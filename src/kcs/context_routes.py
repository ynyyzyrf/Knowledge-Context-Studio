from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import Field
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from .auth_routes import StrictModel
from .engine import (
    EngineError,
    OpenViking,
    document_uri,
    memory_uri,
    private_space_uri,
    space_uri,
    subject_uri,
)
from .model_service import ModelService, ModelServiceError
from .models import (
    AuditEvent,
    Document,
    DocumentChunk,
    MemoryProjection,
    MemoryRecord,
    MemoryRevision,
    NamespaceEntry,
)
from .namespace_routes import private_owner
from .personal_context_routes import agent_namespace
from .personal_context_routes import conditions as namespace_conditions
from .personal_context_routes import payload as namespace_payload
from .personal_index import configured, model_key
from .personal_retrieval import allocate, rank
from .policy import AgentAuth, agent_auth, allowed_space_ids, allowed_subject_ids, locked_agent_auth
from .security import get_db

router = APIRouter(prefix="/v1")


class ContextInput(StrictModel):
    subject_id: str = Field(min_length=1, max_length=32)
    query: str = Field(min_length=1, max_length=2000, pattern=r"\S")
    limit: int = Field(default=8, ge=1, le=20)
    max_chars: int = Field(default=12000, ge=4000, le=40000)
    space_ids: list[str] | None = Field(default=None, max_length=10)


def private_scopes(db, auth, spaces):
    result = {}
    for identity in spaces:
        try:
            result[identity] = private_owner(db, auth, identity)
        except HTTPException as error:
            if error.status_code != 404:
                raise
    return result


def personal_filters(db, auth, spaces):
    filters = []
    for space_id in spaces:
        for kind in ("memories", "skills", "peers"):
            try:
                who = agent_namespace(db, auth, space_id, kind)
            except HTTPException as error:
                if error.status_code != 404:
                    raise
                continue
            filters.append(and_(*namespace_conditions(who, space_id, kind)))
    return filters


def check_subject(db, auth, subject_id):
    if subject_id not in allowed_subject_ids(db, auth):
        raise HTTPException(404, "找不到服務對象")


def active_rows(auth, subject_id):
    return (
        select(MemoryRecord, MemoryRevision)
        .join(
            MemoryRevision,
            (MemoryRevision.memory_id == MemoryRecord.id)
            & (MemoryRevision.version == MemoryRecord.current_version),
        )
        .join(
            MemoryProjection,
            (MemoryProjection.memory_id == MemoryRecord.id)
            & (MemoryProjection.version == MemoryRecord.current_version),
        )
        .where(
            MemoryRecord.tenant_id == auth.tenant_id,
            MemoryRecord.agent_id == auth.agent_id,
            MemoryRecord.subject_id == subject_id,
            MemoryRecord.status == "active",
            MemoryRevision.status == "active",
            MemoryProjection.state == "succeeded",
            MemoryProjection.kind == "upsert",
        )
    )


def item(memory, revision):
    return {
        "id": memory.id,
        "version": revision.version,
        "content": revision.content,
        "source_message_ids": revision.source_message_ids,
        "updated_at": memory.updated_at,
    }


def audit(db, request, auth, subject_id, action, count):
    db.add(
        AuditEvent(
            tenant_id=auth.tenant_id,
            actor_id=auth.agent_id,
            target_id=subject_id,
            action=action,
            request_id=request.state.request_id,
            details={"count": count},
        )
    )


