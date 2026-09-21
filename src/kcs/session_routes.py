from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth_routes import StrictModel
from .models import AuditEvent, Conversation, ConversationMessage
from .policy import AgentAuth, allowed_subject_ids, locked_agent_auth
from .security import get_db

router = APIRouter(prefix="/v1/sessions")


class SessionInput(StrictModel):
    subject_id: str = Field(min_length=1, max_length=32)
    idempotency_key: str = Field(min_length=1, max_length=128)


class MessageInput(StrictModel):
    message_id: str = Field(min_length=1, max_length=128)
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=32000)


def session_payload(row):
    return {
        "id": row.id,
        "subject_id": row.subject_id,
        "created_at": row.created_at,
        "message_count": row.message_count,
    }


def message_payload(row):
    return {
        "id": row.id,
        "message_id": row.message_id,
        "sequence": row.sequence,
        "role": row.role,
        "content": row.content,
        "created_at": row.created_at,
    }


def authorized_session(db, auth, session_id):
    row = db.scalar(
        select(Conversation).where(
            Conversation.id == session_id,
            Conversation.tenant_id == auth.tenant_id,
            Conversation.agent_id == auth.agent_id,
        )
    )
    if not row or row.subject_id not in allowed_subject_ids(db, auth):
        raise HTTPException(404, "找不到會話")
    return row


@router.post("", status_code=201)
def create_session(
    body: SessionInput,
    request: Request,
    auth: AgentAuth = Depends(locked_agent_auth),
    db: Session = Depends(get_db),
):
    if body.subject_id not in allowed_subject_ids(db, auth):
        raise HTTPException(404, "找不到服務對象")
    row = db.scalar(
        select(Conversation).where(
            Conversation.tenant_id == auth.tenant_id,
            Conversation.agent_id == auth.agent_id,
            Conversation.idempotency_key == body.idempotency_key,
        )
    )
    if row:
        if row.subject_id != body.subject_id:
            raise HTTPException(409, "冪等鍵已用於其他服務對象")
        return session_payload(row)
    row = Conversation(
        tenant_id=auth.tenant_id,
        agent_id=auth.agent_id,
        subject_id=body.subject_id,
        idempotency_key=body.idempotency_key,
    )
    db.add(row)
    db.flush()
    db.add(
        AuditEvent(
            tenant_id=auth.tenant_id,
            actor_id=auth.agent_id,
            action="session.created",
            target_id=row.id,
            request_id=request.state.request_id,
            details={"credential_id": auth.credential_id, "subject_id": row.subject_id},
        )
    )
    return session_payload(row)


@router.get("")
def list_sessions(
    auth: AgentAuth = Depends(locked_agent_auth),
    db: Session = Depends(get_db),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
):
    rows = db.scalars(
        select(Conversation)
        .where(
            Conversation.tenant_id == auth.tenant_id,
            Conversation.agent_id == auth.agent_id,
            Conversation.subject_id.in_(allowed_subject_ids(db, auth)),
        )
        .order_by(Conversation.created_at.desc(), Conversation.id)
        .offset(offset)
        .limit(limit)
    )
    return {"items": [session_payload(row) for row in rows]}


@router.get("/{session_id}/messages")
def messages(
    session_id: str,
    auth: AgentAuth = Depends(locked_agent_auth),
    db: Session = Depends(get_db),
    after_sequence: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
):
    authorized_session(db, auth, session_id)
    rows = db.scalars(
        select(ConversationMessage)
        .where(
            ConversationMessage.tenant_id == auth.tenant_id,
            ConversationMessage.session_id == session_id,
            ConversationMessage.sequence > after_sequence,
        )
        .order_by(ConversationMessage.sequence)
        .limit(limit)
    )
    return {"items": [message_payload(row) for row in rows]}


@router.post("/{session_id}/messages", status_code=201)
def add_message(
    session_id: str,
    body: MessageInput,
    request: Request,
    auth: AgentAuth = Depends(locked_agent_auth),
    db: Session = Depends(get_db),
):
    session = authorized_session(db, auth, session_id)
    row = db.scalar(
        select(ConversationMessage).where(
            ConversationMessage.session_id == session_id, ConversationMessage.message_id == body.message_id
        )
    )
    if row:
        if row.role != body.role or row.content != body.content:
            raise HTTPException(409, "訊息識別碼已存在且內容不同")
        return message_payload(row)
    session.message_count += 1
    row = ConversationMessage(
        tenant_id=auth.tenant_id,
        agent_id=auth.agent_id,
        subject_id=session.subject_id,
        session_id=session.id,
        message_id=body.message_id,
        role=body.role,
        content=body.content,
        sequence=session.message_count,
    )
    db.add(row)
    db.flush()
    db.add(
        AuditEvent(
            tenant_id=auth.tenant_id,
            actor_id=auth.agent_id,
            action="session.message_added",
            target_id=row.id,
            request_id=request.state.request_id,
            details={"session_id": session.id, "credential_id": auth.credential_id},
        )
    )
    return message_payload(row)
