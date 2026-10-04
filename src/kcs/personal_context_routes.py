"""Person/Space-owned context; separate, explicitly granted Agent read/write scopes."""

import hashlib
import json
import time
from types import SimpleNamespace
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import Field
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from .auth_routes import StrictModel
from .document_routes import lock_permission
from .models import (
    Agent,
    AgentCredential,
    AgentSpaceGrant,
    AuditEvent,
    NamespaceEntry,
    NamespaceMessage,
    NamespaceRevision,
    NamespaceScopeGrant,
    Person,
)
from .personal_index import index_status, reset_index
from .policy import agent_auth, allowed_space_ids, locked_agent_auth, person_space
from .security import get_db

router = APIRouter(prefix="/v1")
Kind = Literal["memories", "sessions", "skills", "peers"]
HUMAN = "/tenants/{tenant_id}/spaces/{space_id}/user/default/{kind}"
MACHINE = "/spaces/{space_id}/user/default/{kind}"


def identity(request, db, tenant_id, space_id, kind, *, write=False):
    if tenant_id != request.path_params.get("tenant_id"):
        raise HTTPException(422, "tenant_id 必須使用人員 API 路徑")
    if tenant_id is not None:
        auth = lock_permission(db, request, tenant_id, space_id, write=False)
        return tenant_id, auth.person.id, "person:" + auth.person.id, False
    auth = locked_agent_auth(request, agent_auth(request, db), db)
    return agent_namespace(db, auth, space_id, kind, write=write)


def agent_namespace(db, auth, space_id, kind, *, write=False):
    cred = db.get(AgentCredential, auth.credential_id)
    owner = db.get(Person, cred.namespace_person_id) if cred.namespace_person_id else None
    if not owner or not owner.active or space_id not in allowed_space_ids(db, auth):
        raise HTTPException(404, "找不到私人上下文授權")
    person_space(db, auth.tenant_id, space_id, SimpleNamespace(person=owner))
    grant = db.get(NamespaceScopeGrant, (auth.tenant_id, space_id, owner.id, auth.agent_id, kind))
    if not grant or not (grant.can_write if write else grant.can_read):
        raise HTTPException(404, "找不到私人上下文授權")
    return auth.tenant_id, owner.id, "agent:" + auth.agent_id, True


def conditions(who, space_id, kind):
    return (
        NamespaceEntry.tenant_id == who[0],
        NamespaceEntry.space_id == space_id,
        NamespaceEntry.person_id == who[1],
        NamespaceEntry.kind == kind,
        NamespaceEntry.status != "deleted",
    )


def entry(db, who, space_id, kind, entry_id, *, writable=False):
    row = db.scalar(
        select(NamespaceEntry).where(*conditions(who, space_id, kind), NamespaceEntry.id == entry_id)
    )
    if not row or (who[3] and row.status != "active"):
        raise HTTPException(404, "找不到上下文資料")
    if who[3] and writable and row.created_by != who[2]:
        raise HTTPException(403, "Agent 只能寫入自己建立的會話")
    return row


def payload(row, *, full=True, settings=None):
    result = {
        key: getattr(row, key)
        for key in (
            "id",
            "kind",
            "title",
            "status",
            "version",
            "created_by",
            "created_at",
            "updated_at",
            "source_message_ids",
        )
    }
    result["uri"] = f"user/default/{row.kind}/{row.id}"
    result["indexing"] = {"state": index_status(row, settings), "error_code": row.embedding_error}
    if full:
        result["content"] = row.content
    return result


def audit(db, request, who, action, target, details=None):
    db.add(
        AuditEvent(
            tenant_id=who[0],
            actor_id=who[2].split(":", 1)[1],
            action="namespace." + action,
            target_id=target,
            request_id=request.state.request_id,
            details=details or {},
        )
    )