@router.get("/subjects/{subject_id}/memories")
def list_memories(
    subject_id: str,
    request: Request,
    auth: AgentAuth = Depends(locked_agent_auth),
    db: Session = Depends(get_db, scope="function"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    check_subject(db, auth, subject_id)
    rows = db.execute(
        active_rows(auth, subject_id).order_by(MemoryRecord.id).offset(offset).limit(limit + 1)
    ).all()
    items = [item(m, r) for m, r in rows[:limit]]
    audit(db, request, auth, subject_id, "memory.read", len(items))
    return {"items": items, "has_more": len(rows) > limit}


@router.post("/context")
def context(body: ContextInput, request: Request):
    database = request.app.state.database
    settings = request.app.state.settings
    key = model_key(settings)
    # Never hold a policy lock or transaction during network I/O.
    with database.sessions.begin() as db:
        auth = agent_auth(request, db)
        check_subject(db, auth, body.subject_id)
        root = subject_uri(auth.tenant_id, auth.agent_id, body.subject_id)
        allowed = allowed_space_ids(db, auth)
        spaces = list(dict.fromkeys(body.space_ids)) if body.space_ids is not None else allowed
        if any(identity not in allowed for identity in spaces):
            raise HTTPException(404, "找不到授權知識空間")
        if len(spaces) > 10:
            raise HTTPException(422, "請指定本次查詢的 space_ids，最多 10 個空間")
        include_legacy_memory = body.space_ids is None
        owners = private_scopes(db, auth, spaces)
        roots = ([root] if include_legacy_memory else []) + [space_uri(auth.tenant_id, s) for s in spaces]
        roots += [private_space_uri(auth.tenant_id, s, owner) for s, owner in owners.items()]
        filters = personal_filters(db, auth, spaces)
        has_vectors = (
            bool(filters)
            and db.scalar(
                select(NamespaceEntry.id)
                .where(
                    or_(*filters),
                    NamespaceEntry.status == "active",
                    NamespaceEntry.embedding_version == NamespaceEntry.version,
                    NamespaceEntry.embedding_model_key == key,
                )
                .limit(1)
            )
            is not None
        )
    factory = getattr(request.app.state, "context_engine_factory", None)
    try:
        with factory() if factory else OpenViking(request.app.state.settings) as engine:
            hits = engine.find(roots, body.query, min(100, body.limit * 5)) if roots else []
    except EngineError as error:
        raise HTTPException(503, str(error)) from None
    query_vector, degraded_reason = None, None
    model_factory = getattr(request.app.state, "personal_model_factory", None)
    if has_vectors and (model_factory or configured(settings)):
        try:
            with model_factory() if model_factory else ModelService(settings) as model:
                query_vector = model.embed([body.query]).vectors[0]
        except ModelServiceError as error:
            degraded_reason = error.code
    elif not (model_factory or configured(settings)):
        degraded_reason = "embedding_not_configured"
    else:
        degraded_reason = "index_pending"
    with database.sessions.begin() as db:
        auth = locked_agent_auth(request, auth, db)
        check_subject(db, auth, body.subject_id)
        spaces = [s for s in spaces if s in allowed_space_ids(db, auth)]
        owners = private_scopes(db, auth, spaces)
        document_roots = [space_uri(auth.tenant_id, s) for s in spaces]
        document_roots += [private_space_uri(auth.tenant_id, s, owner) for s, owner in owners.items()]
        # Engine hits are untrusted hints. Only the exact current published URI is accepted.
        candidates = {}
        for uri, score in hits:
            prefix = root + "/"
            if include_legacy_memory and isinstance(uri, str) and uri.startswith(prefix):
                parts = uri[len(prefix) :].split("/")
                if len(parts) == 2:
                    candidates[parts[0]] = (uri, score)
        rows = db.execute(active_rows(auth, body.subject_id).where(MemoryRecord.id.in_(candidates))).all()
        verified = {memory_uri(m): (m, r) for m, r in rows}
        document_ids = set()
        for uri, _ in hits:
            for document_root in document_roots:
                prefix = document_root + "/"
                if isinstance(uri, str) and uri.startswith(prefix):
                    parts = uri[len(prefix) :].split("/")
                    if len(parts) == 2:
                        document_ids.add(parts[0])
        chunks = db.execute(
            select(Document, DocumentChunk)
            .join(DocumentChunk, DocumentChunk.document_id == Document.id)
            .where(
                Document.tenant_id == auth.tenant_id,
                Document.space_id.in_(spaces),
                or_(
                    Document.owner_person_id.is_(None),
                    *[
                        and_(Document.space_id == s, Document.owner_person_id == owner)
                        for s, owner in owners.items()
                    ],
                ),
                Document.id.in_(document_ids),
                Document.deleted.is_(False),
                Document.state == "succeeded",
            )
        ).all()
        verified_documents = {document_uri(d, c.number): (d, c) for d, c in chunks}
        items, documents, sections, seen = [], [], [], set()
        document_pool, personal_pool, results = [], [], {}
        for uri, _ in hits:
            if uri in seen:
                continue
            seen.add(uri)
            if uri in verified:
                m, r = verified[uri]
                section = f"[memory:{m.id}@v{r.version}]\n{r.content}"
                result = item(m, r)
                destination = items
            elif uri in verified_documents:
                d, c = verified_documents[uri]
                section = f"[document:{d.id}@v1#chunk{c.number}]\n{c.content}"
                result = {
                    "id": d.id,
                    "version": 1,
                    "space_id": d.space_id,
                    "filename": d.filename,
                    "scope": "private" if d.owner_person_id else "shared",
                    "resource_path": d.resource_path,
                    "chunk": c.number,
                    "page": c.page,
                    "content": c.content,
                    "checksum": d.checksum,
                }
                destination = documents
            else:
                continue
            results[uri] = (destination, result)
            document_pool.append((uri, section))
        personal = []
        filters = personal_filters(db, auth, spaces)
        personal_rows = (
            db.scalars(
                select(NamespaceEntry).where(
                    or_(*filters),
                    NamespaceEntry.status == "active",
                )
            ).yield_per(50)
            if filters
            else []
        )
        # Rows, versions and grants are loaded again after ALL network I/O, under the policy lock.
        ranked, stats = rank(personal_rows, body.query, query_vector, key, max_chars=body.max_chars)
        for row in ranked:
            identity = "personal:" + row.id
            section = f"[personal:{row.kind}:{row.id}@v{row.version}]\n{row.content}"
            results[identity] = (
                personal,
                {**namespace_payload(row, settings=settings), "space_id": row.space_id},
            )
            personal_pool.append((identity, section))
        for identity, section in allocate(
            document_pool, personal_pool, limit=body.limit, max_chars=body.max_chars
        ):
            destination, result = results[identity]
            destination.append(result)
            sections.append(section)
        mode = "hybrid" if query_vector is not None and stats["indexed_count"] else "keyword"
        audit(db, request, auth, body.subject_id, "context.read", len(items) + len(documents) + len(personal))
        return {
            "subject_id": body.subject_id,
            "memories": items,
            "documents": documents,
            "personal_context": personal,
            "personal_context_retrieval": mode,
            "personal_retrieval": {
                "mode": mode,
                "degraded_reason": degraded_reason,
                **stats,
            },
            "request_id": request.state.request_id,
            "context": "\n\n".join(sections),
            "content_role": "untrusted_reference_data",
            "retrieval": "semantic",
            "knowledge_spaces_included": bool(spaces),
            "space_ids": spaces,
        }
