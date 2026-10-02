"""Version-fenced, leased personal embeddings; product rows remain the source of truth."""

import hashlib
import time
import uuid
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import and_, or_, select

from .model_service import ModelService, ModelServiceError
from .models import KnowledgeSpace, Membership, NamespaceEntry, Person, Tenant
from .policy import person_space


def model_key(settings):
    value = (
        f"personal-chunks-v1\n{settings.resolved_embedding_base_url.rstrip('/')}\n{settings.embedding_model}"
    )
    return hashlib.sha256(value.encode()).hexdigest()


def configured(settings):
    return bool(
        settings.embedding_model
        and settings.resolved_embedding_base_url
        and settings.resolved_embedding_api_key.get_secret_value()
        and settings.model_base_url
        and settings.model_api_key.get_secret_value()
    )


def reset_index(row):
    row.embedding_vectors = None
    row.embedding_version = 0
    row.embedding_model_key = ""
    row.embedding_attempt = 0
    row.embedding_available_at = 0
    row.embedding_lease_token = None
    row.embedding_lease_until = 0
    row.embedding_error = None


def index_status(row, settings=None):
    if row.kind == "sessions" or row.status != "active":
        return "inactive"
    if settings is not None and row.embedding_model_key != model_key(settings):
        return "pending"
    if row.embedding_vectors and row.embedding_version == row.version:
        return "ready"
    if row.embedding_lease_token and row.embedding_lease_until > time.time():
        return "running"
    if row.embedding_attempt >= 3:
        return "failed"
    return "retry" if row.embedding_error else "pending"


def owner_can_read(db, row):
    person = db.get(Person, row.person_id)
    if not person or not person.active:
        return False
    try:
        person_space(db, row.tenant_id, row.space_id, SimpleNamespace(person=person))
        return True
    except HTTPException:
        return False


def eligible(key, now):
    return (
        NamespaceEntry.status == "active",
        NamespaceEntry.kind.in_(("memories", "skills", "peers")),
        NamespaceEntry.embedding_lease_until <= now,
        or_(
            NamespaceEntry.embedding_model_key != key,
            and_(
                NamespaceEntry.embedding_version != NamespaceEntry.version,
                NamespaceEntry.embedding_attempt < 3,
                NamespaceEntry.embedding_available_at <= now,
            ),
        ),
    )


def claim(database, settings):
    now, key = time.time(), model_key(settings)
    with database.sessions.begin() as db:
        # A disabled owner/space must not repeatedly hide all work behind a small candidate page.
        candidates = db.execute(
            select(NamespaceEntry.id, NamespaceEntry.tenant_id)
            .join(Tenant, Tenant.id == NamespaceEntry.tenant_id)
            .join(Person, Person.id == NamespaceEntry.person_id)
            .join(
                Membership,
                and_(
                    Membership.tenant_id == NamespaceEntry.tenant_id,
                    Membership.person_id == NamespaceEntry.person_id,
                ),
            )
            .join(KnowledgeSpace, KnowledgeSpace.id == NamespaceEntry.space_id)
            .where(
                *eligible(key, now),
                Tenant.active.is_(True),
                Person.active.is_(True),
                Membership.active.is_(True),
                KnowledgeSpace.active.is_(True),
            )
            .order_by(NamespaceEntry.embedding_available_at, NamespaceEntry.updated_at, NamespaceEntry.id)
        )
        for identity, tenant_id in candidates:
            tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update(skip_locked=True))
            if tenant is None or not tenant.active:
                continue
            row = db.scalar(
                select(NamespaceEntry)
                .where(NamespaceEntry.id == identity, *eligible(key, now))
                .with_for_update()
            )
            if row is None or not owner_can_read(db, row):
                continue
            if row.embedding_model_key != key:
                reset_index(row)
            row.embedding_model_key = key
            row.embedding_attempt += 1
            row.embedding_lease_token = uuid.uuid4().hex
            row.embedding_lease_until = now + settings.model_timeout_seconds + 30
            return (
                row.id,
                row.tenant_id,
                row.version,
                key,
                row.embedding_lease_token,
                row.title,
                row.content,
            )
    return None


def run_one(database, settings, *, model_factory=None):
    if model_factory is None and not configured(settings):
        return False
    task = claim(database, settings)
    if task is None:
        return False
    identity, tenant_id, version, key, lease, title, content = task
    vectors, error = None, None
    # <= 20 content chunks + title; each input <= 2,201 characters, no silent tail loss.
    texts = [title + "\n" + content[i : i + 2000] for i in range(0, len(content), 2000)] or [title]
    try:
        with model_factory() if model_factory else ModelService(settings) as model:
            vectors = model.embed(texts).vectors
    except ModelServiceError as exc:
        error = exc.code
    except Exception:  # noqa: BLE001 -- sanitize the worker boundary
        error = "personal_index_internal_error"
    with database.sessions.begin() as db:
        tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
        row = db.get(NamespaceEntry, identity)
        if (
            row is None
            or row.version != version
            or row.status != "active"
            or row.embedding_model_key != key
            or row.embedding_lease_token != lease
            or row.embedding_lease_until <= time.time()
        ):
            return True
        row.embedding_lease_token, row.embedding_lease_until = None, 0
        if not tenant.active or not owner_can_read(db, row):
            reset_index(row)
            return True
        if error:
            row.embedding_error = error
            row.embedding_available_at = time.time() + min(300, 5 * 2**row.embedding_attempt)
        else:
            row.embedding_vectors, row.embedding_version = vectors, version
            row.embedding_error = None
    return True
