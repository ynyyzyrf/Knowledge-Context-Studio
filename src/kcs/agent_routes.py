import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth_routes import StrictModel
from .models import Agent, AgentCredential, AuditEvent, CredentialSubject, Subject, Tenant
from .policy import AgentAuth, agent_auth, allowed_space_ids, allowed_subject_ids, scoped_object
from .security import PersonAuth, digest, get_db, person_auth, tenant_membership

router = APIRouter(prefix="/v1")


class NamedInput(StrictModel):
    name: str = Field(min_length=1, max_length=160, pattern=r"\S")


class ActiveInput(StrictModel):
    active: bool


class CredentialInput(StrictModel):
    subject_ids: list[str] = Field(min_length=1, max_length=100)
    expires_in_days: int = Field(default=30, ge=1, le=365)


def public_entity(obj):
    return {"id": obj.id, "name": obj.name, "active": obj.active}


def record(db, request, auth, tenant_id, action, target_id, details=None):
    tenant = db.get(Tenant, tenant_id)
    tenant.policy_version += 1
    db.add(
        AuditEvent(
            tenant_id=tenant_id,
            actor_id=auth.person.id,
            action=action,
            target_id=target_id,
            request_id=request.state.request_id,
            details=details or {},
        )
    )


def subject_for_agent(db, tenant_id, agent_id, subject_id):
    subject = scoped_object(db, Subject, tenant_id, subject_id)
    if subject.agent_id != agent_id:
        raise HTTPException(404, "找不到服務對象")
    return subject


def issue_credential(db, tenant_id, agent_id, subject_ids, expires_at):
    token = "kcs_" + secrets.token_urlsafe(32)
    credential = AgentCredential(
        tenant_id=tenant_id, agent_id=agent_id, token_hash=digest(token), expires_at=expires_at
    )
    db.add(credential)
    db.flush()
    for subject_id in sorted(set(subject_ids)):
        db.add(
            CredentialSubject(
                tenant_id=tenant_id, agent_id=agent_id, credential_id=credential.id, subject_id=subject_id
            )
        )
    return credential, token


@router.get("/agent/me")
def machine_identity(auth: AgentAuth = Depends(agent_auth), db: Session = Depends(get_db)):
    return {
        "tenant_id": auth.tenant_id,
        "agent_id": auth.agent_id,
        "credential_id": auth.credential_id,
        "subject_ids": allowed_subject_ids(db, auth),
        "space_ids": allowed_space_ids(db, auth),
    }


@router.get("/tenants/{tenant_id}/agents")
def agents(tenant_id: str, auth: PersonAuth = Depends(person_auth), db: Session = Depends(get_db)):
    tenant_membership(db, tenant_id, auth, admin=True)
    rows = db.scalars(select(Agent).where(Agent.tenant_id == tenant_id).order_by(Agent.id))
    return {"items": [public_entity(row) for row in rows]}


@router.post("/tenants/{tenant_id}/agents", status_code=201)
def create_agent(
    tenant_id: str,
    body: NamedInput,
    request: Request,
    auth: PersonAuth = Depends(person_auth),
    db: Session = Depends(get_db),
):
    tenant_membership(db, tenant_id, auth, admin=True)
    agent = Agent(tenant_id=tenant_id, name=body.name.strip())
    db.add(agent)
    db.flush()
    record(db, request, auth, tenant_id, "agent.created", agent.id)
    return public_entity(agent)


@router.patch("/tenants/{tenant_id}/agents/{agent_id}")
def update_agent(
    tenant_id: str,
    agent_id: str,
    body: ActiveInput,
    request: Request,
    auth: PersonAuth = Depends(person_auth),
    db: Session = Depends(get_db),
):
    tenant_membership(db, tenant_id, auth, admin=True)
    agent = scoped_object(db, Agent, tenant_id, agent_id)
    agent.active = body.active
    record(db, request, auth, tenant_id, "agent.enabled" if body.active else "agent.disabled", agent.id)
    return public_entity(agent)


@router.get("/tenants/{tenant_id}/agents/{agent_id}/subjects")
def subjects(
    tenant_id: str, agent_id: str, auth: PersonAuth = Depends(person_auth), db: Session = Depends(get_db)
):
    tenant_membership(db, tenant_id, auth, admin=True)
    scoped_object(db, Agent, tenant_id, agent_id)
    rows = db.scalars(
        select(Subject)
        .where(Subject.tenant_id == tenant_id, Subject.agent_id == agent_id)
        .order_by(Subject.id)
    )
    return {"items": [public_entity(row) for row in rows]}


