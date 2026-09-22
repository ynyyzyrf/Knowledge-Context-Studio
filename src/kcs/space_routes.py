import re
from collections import Counter
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .agent_routes import ActiveInput, NamedInput, record
from .auth_routes import StrictModel
from .document_routes import lock_permission
from .engine import EngineError, OpenViking, document_uri, private_space_uri, space_uri
from .models import (
    Agent,
    AgentSpaceGrant,
    Document,
    DocumentChunk,
    KnowledgeSpace,
    Membership,
    PersonSpaceGrant,
    ResourceFolder,
)
from .policy import person_space, scoped_object
from .resource_folders import visible_documents
from .security import PersonAuth, get_db, person_auth, tenant_membership

router = APIRouter(prefix="/v1/tenants/{tenant_id}/spaces")


class PersonGrantInput(ActiveInput):
    level: Literal["editor", "viewer"]


class SpaceInput(NamedInput):
    description: str = Field(default="", max_length=500)


class SpaceUpdateInput(StrictModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=500)


class SpaceSearchInput(StrictModel):
    query: str = Field(min_length=1, max_length=2000, pattern=r"\S")
    limit: int = Field(default=8, ge=1, le=20)


def public_space(space, stats=None):
    data = {
        "id": space.id,
        "name": space.name,
        "description": space.description or "",
        "active": space.active,
        "sync_state": space.sync_state,
    }
    if stats:
        data.update(stats)
    return data


def space_stats(db: Session, tenant_id: str, space_ids: list[str], person_id: str):
    """Count only documents visible to the authenticated person."""
    if not space_ids:
        return {}
    docs = {
        space: (count, latest)
        for space, count, latest in db.execute(
            select(Document.space_id, func.count(Document.id), func.max(Document.created_at))
            .where(
                Document.tenant_id == tenant_id,
                Document.space_id.in_(space_ids),
                visible_documents(person_id),
                Document.deleted.is_(False),
            )
            .group_by(Document.space_id)
        ).all()
    }
    grants = db.execute(
        select(AgentSpaceGrant.space_id, AgentSpaceGrant.agent_id).where(
            AgentSpaceGrant.tenant_id == tenant_id,
            AgentSpaceGrant.space_id.in_(space_ids),
            AgentSpaceGrant.active.is_(True),
        )
    ).all()
    agent_counts = Counter(space for space, _ in grants)
    stats = {}
    for space in space_ids:
        count, latest = docs.get(space, (0, None))
        stats[space] = {
            "document_count": count,
            "agent_count": agent_counts.get(space, 0),
            "memory_count": 0,
            "last_activity_at": latest,
        }
    return stats


@router.get("")
def spaces(tenant_id: str, auth: PersonAuth = Depends(person_auth), db: Session = Depends(get_db)):
    member = tenant_membership(db, tenant_id, auth)
    query = select(KnowledgeSpace).where(
        KnowledgeSpace.tenant_id == tenant_id, KnowledgeSpace.active.is_(True)
    )
    if member.role != "tenant_admin":
        query = query.join(
            PersonSpaceGrant,
            (PersonSpaceGrant.tenant_id == KnowledgeSpace.tenant_id)
            & (PersonSpaceGrant.space_id == KnowledgeSpace.id),
        ).where(PersonSpaceGrant.person_id == auth.person.id, PersonSpaceGrant.active.is_(True))
    rows = list(db.scalars(query.order_by(KnowledgeSpace.id)))
    stats = space_stats(db, tenant_id, [space.id for space in rows], auth.person.id)
    return {"items": [public_space(space, stats.get(space.id)) for space in rows]}


@router.post("", status_code=201)
def create_space(
    tenant_id: str,
    body: SpaceInput,
    request: Request,
    auth: PersonAuth = Depends(person_auth),
    db: Session = Depends(get_db),
):
    tenant_membership(db, tenant_id, auth, admin=True)
    space = KnowledgeSpace(
        tenant_id=tenant_id, name=body.name.strip(), description=(body.description or "").strip()
    )
    db.add(space)
    db.flush()
    record(db, request, auth, tenant_id, "space.created", space.id)
    return public_space(space)


