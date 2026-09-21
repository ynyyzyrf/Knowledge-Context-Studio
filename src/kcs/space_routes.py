from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .agent_routes import ActiveInput, NamedInput, record
from .models import Agent, AgentSpaceGrant, KnowledgeSpace, Membership, PersonSpaceGrant
from .policy import person_space, scoped_object
from .security import PersonAuth, get_db, person_auth, tenant_membership

router = APIRouter(prefix="/v1/tenants/{tenant_id}/spaces")


class PersonGrantInput(ActiveInput):
    level: Literal["editor", "viewer"]


def public_space(space):
    return {"id": space.id, "name": space.name, "active": space.active, "sync_state": space.sync_state}


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
    return {"items": [public_space(row) for row in db.scalars(query.order_by(KnowledgeSpace.id))]}


@router.post("", status_code=201)
def create_space(
    tenant_id: str,
    body: NamedInput,
    request: Request,
    auth: PersonAuth = Depends(person_auth),
    db: Session = Depends(get_db),
):
    tenant_membership(db, tenant_id, auth, admin=True)
    space = KnowledgeSpace(tenant_id=tenant_id, name=body.name.strip())
    db.add(space)
    db.flush()
    record(db, request, auth, tenant_id, "space.created", space.id)
    return public_space(space)


@router.get("/{space_id}")
def get_space(
    tenant_id: str, space_id: str, auth: PersonAuth = Depends(person_auth), db: Session = Depends(get_db)
):
    return public_space(person_space(db, tenant_id, space_id, auth))


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