def revision(db, row, actor):
    reset_index(row)
    db.add(
        NamespaceRevision(
            entry_id=row.id,
            version=row.version,
            title=row.title,
            content=row.content,
            status=row.status,
            actor_id=actor,
        )
    )


class EntryInput(StrictModel):
    external_id: str = Field(min_length=1, max_length=128, pattern=r"\S")
    title: str = Field(min_length=1, max_length=200, pattern=r"\S")
    content: str = Field(default="", max_length=40000)
    source_message_ids: list[str] = Field(default_factory=list, max_length=50)


class EditInput(StrictModel):
    version: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=200, pattern=r"\S")
    content: str = Field(max_length=40000)
    status: Literal["pending", "active", "disabled"]


class VersionInput(StrictModel):
    version: int = Field(ge=1)


class MessageInput(StrictModel):
    external_id: str = Field(min_length=1, max_length=128, pattern=r"\S")
    role: Literal["user", "assistant", "tool", "system"]
    content: str = Field(min_length=1, max_length=16000, pattern=r"\S")


class GrantInput(StrictModel):
    can_read: bool
    can_write: bool
    auto_store: bool = False


@router.get(HUMAN + "/agent-access")
def grants(
    tenant_id: str,
    space_id: str,
    kind: Kind,
    request: Request,
    db: Session = Depends(get_db, scope="function"),
):
    who = identity(request, db, tenant_id, space_id, kind)
    agents = db.scalars(
        select(Agent)
        .join(AgentSpaceGrant, AgentSpaceGrant.agent_id == Agent.id)
        .where(
            Agent.tenant_id == tenant_id,
            AgentSpaceGrant.tenant_id == tenant_id,
            AgentSpaceGrant.space_id == space_id,
            AgentSpaceGrant.active.is_(True),
            Agent.active.is_(True),
        )
    )
    items = []
    for a in agents:
        g = db.get(NamespaceScopeGrant, (tenant_id, space_id, who[1], a.id, kind))
        items.append(
            {
                "agent_id": a.id,
                "name": a.name,
                "can_read": bool(g and g.can_read),
                "can_write": bool(g and g.can_write),
                "auto_store": bool(g and g.auto_store),
            }
        )
    return {"items": items}


@router.put(HUMAN + "/agent-access/{agent_id}")
def set_grant(
    tenant_id: str,
    space_id: str,
    kind: Kind,
    agent_id: str,
    body: GrantInput,
    request: Request,
    db: Session = Depends(get_db, scope="function"),
):
    who = identity(request, db, tenant_id, space_id, kind, write=True)
    if body.auto_store and (kind != "memories" or not body.can_write):
        raise HTTPException(422, "自動存儲僅適用於已授權寫入的記憶目錄")
    a = db.get(Agent, agent_id)
    g = db.get(AgentSpaceGrant, (tenant_id, space_id, agent_id))
    if (
        not a
        or a.tenant_id != tenant_id
        or not g
        or ((body.can_read or body.can_write) and (not a.active or not g.active))
    ):
        raise HTTPException(404, "找不到空間內的 Agent")
    row = db.get(NamespaceScopeGrant, (tenant_id, space_id, who[1], agent_id, kind))
    if row is None:
        row = NamespaceScopeGrant(
            tenant_id=tenant_id, space_id=space_id, person_id=who[1], agent_id=agent_id, kind=kind
        )
        db.add(row)
    row.can_read, row.can_write = body.can_read, body.can_write
    row.auto_store = body.auto_store
    audit(db, request, who, kind + ".grant", agent_id, {"space_id": space_id, **body.model_dump()})
    return body.model_dump()