@router.patch("/{space_id}")
def update_space(
    tenant_id: str,
    space_id: str,
    body: SpaceUpdateInput,
    request: Request,
    auth: PersonAuth = Depends(person_auth),
    db: Session = Depends(get_db),
):
    tenant_membership(db, tenant_id, auth, admin=True)
    space = scoped_object(db, KnowledgeSpace, tenant_id, space_id)
    space.name = body.name.strip()
    space.description = (body.description or "").strip()
    record(db, request, auth, tenant_id, "space.updated", space_id)
    return public_space(space)


@router.get("/{space_id}")
def get_space(
    tenant_id: str, space_id: str, auth: PersonAuth = Depends(person_auth), db: Session = Depends(get_db)
):
    space = person_space(db, tenant_id, space_id, auth)
    return public_space(space, space_stats(db, tenant_id, [space.id], auth.person.id).get(space.id))


@router.get("/{space_id}/context")
def space_context(
    tenant_id: str, space_id: str, auth: PersonAuth = Depends(person_auth), db: Session = Depends(get_db)
):
    """Space-local private and shared resources; default resolves from authentication."""
    space = person_space(db, tenant_id, space_id, auth)
    documents = db.scalars(
        select(Document)
        .where(
            Document.tenant_id == tenant_id,
            Document.space_id == space_id,
            Document.deleted.is_(False),
            visible_documents(auth.person.id),
        )
        .order_by(Document.created_at.desc(), Document.id)
    ).all()
    folders = db.scalars(
        select(ResourceFolder)
        .where(
            ResourceFolder.tenant_id == tenant_id,
            ResourceFolder.space_id == space_id,
            ResourceFolder.owner_key.in_(["", auth.person.id]),
        )
        .order_by(ResourceFolder.path)
    ).all()
    groups = {}
    for folder in folders:
        scope = "private" if folder.owner_key else "shared"
        groups[(scope, folder.path)] = {
            "key": folder.path,
            "scope": scope,
            "document_count": 0,
            "chunk_count": 0,
            "recent": [],
        }
    for d in documents:
        scope = "private" if d.owner_person_id else "shared"
        bucket = groups.setdefault(
            (scope, d.resource_path),
            {"key": d.resource_path, "scope": scope, "document_count": 0, "chunk_count": 0, "recent": []},
        )
        bucket["document_count"] += 1
        bucket["chunk_count"] += d.chunk_count
        if len(bucket["recent"]) < 5:
            bucket["recent"].append(
                {
                    "id": d.id,
                    "filename": d.filename,
                    "resource_path": d.resource_path,
                    "scope": scope,
                    "created_at": d.created_at,
                }
            )
    agents = db.scalars(
        select(Agent)
        .join(
            AgentSpaceGrant,
            (AgentSpaceGrant.agent_id == Agent.id) & (AgentSpaceGrant.tenant_id == Agent.tenant_id),
        )
        .where(
            Agent.tenant_id == tenant_id,
            AgentSpaceGrant.space_id == space_id,
            AgentSpaceGrant.active.is_(True),
        )
    ).all()
    return {
        "space": public_space(space),
        "categories": list(groups.values()),
        "subjects": [],
        "namespace": {
            "alias": "default",
            "identity": "authenticated_user",
            "directories": [
                {
                    "name": name,
                    "state": "available" if name == "resources" else "not_connected",
                    "searchable": name == "resources",
                }
                for name in ["memories", "peers", "privacy", "resources", "sessions", "skills"]
            ],
        },
        "agents": [{"agent_id": a.id, "agent_name": a.name, "agent_active": a.active} for a in agents],
    }


