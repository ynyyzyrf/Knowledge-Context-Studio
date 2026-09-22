import re
from collections import Counter
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .agent_routes import ActiveInput, NamedInput, record
from .auth_routes import StrictModel
from .engine import EngineError, OpenViking, document_uri, space_uri
from .models import (
    Agent,
    AgentSpaceGrant,
    Conversation,
    Document,
    DocumentChunk,
    KnowledgeSpace,
    Membership,
    MemoryRecord,
    PersonSpaceGrant,
    Subject,
)
from .policy import person_space, scoped_object
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


def space_stats(db: Session, tenant_id: str, space_ids: list[str]):
    """Real aggregate counts for the space cards. Memory is owned by each
    agent's subjects, so it is attributed to every space that agent can read."""
    if not space_ids:
        return {}
    docs = {
        space: (count, latest)
        for space, count, latest in db.execute(
            select(Document.space_id, func.count(Document.id), func.max(Document.created_at))
            .where(
                Document.tenant_id == tenant_id,
                Document.space_id.in_(space_ids),
                Document.deleted.is_(False),
            )
            .group_by(Document.space_id)
        ).all()
    }
    grants = db.execute(
        select(AgentSpaceGrant.space_id, AgentSpaceGrant.agent_id)
        .where(
            AgentSpaceGrant.tenant_id == tenant_id,
            AgentSpaceGrant.space_id.in_(space_ids),
            AgentSpaceGrant.active.is_(True),
        )
    ).all()
    agent_counts = Counter(space for space, _ in grants)
    agent_ids = list({agent for _, agent in grants})
    memory_by_agent = {}
    if agent_ids:
        memory_by_agent = dict(
            db.execute(
                select(MemoryRecord.agent_id, func.count(MemoryRecord.id))
                .where(
                    MemoryRecord.tenant_id == tenant_id,
                    MemoryRecord.agent_id.in_(agent_ids),
                    MemoryRecord.status == "active",
                )
                .group_by(MemoryRecord.agent_id)
            ).all()
        )
    stats = {}
    for space in space_ids:
        count, latest = docs.get(space, (0, None))
        stats[space] = {
            "document_count": count,
            "agent_count": agent_counts.get(space, 0),
            "memory_count": sum(
                memory_by_agent.get(agent, 0)
                for granted_space, agent in grants
                if granted_space == space
            ),
            "last_activity_at": latest,
        }
    return stats


def category_of(filename: str) -> str:
    # Category is derived from the path prefix of the imported file, if any.
    return filename.split("/")[0] if "/" in filename else "general"


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
    stats = space_stats(db, tenant_id, [space.id for space in rows])
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
    return public_space(space, space_stats(db, tenant_id, [space.id]).get(space.id))


@router.get("/{space_id}/context")
def space_context(
    tenant_id: str, space_id: str, auth: PersonAuth = Depends(person_auth), db: Session = Depends(get_db)
):
    """Context tree data for the space studio: resources by category and the
    subjects of every agent granted to this space."""
    space = person_space(db, tenant_id, space_id, auth)
    documents = db.execute(
        select(Document)
        .where(
            Document.tenant_id == tenant_id,
            Document.space_id == space_id,
            Document.deleted.is_(False),
        )
        .order_by(Document.created_at.desc())
    ).scalars().all()
    categories: dict[str, dict] = {}
    for document in documents:
        bucket = categories.setdefault(
            category_of(document.filename),
            {"key": category_of(document.filename), "document_count": 0, "chunk_count": 0, "recent": []},
        )
        bucket["document_count"] += 1
        bucket["chunk_count"] += document.chunk_count
        if len(bucket["recent"]) < 5:
            bucket["recent"].append({"id": document.id, "filename": document.filename, "created_at": document.created_at})
    grants = db.execute(
        select(AgentSpaceGrant, Agent)
        .join(Agent, (Agent.id == AgentSpaceGrant.agent_id) & (Agent.tenant_id == AgentSpaceGrant.tenant_id))
        .where(
            AgentSpaceGrant.tenant_id == tenant_id,
            AgentSpaceGrant.space_id == space_id,
            AgentSpaceGrant.active.is_(True),
        )
    ).all()
    agent_rows = [
        {"agent_id": grant.agent_id, "agent_name": agent.name, "agent_active": agent.active}
        for grant, agent in grants
    ]
    subjects: list[dict] = []
    for grant, agent in grants:
        rows = db.execute(
            select(Subject)
            .where(
                Subject.tenant_id == tenant_id,
                Subject.agent_id == grant.agent_id,
            )
            .order_by(Subject.id)
        ).scalars().all()
        for subject in rows:
            memory_count = db.scalar(
                select(func.count(MemoryRecord.id)).where(
                    MemoryRecord.tenant_id == tenant_id,
                    MemoryRecord.agent_id == grant.agent_id,
                    MemoryRecord.subject_id == subject.id,
                    MemoryRecord.status == "active",
                )
            )
            session_count = db.scalar(
                select(func.count(Conversation.id)).where(
                    Conversation.tenant_id == tenant_id,
                    Conversation.agent_id == grant.agent_id,
                    Conversation.subject_id == subject.id,
                )
            )
            subjects.append(
                {
                    "id": subject.id,
                    "name": subject.name,
                    "active": subject.active,
                    "agent_id": agent.id,
                    "agent_name": agent.name,
                    "memory_count": memory_count or 0,
                    "session_count": session_count or 0,
                }
            )
    return {
        "space": public_space(space),
        "agents": agent_rows,
        "categories": list(categories.values()),
        "subjects": subjects,
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
    root = space_uri(tenant_id, space.id)
    factory = getattr(request.app.state, "context_engine_factory", None)
    try:
        with factory() if factory else OpenViking(request.app.state.settings) as engine:
            hits = engine.find(root, body.query, min(100, body.limit * 5))
    except EngineError as error:
        raise HTTPException(503, str(error)) from None
    document_ids: set[str] = set()
    for uri, _ in hits:
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
