import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .agent_routes import record, subject_for_agent
from .auth_routes import StrictModel
from .models import (
    Agent,
    AuditEvent,
    ConversationMessage,
    MemoryCandidate,
    MemoryProjection,
    MemoryRecord,
    MemoryRevision,
)
from .policy import scoped_object
from .security import PersonAuth, get_db, person_auth, tenant_membership

router = APIRouter(prefix="/v1/tenants/{tenant_id}")


class VersionInput(StrictModel):
    expected_version: int = Field(ge=1)


class ReasonInput(VersionInput):
    reason: str = Field(min_length=1, max_length=1000, pattern=r"\S")


class EditInput(ReasonInput):
    content: str = Field(min_length=1, max_length=4000, pattern=r"\S")


def expected(actual, expected_version):
    if actual != expected_version:
        raise HTTPException(409, "版本已變更，請重新載入後再提交")


def usable_subject(db, tenant_id, agent_id, subject_id):
    agent = scoped_object(db, Agent, tenant_id, agent_id)
    subject = subject_for_agent(db, tenant_id, agent_id, subject_id)
    if not agent.active or not subject.active:
        raise HTTPException(409, "請先啟用 Agent 與服務對象")


def payload(db, memory):
    revision = db.get(MemoryRevision, (memory.id, memory.current_version))
    projection = db.scalar(
        select(MemoryProjection).where(
            MemoryProjection.memory_id == memory.id, MemoryProjection.version == memory.current_version
        )
    )
    return {
        "id": memory.id,
        "agent_id": memory.agent_id,
        "subject_id": memory.subject_id,
        "version": memory.current_version,
        "status": memory.status,
        "content": revision.content,
        "source_message_ids": revision.source_message_ids,
        "updated_at": memory.updated_at,
        "publication": {"id": projection.id, "state": projection.state, "error_code": projection.error_code},
    }


def new_revision(db, memory, auth, request, *, content, sources, status, reason):
    # Mark pending older operations obsolete. Running operations require completion fencing in the publisher.
    db.execute(
        update(MemoryProjection)
        .where(MemoryProjection.memory_id == memory.id, MemoryProjection.state.in_(["pending", "retry"]))
        .values(state="obsolete")
    )
    revision = MemoryRevision(
        memory_id=memory.id,
        version=memory.current_version,
        tenant_id=memory.tenant_id,
        agent_id=memory.agent_id,
        subject_id=memory.subject_id,
        content=content,
        source_message_ids=sources,
        status=status,
        reason=reason,
        actor_id=auth.person.id,
    )
    db.add(revision)
    db.flush()
    db.add(
        MemoryProjection(
            tenant_id=memory.tenant_id,
            agent_id=memory.agent_id,
            subject_id=memory.subject_id,
            memory_id=memory.id,
            version=memory.current_version,
            kind="upsert" if status == "pending" else "delete",
            request_id=request.state.request_id,
        )
    )
    memory.status, memory.updated_at = status, time.time()
    db.flush()


@router.post("/candidates/{candidate_id}/approve", status_code=202)
def approve(
    tenant_id: str,
    candidate_id: str,
    body: VersionInput,
    request: Request,
    auth: PersonAuth = Depends(person_auth),
    db: Session = Depends(get_db),
):
    tenant_membership(db, tenant_id, auth, admin=True)
    candidate = scoped_object(db, MemoryCandidate, tenant_id, candidate_id)
    expected(candidate.version, body.expected_version)
    if candidate.status != "candidate":
        raise HTTPException(409, "候選已處理")
    usable_subject(db, tenant_id, candidate.agent_id, candidate.subject_id)
    memory = MemoryRecord(
        tenant_id=tenant_id,
        agent_id=candidate.agent_id,
        subject_id=candidate.subject_id,
        candidate_id=candidate.id,
    )
    db.add(memory)
    db.flush()
    candidate.status, candidate.version = "approved", candidate.version + 1
    new_revision(
        db,
        memory,
        auth,
        request,
        content=candidate.content,
        sources=candidate.source_message_ids,
        status="pending",
        reason="Candidate approved",
    )
    record(db, request, auth, tenant_id, "memory.approved", memory.id, {"candidate_id": candidate.id})
    return payload(db, memory)


