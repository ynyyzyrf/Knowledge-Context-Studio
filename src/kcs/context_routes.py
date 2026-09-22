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
from .models import AuditEvent, Document, DocumentChunk, MemoryProjection, MemoryRecord, MemoryRevision
from .namespace_routes import private_owner
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
    db: Session = Depends(get_db),
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
    factory = getattr(request.app.state, "context_engine_factory", None)
    try:
        with factory() if factory else OpenViking(request.app.state.settings) as engine:
            hits = engine.find(roots, body.query, min(100, body.limit * 5)) if roots else []
    except EngineError as error:
        raise HTTPException(503, str(error)) from None
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
        items, documents, sections, used, seen = [], [], [], 0, set()
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
            cost = len(section) + (2 if sections else 0)
            if used + cost > body.max_chars:
                continue
            destination.append(result)
            sections.append(section)
            used += cost
            if len(items) + len(documents) >= body.limit:
                break
        audit(db, request, auth, body.subject_id, "context.read", len(items) + len(documents))
        return {
            "subject_id": body.subject_id,
            "memories": items,
            "documents": documents,
            "request_id": request.state.request_id,
            "context": "\n\n".join(sections),
            "content_role": "untrusted_reference_data",
            "retrieval": "semantic",
            "knowledge_spaces_included": bool(spaces),
            "space_ids": spaces,
        }