@router.post("/tenants/{tenant_id}/agents/{agent_id}/subjects", status_code=201)
def create_subject(
    tenant_id: str,
    agent_id: str,
    body: NamedInput,
    request: Request,
    auth: PersonAuth = Depends(person_auth),
    db: Session = Depends(get_db),
):
    tenant_membership(db, tenant_id, auth, admin=True)
    scoped_object(db, Agent, tenant_id, agent_id)
    subject = Subject(tenant_id=tenant_id, agent_id=agent_id, name=body.name.strip())
    db.add(subject)
    db.flush()
    record(db, request, auth, tenant_id, "subject.created", subject.id)
    return public_entity(subject)


@router.patch("/tenants/{tenant_id}/agents/{agent_id}/subjects/{subject_id}")
def update_subject(
    tenant_id: str,
    agent_id: str,
    subject_id: str,
    body: ActiveInput,
    request: Request,
    auth: PersonAuth = Depends(person_auth),
    db: Session = Depends(get_db),
):
    tenant_membership(db, tenant_id, auth, admin=True)
    subject = subject_for_agent(db, tenant_id, agent_id, subject_id)
    subject.active = body.active
    record(db, request, auth, tenant_id, "subject.enabled" if body.active else "subject.disabled", subject.id)
    return public_entity(subject)


@router.get("/tenants/{tenant_id}/agents/{agent_id}/credentials")
def credentials(
    tenant_id: str, agent_id: str, auth: PersonAuth = Depends(person_auth), db: Session = Depends(get_db)
):
    tenant_membership(db, tenant_id, auth, admin=True)
    scoped_object(db, Agent, tenant_id, agent_id)
    rows = db.scalars(
        select(AgentCredential)
        .where(AgentCredential.tenant_id == tenant_id, AgentCredential.agent_id == agent_id)
        .order_by(AgentCredential.created_at.desc())
    )
    return {
        "items": [
            {
                "id": row.id,
                "created_at": row.created_at,
                "expires_at": row.expires_at,
                "revoked_at": row.revoked_at,
            }
            for row in rows
        ]
    }


@router.post("/tenants/{tenant_id}/agents/{agent_id}/credentials", status_code=201)
def create_credential(
    tenant_id: str,
    agent_id: str,
    body: CredentialInput,
    request: Request,
    auth: PersonAuth = Depends(person_auth),
    db: Session = Depends(get_db),
):
    tenant_membership(db, tenant_id, auth, admin=True)
    agent = scoped_object(db, Agent, tenant_id, agent_id)
    if not agent.active:
        raise HTTPException(409, "請先啟用 Agent")
    for subject_id in body.subject_ids:
        if not subject_for_agent(db, tenant_id, agent_id, subject_id).active:
            raise HTTPException(404, "找不到服務對象")
    credential, token = issue_credential(
        db, tenant_id, agent_id, body.subject_ids, time.time() + body.expires_in_days * 86400
    )
    record(db, request, auth, tenant_id, "credential.created", credential.id)
    return {"id": credential.id, "token": token, "expires_at": credential.expires_at}


def owned_credential(db, tenant_id, agent_id, credential_id):
    row = scoped_object(db, AgentCredential, tenant_id, credential_id)
    if row.agent_id != agent_id:
        raise HTTPException(404, "找不到憑證")
    return row


@router.post("/tenants/{tenant_id}/agents/{agent_id}/credentials/{credential_id}/rotate", status_code=201)
def rotate(
    tenant_id: str,
    agent_id: str,
    credential_id: str,
    body: StrictModel,
    request: Request,
    auth: PersonAuth = Depends(person_auth),
    db: Session = Depends(get_db),
):
    tenant_membership(db, tenant_id, auth, admin=True)
    agent = scoped_object(db, Agent, tenant_id, agent_id)
    old = owned_credential(db, tenant_id, agent_id, credential_id)
    if not agent.active or old.revoked_at is not None or old.expires_at <= time.time():
        raise HTTPException(409, "憑證已失效，請重新簽發")
    scope = list(
        db.scalars(
            select(CredentialSubject.subject_id).where(
                CredentialSubject.tenant_id == tenant_id, CredentialSubject.credential_id == old.id
            )
        )
    )
    credential, token = issue_credential(db, tenant_id, agent_id, scope, old.expires_at)
    old.revoked_at = time.time()
    record(db, request, auth, tenant_id, "credential.rotated", old.id, {"replacement_id": credential.id})
    return {"id": credential.id, "token": token, "expires_at": credential.expires_at}


@router.delete("/tenants/{tenant_id}/agents/{agent_id}/credentials/{credential_id}", status_code=204)
def revoke(
    tenant_id: str,
    agent_id: str,
    credential_id: str,
    request: Request,
    auth: PersonAuth = Depends(person_auth),
    db: Session = Depends(get_db),
):
    tenant_membership(db, tenant_id, auth, admin=True)
    credential = owned_credential(db, tenant_id, agent_id, credential_id)
    if credential.revoked_at is None:
        credential.revoked_at = time.time()
        record(db, request, auth, tenant_id, "credential.revoked", credential.id)