@router.get(HUMAN + "/entries")
@router.get(MACHINE + "/entries")
def entries(
    space_id: str,
    kind: Kind,
    request: Request,
    tenant_id: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    q: str = Query("", max_length=200),
    db: Session = Depends(get_db, scope="function"),
):
    who = identity(request, db, tenant_id, space_id, kind)
    filters = list(conditions(who, space_id, kind))
    if who[3]:
        filters.append(NamespaceEntry.status == "active")
    if q.strip():
        filters.append(
            or_(
                NamespaceEntry.title.icontains(q.strip(), autoescape=True),
                NamespaceEntry.content.icontains(q.strip(), autoescape=True),
            )
        )
    total = db.scalar(select(func.count()).select_from(NamespaceEntry).where(*filters))
    rows = db.scalars(
        select(NamespaceEntry)
        .where(*filters)
        .order_by(NamespaceEntry.updated_at.desc(), NamespaceEntry.id)
        .offset(offset)
        .limit(limit)
    )
    return {
        "items": [payload(row, full=False, settings=request.app.state.settings) for row in rows],
        "total": total,
        "search_mode": "keyword",
        "content_role": "untrusted_reference_data",
    }


@router.post(HUMAN + "/entries", status_code=201)
@router.post(MACHINE + "/entries", status_code=201)
def create_entry(
    space_id: str,
    kind: Kind,
    body: EntryInput,
    request: Request,
    tenant_id: str | None = None,
    db: Session = Depends(get_db, scope="function"),
):
    who = identity(request, db, tenant_id, space_id, kind, write=True)
    if kind != "sessions" and not body.content.strip():
        raise HTTPException(422, "內容不能為空")
    fingerprint = hashlib.sha256(json.dumps(body.model_dump(), sort_keys=True).encode()).hexdigest()
    old = db.scalar(
        select(NamespaceEntry).where(
            NamespaceEntry.tenant_id == who[0],
            NamespaceEntry.space_id == space_id,
            NamespaceEntry.person_id == who[1],
            NamespaceEntry.kind == kind,
            NamespaceEntry.created_by == who[2],
            NamespaceEntry.external_id == body.external_id,
        )
    )
    if old:
        if old.input_hash != fingerprint or old.status == "deleted":
            raise HTTPException(409, "此請求識別碼已使用，請使用新的 external_id")
        # Never return subsequently edited content through a write-only Agent grant.
        return {
            "id": old.id,
            "status": old.status,
            "version": old.version,
            "replayed": True,
            "storage": {"outcome": "replayed", "reason": "idempotent_replay"},
            "indexing": {
                "state": index_status(old, request.app.state.settings),
                "error_code": old.embedding_error,
            },
        }
    if body.source_message_ids:
        if kind != "memories":
            raise HTTPException(422, "只有記憶可以引用會話訊息")
        if who[3]:
            identity(request, db, None, space_id, "sessions")
        found = set(
            db.scalars(
                select(NamespaceMessage.id)
                .join(NamespaceEntry, NamespaceEntry.id == NamespaceMessage.session_id)
                .where(
                    *conditions(who, space_id, "sessions"), NamespaceMessage.id.in_(body.source_message_ids)
                )
            )
        )
        if found != set(body.source_message_ids):
            raise HTTPException(404, "找不到可引用的來源訊息")
    count = db.scalar(
        select(func.count()).select_from(NamespaceEntry).where(*conditions(who, space_id, kind))
    )
    if count >= 1000:
        raise HTTPException(413, "此個人目錄上限為 1,000 筆")
    auto_store = False
    if who[3] and kind == "memories":
        g = db.get(NamespaceScopeGrant, (who[0], space_id, who[1], who[2].split(":", 1)[1], kind))
        auto_store = bool(g and g.can_write and g.auto_store)
    row = NamespaceEntry(
        tenant_id=who[0],
        space_id=space_id,
        person_id=who[1],
        kind=kind,
        title=body.title,
        content=body.content,
        created_by=who[2],
        external_id=body.external_id,
        input_hash=fingerprint,
        source_message_ids=body.source_message_ids,
        status="active" if kind == "sessions" or auto_store else "pending",
    )
    db.add(row)
    db.flush()
    revision(db, row, who[2])
    audit(db, request, who, kind + ".created", row.id)
    return {
        **payload(row, settings=request.app.state.settings),
        "storage": {
            "outcome": "created" if row.status == "active" else "review_required",
            "reason": "automatic_policy"
            if auto_store
            else "session_created"
            if kind == "sessions"
            else "manual_policy",
        },
    }


