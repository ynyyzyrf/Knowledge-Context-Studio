"""Authenticated user's space-local namespace; default is never a Subject."""

from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .agent_routes import ActiveInput, record
from .auth_routes import StrictModel
from .document_routes import lock_permission
from .engine import EngineError, OpenViking, document_uri, private_space_uri
from .models import (
    Agent,
    AgentCredential,
    AgentSpaceGrant,
    AuditEvent,
    Document,
    DocumentChunk,
    NamespaceAgentGrant,
    Person,
)
from .policy import agent_auth, allowed_space_ids, locked_agent_auth, person_space
from .security import PersonAuth, get_db, person_auth

router = APIRouter(prefix="/v1")


def private_owner(db, auth, space_id):
    credential = db.get(AgentCredential, auth.credential_id)
    person = db.get(Person, credential.namespace_person_id) if credential.namespace_person_id else None
    if not person or not person.active or space_id not in allowed_space_ids(db, auth):
        raise HTTPException(404, "找不到授權私人 namespace")
    person_space(db, auth.tenant_id, space_id, SimpleNamespace(person=person))
    grant = db.get(NamespaceAgentGrant, (auth.tenant_id, space_id, person.id, auth.agent_id))
    if not grant or not grant.active:
        raise HTTPException(404, "找不到授權私人 namespace")
    return person.id


@router.get("/tenants/{tenant_id}/spaces/{space_id}/user/default/agent-access")
def access(
    tenant_id: str, space_id: str, auth: PersonAuth = Depends(person_auth), db: Session = Depends(get_db)
):
    person_space(db, tenant_id, space_id, auth)
    rows = (
        db.execute(
            select(Agent)
            .join(
                AgentSpaceGrant,
                (AgentSpaceGrant.agent_id == Agent.id) & (AgentSpaceGrant.tenant_id == Agent.tenant_id),
            )
            .where(
                Agent.tenant_id == tenant_id,
                Agent.active.is_(True),
                AgentSpaceGrant.space_id == space_id,
                AgentSpaceGrant.active.is_(True),
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "agent_id": a.id,
                "name": a.name,
                "active": bool(
                    (g := db.get(NamespaceAgentGrant, (tenant_id, space_id, auth.person.id, a.id)))
                    and g.active
                ),
            }
            for a in rows
        ]
    }


@router.put("/tenants/{tenant_id}/spaces/{space_id}/user/default/agent-access/{agent_id}")
def grant(
    tenant_id: str,
    space_id: str,
    agent_id: str,
    body: ActiveInput,
    request: Request,
    db: Session = Depends(get_db),
):
    auth = lock_permission(db, request, tenant_id, space_id, write=False)
    agent = db.get(Agent, agent_id)
    space_grant = db.get(AgentSpaceGrant, (tenant_id, space_id, agent_id))
    if (
        not agent
        or agent.tenant_id != tenant_id
        or not space_grant
        or (body.active and (not agent.active or not space_grant.active))
    ):
        raise HTTPException(404, "找不到空間內的 Agent")
    row = db.get(NamespaceAgentGrant, (tenant_id, space_id, auth.person.id, agent_id))
    if not row:
        row = NamespaceAgentGrant(
            tenant_id=tenant_id, space_id=space_id, person_id=auth.person.id, agent_id=agent_id
        )
        db.add(row)
    row.active = body.active
    record(
        db,
        request,
        auth,
        tenant_id,
        "namespace.resources.grant",
        space_id,
        {"agent_id": agent_id, "active": body.active, "scope": "user/default/resources:read"},
    )
    return {"agent_id": agent_id, "active": row.active}


class QueryInput(StrictModel):
    query: str = Field(min_length=1, max_length=2000, pattern=r"\S")
    limit: int = Field(default=8, ge=1, le=20)
    max_chars: int = Field(default=12000, ge=1000, le=40000)


@router.post("/spaces/{space_id}/user/default/resources/search")
def search_private(space_id: str, body: QueryInput, request: Request):
    database = request.app.state.database
    with database.sessions.begin() as db:
        auth = agent_auth(request, db)
        owner = private_owner(db, auth, space_id)
        root = private_space_uri(auth.tenant_id, space_id, owner)
    factory = getattr(request.app.state, "context_engine_factory", None)
    try:
        with factory() if factory else OpenViking(request.app.state.settings) as engine:
            hits = engine.find(root, body.query, min(100, body.limit * 5))
    except EngineError as error:
        raise HTTPException(503, str(error)) from None
    with database.sessions.begin() as db:
        auth = locked_agent_auth(request, auth, db)
        if private_owner(db, auth, space_id) != owner:
            raise HTTPException(404, "找不到授權私人 namespace")
        identities = {
            uri[len(root) + 1 :].split("/")[0]
            for uri, _ in hits
            if isinstance(uri, str) and uri.startswith(root + "/")
        }
        rows = db.execute(
            select(Document, DocumentChunk)
            .join(DocumentChunk, DocumentChunk.document_id == Document.id)
            .where(
                Document.tenant_id == auth.tenant_id,
                Document.space_id == space_id,
                Document.owner_person_id == owner,
                Document.id.in_(identities),
                Document.deleted.is_(False),
                Document.state == "succeeded",
            )
        ).all()
        verified = {document_uri(d, c.number): (d, c) for d, c in rows}
        items, used, seen = [], 0, set()
        for uri, score in hits:
            if uri not in verified or uri in seen:
                continue
            seen.add(uri)
            d, c = verified[uri]
            if used + len(c.content or "") > body.max_chars:
                continue
            items.append(
                {
                    "document_id": d.id,
                    "filename": d.filename,
                    "resource_path": d.resource_path,
                    "chunk": c.number,
                    "content": c.content,
                    "score": score,
                }
            )
            used += len(c.content or "")
            if len(items) >= body.limit:
                break
        db.add(
            AuditEvent(
                tenant_id=auth.tenant_id,
                actor_id=auth.agent_id,
                action="namespace.resources.read",
                target_id=space_id,
                request_id=request.state.request_id,
                details={"owner_person_id": owner, "count": len(items)},
            )
        )
        return {
            "namespace": "user/default/resources",
            "space_id": space_id,
            "items": items,
            "content_role": "untrusted_reference_data",
        }
