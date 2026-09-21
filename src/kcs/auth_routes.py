import secrets
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import AuditEvent, LoginSession, Membership, Person, Tenant
from .security import (
    PersonAuth,
    digest,
    dummy_hash,
    get_db,
    membership_list,
    password_hasher,
    person_auth,
    tenant_membership,
    verify_password,
)

router = APIRouter(prefix="/v1")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginInput(StrictModel):
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    password: str = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):
        return value.strip().lower()


class MemberInput(LoginInput):
    password: str = Field(min_length=16, max_length=256)
    role: Literal["tenant_admin", "editor", "viewer"]


class MemberUpdate(StrictModel):
    active: bool


class ExistingMemberInput(StrictModel):
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    role: Literal["tenant_admin", "editor", "viewer"]


def profile(db, person, csrf):
    return {
        "person": {"id": person.id, "email": person.email},
        "memberships": membership_list(db, person.id),
        "csrf_token": csrf,
    }


@router.post("/auth/login")
def login(body: LoginInput, request: Request, response: Response):
    settings = request.app.state.settings
    result = None
    with request.app.state.database.sessions.begin() as db:
        person = db.scalar(select(Person).where(Person.email == body.email).with_for_update())
        verified = verify_password(person.password_hash if person else dummy_hash, body.password)
        if person and person.active and person.locked_until <= time.time() and verified:
            person.failed_logins = 0
            if password_hasher.check_needs_rehash(person.password_hash):
                person.password_hash = password_hasher.hash(body.password)
            token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            db.add(
                LoginSession(
                    token_hash=digest(token),
                    person_id=person.id,
                    csrf_hash=digest(csrf),
                    expires_at=time.time() + settings.session_hours * 3600,
                )
            )
            result = profile(db, person, csrf)
        elif person and person.locked_until <= time.time():
            person.failed_logins += 1
            if person.failed_logins >= 5:
                person.locked_until = time.time() + 900
    if result is None:
        raise HTTPException(401, "帳號或密碼錯誤，或暫時無法登入")
    options = {
        "secure": settings.secure_cookies,
        "samesite": "strict",
        "max_age": settings.session_hours * 3600,
        "path": "/",
    }
    response.set_cookie("kcs_session", token, httponly=True, **options)
    response.set_cookie("kcs_csrf", csrf, httponly=False, **options)
    return result


@router.get("/auth/me")
def me(request: Request, auth: PersonAuth = Depends(person_auth), db: Session = Depends(get_db)):
    return profile(db, auth.person, request.cookies.get("kcs_csrf"))


@router.post("/auth/logout", status_code=204)
def logout(response: Response, auth: PersonAuth = Depends(person_auth), db: Session = Depends(get_db)):
    db.delete(auth.session)
    response.delete_cookie("kcs_session", path="/")
    response.delete_cookie("kcs_csrf", path="/")


@router.get("/tenants/{tenant_id}/members")
def members(tenant_id: str, auth: PersonAuth = Depends(person_auth), db: Session = Depends(get_db)):
    tenant_membership(db, tenant_id, auth)
    rows = db.execute(select(Membership, Person).join(Person).where(Membership.tenant_id == tenant_id)).all()
    return {
        "items": [{"person_id": p.id, "email": p.email, "role": m.role, "active": m.active} for m, p in rows]
    }


@router.post("/tenants/{tenant_id}/members", status_code=201)
def add_member(
    tenant_id: str,
    body: MemberInput,
    request: Request,
    auth: PersonAuth = Depends(person_auth),
    db: Session = Depends(get_db),
):
    tenant_membership(db, tenant_id, auth, admin=True)
    db.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    person = db.scalar(select(Person).where(Person.email == body.email))
    if person:
        # Never reset another account's password via an invite operation.
        raise HTTPException(409, "此帳號已存在，請使用既有成員邀請流程")
    person = Person(email=body.email, password_hash=password_hasher.hash(body.password))
    db.add(person)
    db.flush()
    db.add(Membership(tenant_id=tenant_id, person_id=person.id, role=body.role))
    db.add(
        AuditEvent(
            tenant_id=tenant_id,
            actor_id=auth.person.id,
            action="member.created",
            target_id=person.id,
            request_id=request.state.request_id,
            details={"role": body.role},
        )
    )
    return {"person_id": person.id, "email": person.email, "role": body.role, "active": True}


@router.patch("/tenants/{tenant_id}/members/{person_id}")
def update_member(
    tenant_id: str,
    person_id: str,
    body: MemberUpdate,
    request: Request,
    auth: PersonAuth = Depends(person_auth),
    db: Session = Depends(get_db),
):
    tenant_membership(db, tenant_id, auth, admin=True)
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    member = db.get(Membership, (tenant_id, person_id))
    if not member:
        raise HTTPException(404, "找不到成員")
    if not body.active and member.active and member.role == "tenant_admin":
        count = db.scalar(
            select(func.count())
            .select_from(Membership)
            .where(
                Membership.tenant_id == tenant_id,
                Membership.role == "tenant_admin",
                Membership.active.is_(True),
            )
        )
        if count <= 1:
            raise HTTPException(409, "必須保留至少一位管理員")
    member.active = body.active
    tenant.policy_version += 1
    db.add(
        AuditEvent(
            tenant_id=tenant_id,
            actor_id=auth.person.id,
            action="member.enabled" if body.active else "member.disabled",
            target_id=person_id,
            request_id=request.state.request_id,
        )
    )
    return {"person_id": person_id, "role": member.role, "active": member.active}


@router.post("/tenants/{tenant_id}/members/existing", status_code=201)
def add_existing_member(
    tenant_id: str,
    body: ExistingMemberInput,
    request: Request,
    auth: PersonAuth = Depends(person_auth),
    db: Session = Depends(get_db),
):
    tenant_membership(db, tenant_id, auth, admin=True)
    person = db.scalar(
        select(Person).where(Person.email == body.email.strip().lower(), Person.active.is_(True))
    )
    if not person:
        raise HTTPException(404, "找不到可加入的帳號")
    if db.get(Membership, (tenant_id, person.id)):
        raise HTTPException(409, "此帳號已在成員名單中")
    db.add(Membership(tenant_id=tenant_id, person_id=person.id, role=body.role))
    db.add(
        AuditEvent(
            tenant_id=tenant_id,
            actor_id=auth.person.id,
            action="member.added",
            target_id=person.id,
            request_id=request.state.request_id,
            details={"role": body.role},
        )
    )
    return {"person_id": person.id, "email": person.email, "role": body.role, "active": True}


@router.get("/tenants/{tenant_id}/audit")
def audit(tenant_id: str, auth: PersonAuth = Depends(person_auth), db: Session = Depends(get_db)):
    tenant_membership(db, tenant_id, auth, admin=True)
    events = db.scalars(
        select(AuditEvent)
        .where(AuditEvent.tenant_id == tenant_id)
        .order_by(AuditEvent.created_at.desc())
        .limit(100)
    ).all()
    return {
        "items": [
            {
                "id": e.id,
                "action": e.action,
                "actor_id": e.actor_id,
                "target_id": e.target_id,
                "created_at": e.created_at,
                "request_id": e.request_id,
                "details": e.details,
            }
            for e in events
        ]
    }