@router.get(HUMAN + "/entries/{entry_id}")
@router.get(MACHINE + "/entries/{entry_id}")
def read_entry(
    space_id: str,
    kind: Kind,
    entry_id: str,
    request: Request,
    tenant_id: str | None = None,
    db: Session = Depends(get_db, scope="function"),
):
    who = identity(request, db, tenant_id, space_id, kind)
    row = entry(db, who, space_id, kind, entry_id)
    result = payload(row, settings=request.app.state.settings)
    if not who[3]:
        result["revisions"] = [
            {
                "version": r.version,
                "title": r.title,
                "content": r.content,
                "status": r.status,
                "created_at": r.created_at,
            }
            for r in db.scalars(
                select(NamespaceRevision)
                .where(NamespaceRevision.entry_id == row.id)
                .order_by(NamespaceRevision.version.desc())
                .limit(50)
            )
        ]
    audit(db, request, who, kind + ".read", row.id)
    return {**result, "content_role": "untrusted_reference_data"}


@router.put(HUMAN + "/entries/{entry_id}")
def edit_entry(
    tenant_id: str,
    space_id: str,
    kind: Kind,
    entry_id: str,
    body: EditInput,
    request: Request,
    db: Session = Depends(get_db, scope="function"),
):
    who = identity(request, db, tenant_id, space_id, kind, write=True)
    row = entry(db, who, space_id, kind, entry_id)
    if row.version != body.version:
        raise HTTPException(409, "資料已被更新，請重新載入")
    if kind != "sessions" and not body.content.strip():
        raise HTTPException(422, "內容不能為空")
    if row.version >= 100:
        raise HTTPException(409, "版本已達上限，請建立新資料")
    row.title, row.content, row.status = body.title, body.content, body.status
    row.version += 1
    row.updated_at = time.time()
    revision(db, row, who[2])
    audit(db, request, who, kind + ".updated", row.id)
    return payload(row, settings=request.app.state.settings)


@router.post(HUMAN + "/entries/{entry_id}/delete")
def delete_entry(
    tenant_id: str,
    space_id: str,
    kind: Kind,
    entry_id: str,
    body: VersionInput,
    request: Request,
    db: Session = Depends(get_db, scope="function"),
):
    who = identity(request, db, tenant_id, space_id, kind, write=True)
    row = entry(db, who, space_id, kind, entry_id)
    if row.version != body.version:
        raise HTTPException(409, "資料已被更新，請重新載入")
    row.status, row.content, row.title, row.source_message_ids = "deleted", "", "已刪除", []
    reset_index(row)
    row.version += 1
    row.updated_at = time.time()
    db.execute(
        update(NamespaceRevision)
        .where(NamespaceRevision.entry_id == row.id)
        .values(content="", title="已刪除", status="deleted")
    )
    db.execute(update(NamespaceMessage).where(NamespaceMessage.session_id == row.id).values(content=""))
    audit(db, request, who, kind + ".deleted", row.id)
    return {"id": row.id, "status": row.status}


@router.post(HUMAN + "/entries/{entry_id}/reindex", status_code=202)
def reindex_entry(
    tenant_id: str,
    space_id: str,
    kind: Kind,
    entry_id: str,
    body: VersionInput,
    request: Request,
    db: Session = Depends(get_db, scope="function"),
):
    who = identity(request, db, tenant_id, space_id, kind, write=True)
    row = entry(db, who, space_id, kind, entry_id)
    if row.version != body.version:
        raise HTTPException(409, "資料已被更新，請重新載入")
    if row.status != "active" or kind == "sessions":
        raise HTTPException(409, "只有已啟用的記憶、Skill 或服務對象可建立索引")
    reset_index(row)
    audit(db, request, who, kind + ".reindex", row.id)
    return {"id": row.id, "indexing": {"state": "pending", "error_code": None}}


