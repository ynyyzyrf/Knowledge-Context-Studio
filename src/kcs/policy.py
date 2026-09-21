"""Product authorization. Engine identity never comes from client assertions."""

import time
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    Agent,
    AgentCredential,
    AgentSpaceGrant,
    CredentialSubject,
    KnowledgeSpace,
    PersonSpaceGrant,
    Subject,
    Tenant,
)
from .security import digest, get_db, tenant_membership


@dataclass
class AgentAuth:
    tenant_id: str
    agent_id: str
    credential_id: str


def agent_auth(request: Request, db: Session = Depends(get_db)):
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token or len(token) > 256:
        raise HTTPException(401, "Agent 憑證無效")
    credential = db.scalar(select(AgentCredential).where(AgentCredential.token_hash == digest(token)))
    if not credential or credential.revoked_at is not None or credential.expires_at <= time.time():
        raise HTTPException(401, "Agent 憑證無效")
    agent = db.get(Agent, credential.agent_id)
    tenant = db.get(Tenant, credential.tenant_id)
    if not agent or not agent.active or not tenant or not tenant.active:
        raise HTTPException(401, "Agent 憑證無效")
    return AgentAuth(tenant.id, agent.id, credential.id)


def locked_agent_auth(request: Request, auth: AgentAuth = Depends(agent_auth), db: Session = Depends(get_db)):
    # Policy mutations use the same lock. Recheck credentials after acquiring it.
    db.scalar(select(Tenant).where(Tenant.id == auth.tenant_id).with_for_update())
    db.expire_all()
    return agent_auth(request, db)


def scoped_object(db, model, tenant_id, object_id):
    obj = db.scalar(select(model).where(model.tenant_id == tenant_id, model.id == object_id))
    if not obj:
        raise HTTPException(404, "找不到物件")
    return obj


def allowed_subject_ids(db, auth):
    return list(
        db.scalars(
            select(Subject.id)
            .join(
                CredentialSubject,
                (CredentialSubject.subject_id == Subject.id)
                & (CredentialSubject.tenant_id == Subject.tenant_id)
                & (CredentialSubject.agent_id == Subject.agent_id),
            )
            .where(
                CredentialSubject.credential_id == auth.credential_id,
                Subject.tenant_id == auth.tenant_id,
                Subject.agent_id == auth.agent_id,
                Subject.active.is_(True),
            )
            .order_by(Subject.id)
        )
    )


def allowed_space_ids(db, auth):
    return list(
        db.scalars(
            select(KnowledgeSpace.id)
            .join(
                AgentSpaceGrant,
                (AgentSpaceGrant.space_id == KnowledgeSpace.id)
                & (AgentSpaceGrant.tenant_id == KnowledgeSpace.tenant_id),
            )
            .where(
                AgentSpaceGrant.tenant_id == auth.tenant_id,
                AgentSpaceGrant.agent_id == auth.agent_id,
                AgentSpaceGrant.active.is_(True),
                KnowledgeSpace.active.is_(True),
            )
            .order_by(KnowledgeSpace.id)
        )
    )


def person_space(db, tenant_id, space_id, auth, *, write=False):
    member = tenant_membership(db, tenant_id, auth)
    space = scoped_object(db, KnowledgeSpace, tenant_id, space_id)
    if not space.active:
        raise HTTPException(404, "找不到空間")
    if member.role == "tenant_admin":
        return space
    grant = db.get(PersonSpaceGrant, (tenant_id, space_id, auth.person.id))
    if not grant or not grant.active:
        raise HTTPException(404, "找不到空間")
    if write and (grant.level != "editor" or member.role != "editor"):
        raise HTTPException(403, "需要空間編輯權限")
    return space
