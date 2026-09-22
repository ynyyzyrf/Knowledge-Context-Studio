"""Durable document indexing and deletion, with leased and fenced completion."""

import time
import uuid
from dataclasses import dataclass

from sqlalchemy import and_, case, or_, select

from .document_parser import ParseError, parse_isolated
from .engine import EngineError, OpenViking, document_uri
from .models import AuditEvent, Document, DocumentChunk, KnowledgeSpace, Tenant


@dataclass
class Task:
    doc: Document
    token: str
    deleting: bool


def locked(db, task):
    db.scalar(select(Tenant).where(Tenant.id == task.doc.tenant_id).with_for_update())
    doc = db.get(Document, task.doc.id)
    if doc.state != "running" or doc.lease_token != task.token or doc.lease_until <= time.time():
        raise EngineError("document_lease_lost")
    return doc


def claim(database, seconds):
    now = time.time()
    with database.sessions.begin() as db:
        candidates = db.execute(
            select(Document.id, Document.tenant_id)
            .where(
                or_(
                    and_(Document.state.in_(["pending", "retry"]), Document.available_at <= now),
                    and_(Document.state == "running", Document.lease_until <= now),
                    and_(
                        Document.deleted.is_(True),
                        Document.state == "succeeded",
                        Document.available_at <= now,
                    ),
                )
            )
            .order_by(case((Document.state == "succeeded", 1), else_=0), Document.created_at)
            .limit(100)
        ).all()
        for identity, tenant_id in candidates:
            tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update(skip_locked=True))
            if not tenant:
                continue
            doc = db.scalar(select(Document).where(Document.id == identity).with_for_update())
            if (doc.state == "running" and doc.lease_until > now) or doc.available_at > now:
                continue
            if doc.state not in ("pending", "retry", "running") and not (
                doc.deleted and doc.state == "succeeded"
            ):
                continue
            if not doc.deleted and (not tenant.active or not db.get(KnowledgeSpace, doc.space_id).active):
                doc.state, doc.error_code = "failed", "document_space_disabled"
                continue
            if doc.attempt >= 3 and not doc.deleted:
                doc.state, doc.error_code = "failed", "document_attempts_exhausted"
                continue
            doc.state, doc.attempt = "running", min(doc.attempt + 1, 3)
            doc.lease_token, doc.lease_until = uuid.uuid4().hex, now + seconds
            if not doc.deleted and not doc.chunk_count:
                # Load original bytes only for a parser claim, never list/context queries.
                _ = doc.source
            return Task(doc, doc.lease_token, doc.deleted)
    return None


def finish(database, task, error=None):
    with database.sessions.begin() as db:
        db.scalar(select(Tenant).where(Tenant.id == task.doc.tenant_id).with_for_update())
        doc = db.get(Document, task.doc.id)
        if doc.deleted and not task.deleting:
            # Always reschedule after a late writer, even if an intervening cleanup completed.
            doc.state, doc.available_at, doc.attempt = "pending", time.time(), 0
            doc.lease_token, doc.lease_until = None, None
            return
        if doc.state != "running" or doc.lease_token != task.token or doc.lease_until <= time.time():
            return
        if error:
            retryable = doc.deleted or error in (
                "engine_unavailable",
                "engine_timeout",
                "engine_index_incomplete",
            )
            doc.state = "retry" if retryable and (doc.deleted or doc.attempt < 3) else "failed"
            doc.error_code, doc.available_at = error, time.time() + 5 * 2 ** min(doc.attempt, 6)
        else:
            doc.state, doc.error_code, doc.available_at = "succeeded", None, time.time() + 60
            if not doc.deleted:
                db.get(KnowledgeSpace, doc.space_id).sync_state = "ready"
        doc.lease_token, doc.lease_until = None, None
        db.add(
            AuditEvent(
                tenant_id=doc.tenant_id,
                actor_id="document-worker",
                target_id=doc.id,
                request_id=doc.request_id,
                action="document.processed",
                details={"state": doc.state, "deleted": doc.deleted, "error_code": doc.error_code},
            )
        )


def run_one(database, settings, *, engine_factory=None, parser=parse_isolated):
    if engine_factory is None and (not settings.engine_url or not settings.engine_api_key.get_secret_value()):
        return False
    seconds = settings.engine_timeout_seconds * 3 + 45
    task = claim(database, seconds)
    if task is None:
        return False
    try:
        if not task.deleting:
            with database.sessions() as db:
                chunks = list(
                    db.scalars(
                        select(DocumentChunk)
                        .where(DocumentChunk.document_id == task.doc.id)
                        .order_by(DocumentChunk.number)
                    )
                )
            if not chunks:
                parsed = parser(task.doc.source, task.doc.filename)
                with database.sessions.begin() as db:
                    doc = locked(db, task)
                    if doc.deleted:
                        raise EngineError("document_deleted")
                    chunks = [
                        DocumentChunk(
                            document_id=doc.id,
                            number=i,
                            tenant_id=doc.tenant_id,
                            space_id=doc.space_id,
                            **chunk,
                        )
                        for i, chunk in enumerate(parsed)
                    ]
                    db.add_all(chunks)
                    doc.chunk_count = len(chunks)
        else:
            chunks = [None] * task.doc.chunk_count
        with engine_factory() if engine_factory else OpenViking(settings) as engine:
            for number, chunk in enumerate(chunks):
                with database.sessions.begin() as db:
                    doc = locked(db, task)
                    if doc.deleted and not task.deleting:
                        raise EngineError("document_deleted")
                    doc.lease_until = time.time() + seconds
                uri = document_uri(task.doc, number)
                if task.deleting:
                    engine.delete(uri)
                else:
                    engine.publish(uri, chunk.content)
        finish(database, task)
    except (EngineError, ParseError) as error:
        finish(database, task, str(error))
    except Exception:  # noqa: BLE001 -- durable worker boundary, keep internal errors out of public state
        finish(database, task, "document_processing_failed")
    return True