@router.post("/{space_id}/search")
def search_space(
    tenant_id: str,
    space_id: str,
    body: SpaceSearchInput,
    request: Request,
    auth: PersonAuth = Depends(person_auth),
    db: Session = Depends(get_db),
):
    """Semantic search inside a single space. Isolation is preserved by
    querying only this space's engine root and verifying every hit against
    the current database content."""
    space = person_space(db, tenant_id, space_id, auth)
    roots = [space_uri(tenant_id, space.id), private_space_uri(tenant_id, space.id, auth.person.id)]
    factory = getattr(request.app.state, "context_engine_factory", None)
    try:
        with factory() if factory else OpenViking(request.app.state.settings) as engine:
            hits = engine.find(roots, body.query, min(100, body.limit * 5))
    except EngineError as error:
        raise HTTPException(503, str(error)) from None
    auth = lock_permission(db, request, tenant_id, space_id, write=False)
    document_ids: set[str] = set()
    for uri, _ in hits:
        for root in roots:
            prefix = root + "/"
            if isinstance(uri, str) and uri.startswith(prefix):
                parts = uri[len(prefix) :].split("/")
                if len(parts) == 2 and re.fullmatch(r"v1-c(\d+)\.md", parts[1]):
                    document_ids.add(parts[0])
    rows = db.execute(
        select(Document, DocumentChunk)
        .join(DocumentChunk, DocumentChunk.document_id == Document.id)
        .where(
            Document.tenant_id == tenant_id,
            Document.space_id == space_id,
            Document.id.in_(document_ids),
            visible_documents(auth.person.id),
            Document.deleted.is_(False),
            Document.state == "succeeded",
        )
    ).all()
    verified = {document_uri(document, chunk.number): (document, chunk) for document, chunk in rows}
    items = []
    for uri, score in hits:
        if len(items) >= body.limit:
            break
        if uri in verified:
            document, chunk = verified[uri]
            items.append(
                {
                    "document_id": document.id,
                    "filename": document.filename,
                    "chunk": chunk.number,
                    "page": chunk.page,
                    "content": chunk.content,
                    "score": score,
                }
            )
    record(db, request, auth, tenant_id, "space.search", space_id, {"count": len(items)})
    return {"items": items, "request_id": request.state.request_id}


@router.put("/{space_id}/agents/{agent_id}")
def grant_agent(
    tenant_id: str,
    space_id: str,
    agent_id: str,
    body: ActiveInput,
    request: Request,
    auth: PersonAuth = Depends(person_auth),
    db: Session = Depends(get_db),
):
    tenant_membership(db, tenant_id, auth, admin=True)
    scoped_object(db, KnowledgeSpace, tenant_id, space_id)
    scoped_object(db, Agent, tenant_id, agent_id)
    grant = db.get(AgentSpaceGrant, (tenant_id, space_id, agent_id))
    if not grant:
        grant = AgentSpaceGrant(tenant_id=tenant_id, space_id=space_id, agent_id=agent_id)
        db.add(grant)
    grant.active = body.active
    record(
        db,
        request,
        auth,
        tenant_id,
        "space.agent_grant",
        space_id,
        {"agent_id": agent_id, "active": body.active},
    )
    return {"agent_id": agent_id, "active": body.active}


@router.put("/{space_id}/people/{person_id}")
def grant_person(
    tenant_id: str,
    space_id: str,
    person_id: str,
    body: PersonGrantInput,
    request: Request,
    auth: PersonAuth = Depends(person_auth),
    db: Session = Depends(get_db),
):
    tenant_membership(db, tenant_id, auth, admin=True)
    scoped_object(db, KnowledgeSpace, tenant_id, space_id)
    member = db.get(Membership, (tenant_id, person_id))
    if not member or not member.active:
        raise HTTPException(404, "找不到成員")
    grant = db.get(PersonSpaceGrant, (tenant_id, space_id, person_id))
    if not grant:
        grant = PersonSpaceGrant(
            tenant_id=tenant_id, space_id=space_id, person_id=person_id, level=body.level
        )
        db.add(grant)
    grant.active, grant.level = body.active, body.level
    record(
        db,
        request,
        auth,
        tenant_id,
        "space.person_grant",
        space_id,
        {"person_id": person_id, "active": body.active, "level": body.level},
    )
    return {"person_id": person_id, "active": body.active, "level": body.level}


@router.get("/{space_id}/grants")
def grants(
    tenant_id: str, space_id: str, auth: PersonAuth = Depends(person_auth), db: Session = Depends(get_db)
):
    tenant_membership(db, tenant_id, auth, admin=True)
    scoped_object(db, KnowledgeSpace, tenant_id, space_id)
    people = db.scalars(
        select(PersonSpaceGrant).where(
            PersonSpaceGrant.tenant_id == tenant_id, PersonSpaceGrant.space_id == space_id
        )
    )
    agents = db.scalars(
        select(AgentSpaceGrant).where(
            AgentSpaceGrant.tenant_id == tenant_id, AgentSpaceGrant.space_id == space_id
        )
    )
    return {
        "people": [{"person_id": x.person_id, "level": x.level, "active": x.active} for x in people],
        "agents": [{"agent_id": x.agent_id, "active": x.active} for x in agents],
    }