@router.get(HUMAN + "/entries/{entry_id}/messages")
@router.get(MACHINE + "/entries/{entry_id}/messages")
def messages(
    space_id: str,
    kind: Kind,
    entry_id: str,
    request: Request,
    tenant_id: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db, scope="function"),
):
    who = identity(request, db, tenant_id, space_id, kind)
    if kind != "sessions":
        raise HTTPException(404, "此目錄沒有訊息")
    row = entry(db, who, space_id, kind, entry_id)
    rows = list(
        db.scalars(
            select(NamespaceMessage)
            .where(NamespaceMessage.session_id == row.id)
            .order_by(NamespaceMessage.sequence)
            .offset(offset)
            .limit(limit + 1)
        )
    )
    return {
        "items": [
            {"id": m.id, "role": m.role, "content": m.content, "sequence": m.sequence} for m in rows[:limit]
        ],
        "has_more": len(rows) > limit,
        "content_role": "untrusted_reference_data",
    }


@router.post(HUMAN + "/entries/{entry_id}/messages", status_code=201)
@router.post(MACHINE + "/entries/{entry_id}/messages", status_code=201)
def append_message(
    space_id: str,
    kind: Kind,
    entry_id: str,
    body: MessageInput,
    request: Request,
    tenant_id: str | None = None,
    db: Session = Depends(get_db, scope="function"),
):
    who = identity(request, db, tenant_id, space_id, kind, write=True)
    if kind != "sessions":
        raise HTTPException(404, "此目錄沒有訊息")
    row = entry(db, who, space_id, kind, entry_id, writable=True)
    if row.status != "active":
        raise HTTPException(409, "會話已停用")
    old = db.scalar(
        select(NamespaceMessage).where(
            NamespaceMessage.session_id == row.id, NamespaceMessage.external_id == body.external_id
        )
    )
    if old:
        if old.role != body.role or old.content != body.content:
            raise HTTPException(409, "訊息識別碼已使用")
        return {"id": old.id, "sequence": old.sequence, "replayed": True}
    count = db.scalar(
        select(func.count()).select_from(NamespaceMessage).where(NamespaceMessage.session_id == row.id)
    )
    if count >= 1000:
        raise HTTPException(413, "每段會話上限為 1,000 則訊息")
    m = NamespaceMessage(
        session_id=row.id,
        external_id=body.external_id,
        role=body.role,
        content=body.content,
        sequence=count + 1,
    )
    db.add(m)
    row.updated_at = time.time()
    db.flush()
    audit(db, request, who, "sessions.message_added", row.id)
    return {"id": m.id, "sequence": m.sequence}


@router.get(HUMAN + "/entries/{entry_id}/sources")
def sources(
    tenant_id: str,
    space_id: str,
    kind: Kind,
    entry_id: str,
    request: Request,
    db: Session = Depends(get_db, scope="function"),
):
    who = identity(request, db, tenant_id, space_id, kind)
    row = entry(db, who, space_id, kind, entry_id)
    rows = db.execute(
        select(NamespaceMessage, NamespaceEntry.title)
        .join(NamespaceEntry, NamespaceEntry.id == NamespaceMessage.session_id)
        .where(*conditions(who, space_id, "sessions"), NamespaceMessage.id.in_(row.source_message_ids))
    ).all()
    return {
        "items": [
            {
                "id": m.id,
                "session_id": m.session_id,
                "session_title": title,
                "role": m.role,
                "content": m.content,
            }
            for m, title in rows
        ],
        "unavailable_count": len(set(row.source_message_ids)) - len(rows),
    }
