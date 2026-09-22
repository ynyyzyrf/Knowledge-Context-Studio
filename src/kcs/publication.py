"""Leased memory publication; engine I/O is outside product transactions."""

import time
import uuid
from dataclasses import dataclass

from sqlalchemy import and_, case, or_, select

from .engine import EngineError, OpenViking, memory_uri
from .models import Agent, AuditEvent, MemoryProjection, MemoryRecord, MemoryRevision, Subject, Tenant


@dataclass(frozen=True)
class Publication:
    id: str
    tenant_id: str
    lease_token: str
    memory: MemoryRecord
    version: int
    kind: str
    content: str | None
    versions: tuple[int, ...]


def claim(database, seconds):
    now = time.time()
    with database.sessions.begin() as db:
        ids = db.execute(
            select(MemoryProjection.id, MemoryProjection.tenant_id)
            .where(
                or_(
                    and_(
                        MemoryProjection.state.in_(["pending", "retry"]), MemoryProjection.available_at <= now
                    ),
                    and_(MemoryProjection.state == "running", MemoryProjection.lease_until <= now),
                    MemoryProjection.state == "obsolete",
                    and_(
                        MemoryProjection.kind == "delete",
                        MemoryProjection.state == "succeeded",
                        MemoryProjection.available_at <= now,
                    ),
                )
            )
            .order_by(
                case((MemoryProjection.state.in_(["pending", "retry", "running"]), 0), else_=1),
                MemoryProjection.created_at,
                MemoryProjection.version,
            )
            .limit(100)
        ).all()
        for identity, tenant_id in ids:
            # Match governance lock ordering: tenant before projection.
            tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update(skip_locked=True))
            if tenant is None:
                continue
            p = db.scalar(select(MemoryProjection).where(MemoryProjection.id == identity).with_for_update())
            if (
                p.state not in ("pending", "retry", "running", "obsolete", "succeeded")
                or (p.state == "running" and p.lease_until > now)
                or (p.state == "succeeded" and (p.kind != "delete" or p.available_at > now))
            ):
                continue
            memory = db.get(MemoryRecord, p.memory_id)
            if p.version != memory.current_version and p.kind == "upsert":
                p.kind, p.attempt = "delete", 0
            if p.state == "succeeded":
                p.attempt = 0
            if p.kind == "delete" and db.scalar(
                select(MemoryProjection.id)
                .where(
                    MemoryProjection.memory_id == p.memory_id,
                    MemoryProjection.kind == "upsert",
                    MemoryProjection.state == "running",
                    MemoryProjection.lease_until > now,
                )
                .limit(1)
            ):
                continue
            if p.attempt >= 3 and p.kind != "delete":
                p.state, p.error_code = "failed", "publication_attempts_exhausted"
                continue
            if p.kind == "upsert" and (
                not tenant.active
                or not db.get(Agent, p.agent_id).active
                or not db.get(Subject, p.subject_id).active
            ):
                p.state, p.error_code = "failed", "publication_scope_disabled"
                continue
            p.state, p.attempt = "running", p.attempt + 1
            p.lease_token, p.lease_until = uuid.uuid4().hex, now + seconds
            revision = db.get(MemoryRevision, (p.memory_id, p.version))
            versions = tuple(
                db.scalars(
                    select(MemoryRevision.version).where(
                        MemoryRevision.memory_id == p.memory_id, MemoryRevision.version <= p.version
                    )
                )
            )
            if p.version != memory.current_version:
                versions = (p.version,)
            return Publication(
                p.id, p.tenant_id, p.lease_token, memory, p.version, p.kind, revision.content, versions
            )
    return None


def finish(database, task, error=None):
    with database.sessions.begin() as db:
        tenant = db.scalar(select(Tenant).where(Tenant.id == task.tenant_id).with_for_update())
        p = db.scalar(select(MemoryProjection).where(MemoryProjection.id == task.id).with_for_update())
        if p.state != "running" or p.lease_token != task.lease_token or p.lease_until <= time.time():
            return False
        memory = db.get(MemoryRecord, p.memory_id)
        if memory.current_version != p.version and task.kind == "upsert":
            p.state = "obsolete"
        else:
            if p.kind == "upsert" and (
                not tenant.active
                or not db.get(Agent, p.agent_id).active
                or not db.get(Subject, p.subject_id).active
            ):
                error = "publication_scope_disabled"
            if error:
                retryable = p.kind == "delete" or error in ("engine_timeout", "engine_unavailable")
                p.state = "retry" if retryable and (p.kind == "delete" or p.attempt < 3) else "failed"
                if p.kind == "delete":
                    p.attempt = min(p.attempt, 2)
                p.error_code, p.available_at = error, time.time() + min(300, 5 * 2**p.attempt)
            else:
                p.state, p.error_code = "succeeded", None
                if p.kind == "delete":
                    # Reconcile unknown late remote completions, including process crashes.
                    p.available_at = time.time() + 60
                if p.kind == "upsert" and memory.status == "pending":
                    memory.status, memory.updated_at = "active", time.time()
                    db.get(MemoryRevision, (memory.id, p.version)).status = "active"
            db.add(
                AuditEvent(
                    tenant_id=p.tenant_id,
                    actor_id="publisher",
                    action="memory.publication",
                    target_id=memory.id,
                    request_id=p.request_id,
                    details={"version": p.version, "state": p.state, "error_code": p.error_code},
                )
            )
        p.lease_token, p.lease_until = None, None
        return p.state == "succeeded"


def queue_stale_cleanup(database, task):
    """A late writer must invalidate cleanup that may have completed before it."""
    if task.kind != "upsert":
        return
    with database.sessions.begin() as db:
        db.scalar(select(Tenant).where(Tenant.id == task.tenant_id).with_for_update())
        memory = db.get(MemoryRecord, task.memory.id)
        if memory.current_version == task.version:
            return
        p = db.get(MemoryProjection, task.id)
        p.kind, p.state, p.attempt = "delete", "pending", 0
        p.available_at, p.error_code = time.time(), None
        p.lease_token, p.lease_until = None, None


def renew(database, task, seconds):
    with database.sessions.begin() as db:
        db.scalar(select(Tenant).where(Tenant.id == task.tenant_id).with_for_update())
        p = db.get(MemoryProjection, task.id)
        if p.state != "running" or p.lease_token != task.lease_token or p.lease_until <= time.time():
            raise EngineError("publication_lease_lost")
        p.lease_until = time.time() + seconds


def run_one(database, settings, *, engine_factory=None):
    if engine_factory is None and (not settings.engine_url or not settings.engine_api_key.get_secret_value()):
        return False
    task = claim(database, settings.engine_timeout_seconds * 2 + 30)
    if task is None:
        return False
    try:
        with engine_factory() if engine_factory else OpenViking(settings) as engine:
            if task.kind == "upsert":
                engine.publish(memory_uri(task.memory, task.version), task.content)
            else:
                for version in task.versions:
                    renew(database, task, settings.engine_timeout_seconds * 2 + 30)
                    engine.delete(memory_uri(task.memory, version))
            finish(database, task)
    except EngineError as error:
        finish(database, task, str(error))
    except Exception:  # noqa: BLE001 -- sanitize external worker-boundary errors
        finish(database, task, "publication_internal_error")
    finally:
        queue_stale_cleanup(database, task)
    return True