@router.post("/candidates/{candidate_id}/reject")
def reject(
    tenant_id: str,
    candidate_id: str,
    body: ReasonInput,
    request: Request,
    auth: PersonAuth = Depends(person_auth),
    db: Session = Depends(get_db),
):
    tenant_membership(db, tenant_id, auth, admin=True)
    candidate = scoped_object(db, MemoryCandidate, tenant_id, candidate_id)
    expected(candidate.version, body.expected_version)
    if candidate.status != "candidate":
        raise HTTPException(409, "候選已處理")
    candidate.status, candidate.version = "rejected", candidate.version + 1
    record(db, request, auth, tenant_id, "candidate.rejected", candidate.id, {"reason": body.reason})
    return {"id": candidate.id, "status": candidate.status, "version": candidate.version}


def mutable_memory(db, tenant_id, memory_id, body):
    memory = scoped_object(db, MemoryRecord, tenant_id, memory_id)
    expected(memory.current_version, body.expected_version)
    if memory.status == "deleted":
        raise HTTPException(409, "記憶已刪除")
    return memory


@router.patch("/memories/{memory_id}", status_code=202)
def edit_memory(
    tenant_id: str,
    memory_id: str,
    body: EditInput,
    request: Request,
    auth: PersonAuth = Depends(person_auth),
    db: Session = Depends(get_db),
):
    tenant_membership(db, tenant_id, auth, admin=True)
    memory = mutable_memory(db, tenant_id, memory_id, body)
    usable_subject(db, tenant_id, memory.agent_id, memory.subject_id)
    previous = db.get(MemoryRevision, (memory.id, memory.current_version))
    previous.status = "superseded"
    memory.current_version += 1
    new_revision(
        db,
        memory,
        auth,
        request,
        content=body.content,
        sources=previous.source_message_ids,
        status="pending",
        reason=body.reason,
    )
    record(db, request, auth, tenant_id, "memory.edited", memory.id, {"version": memory.current_version})
    return payload(db, memory)


def stop_memory(db, tenant_id, memory_id, body, request, auth, *, delete):
    tenant_membership(db, tenant_id, auth, admin=True)
    memory = mutable_memory(db, tenant_id, memory_id, body)
    previous = db.get(MemoryRevision, (memory.id, memory.current_version))
    previous.status = "superseded"
    content, sources = previous.content, previous.source_message_ids
    memory.current_version += 1
    if delete:
        db.execute(update(MemoryRevision).where(MemoryRevision.memory_id == memory.id).values(content=None))
        candidate = db.get(MemoryCandidate, memory.candidate_id)
        candidate.content = ""
        content = None
    new_revision(
        db,
        memory,
        auth,
        request,
        content=content,
        sources=sources,
        status="deleted" if delete else "disabled",
        reason=body.reason,
    )
    record(
        db,
        request,
        auth,
        tenant_id,
        "memory.deleted" if delete else "memory.disabled",
        memory.id,
        {"version": memory.current_version},
    )
    return payload(db, memory)


@router.post("/memories/{memory_id}/disable", status_code=202)
def disable(
    tenant_id: str,
    memory_id: str,
    body: ReasonInput,
    request: Request,
    auth: PersonAuth = Depends(person_auth),
    db: Session = Depends(get_db),
):
    return stop_memory(db, tenant_id, memory_id, body, request, auth, delete=False)


@router.post("/memories/{memory_id}/delete", status_code=202)
def delete_memory(
    tenant_id: str,
    memory_id: str,
    body: ReasonInput,
    request: Request,
    auth: PersonAuth = Depends(person_auth),
    db: Session = Depends(get_db),
):
    return stop_memory(db, tenant_id, memory_id, body, request, auth, delete=True)


@router.get("/agents/{agent_id}/subjects/{subject_id}/cognition")
def cognition(
    tenant_id: str,
    agent_id: str,
    subject_id: str,
    request: Request,
    auth: PersonAuth = Depends(person_auth),
    db: Session = Depends(get_db),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
):
    tenant_membership(db, tenant_id, auth, admin=True)
    subject_for_agent(db, tenant_id, agent_id, subject_id)
    candidates = db.scalars(
        select(MemoryCandidate)
        .where(
            MemoryCandidate.tenant_id == tenant_id,
            MemoryCandidate.agent_id == agent_id,
            MemoryCandidate.subject_id == subject_id,
        )
        .order_by(MemoryCandidate.created_at.desc(), MemoryCandidate.id)
        .offset(offset)
        .limit(limit)
    )
    memories = db.scalars(
        select(MemoryRecord)
        .where(
            MemoryRecord.tenant_id == tenant_id,
            MemoryRecord.agent_id == agent_id,
            MemoryRecord.subject_id == subject_id,
        )
        .order_by(MemoryRecord.updated_at.desc(), MemoryRecord.id)
        .offset(offset)
        .limit(limit)
    )
    result = {
        "candidates": [
            {
                "id": c.id,
                "version": c.version,
                "content": c.content,
                "status": c.status,
                "source_message_ids": c.source_message_ids,
            }
            for c in candidates
        ],
        "memories": [payload(db, memory) for memory in memories],
    }
    db.add(
        AuditEvent(
            tenant_id=tenant_id,
            actor_id=auth.person.id,
            action="cognition.viewed",
            target_id=subject_id,
            request_id=request.state.request_id,
        )
    )
    return result


@router.get("/candidates/{candidate_id}/provenance")
def candidate_provenance(
    tenant_id: str,
    candidate_id: str,
    request: Request,
    auth: PersonAuth = Depends(person_auth),
    db: Session = Depends(get_db),
):
    tenant_membership(db, tenant_id, auth, admin=True)
    candidate = scoped_object(db, MemoryCandidate, tenant_id, candidate_id)
    source_ids = candidate.source_message_ids if candidate.content else []
    rows = db.scalars(
        select(ConversationMessage).where(
            ConversationMessage.tenant_id == tenant_id,
            ConversationMessage.agent_id == candidate.agent_id,
            ConversationMessage.subject_id == candidate.subject_id,
            ConversationMessage.id.in_(source_ids),
        )
    )
    db.add(
        AuditEvent(
            tenant_id=tenant_id,
            actor_id=auth.person.id,
            action="candidate.provenance_viewed",
            target_id=candidate.id,
            request_id=request.state.request_id,
        )
    )
    return {
        "messages": [
            {"id": m.id, "session_id": m.session_id, "role": m.role, "content": m.content} for m in rows
        ]
    }


@router.get("/memories/{memory_id}/provenance")
def provenance(
    tenant_id: str,
    memory_id: str,
    request: Request,
    auth: PersonAuth = Depends(person_auth),
    db: Session = Depends(get_db),
):
    tenant_membership(db, tenant_id, auth, admin=True)
    memory = scoped_object(db, MemoryRecord, tenant_id, memory_id)
    revisions = list(
        db.scalars(
            select(MemoryRevision)
            .where(MemoryRevision.memory_id == memory_id)
            .order_by(MemoryRevision.version)
        )
    )
    source_ids = set(revisions[-1].source_message_ids) if memory.status != "deleted" else set()
    messages = db.scalars(
        select(ConversationMessage).where(
            ConversationMessage.tenant_id == tenant_id,
            ConversationMessage.agent_id == memory.agent_id,
            ConversationMessage.subject_id == memory.subject_id,
            ConversationMessage.id.in_(source_ids),
        )
    )
    db.add(
        AuditEvent(
            tenant_id=tenant_id,
            actor_id=auth.person.id,
            action="memory.provenance_viewed",
            target_id=memory.id,
            request_id=request.state.request_id,
        )
    )
    return {
        "revisions": [
            {
                "version": r.version,
                "status": r.status,
                "content": r.content,
                "reason": r.reason,
                "actor_id": r.actor_id,
                "created_at": r.created_at,
            }
            for r in revisions
        ],
        "messages": [
            {"id": m.id, "session_id": m.session_id, "role": m.role, "content": m.content} for m in messages
        ],
    }
