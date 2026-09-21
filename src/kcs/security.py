import hashlib
import secrets
import time
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import LoginSession, Membership, Person, Tenant

password_hasher = PasswordHasher()
dummy_hash = password_hasher.hash(secrets.token_urlsafe(32))


def digest(value: str):
    return hashlib.sha256(value.encode()).hexdigest()


def verify_password(encoded: str, password: str):
    try:
        return password_hasher.verify(encoded, password)
    except (VerificationError, InvalidHashError):
        return False


def get_db(request: Request):
    with request.app.state.database.sessions.begin() as db:
        yield db


@dataclass
class PersonAuth:
    person: Person
    session: LoginSession


def person_auth(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("kcs_session", "")
    session = db.get(LoginSession, digest(token)) if token else None
    person = db.get(Person, session.person_id) if session else None
    if not session or session.expires_at <= time.time() or not person or not person.active:
        raise HTTPException(401, "登入已失效")
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        csrf = request.headers.get("X-CSRF-Token", "")
        if not csrf or not secrets.compare_digest(digest(csrf), session.csrf_hash):
            raise HTTPException(403, "請重新載入頁面後重試")
    return PersonAuth(person, session)


def tenant_membership(db: Session, tenant_id: str, auth: PersonAuth, *, admin=False):
    if admin:
        # Serialize policy mutations, including permission recheck after waiting.
        db.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    member = db.get(Membership, (tenant_id, auth.person.id))
    tenant = db.get(Tenant, tenant_id)
    if not tenant or not tenant.active or not member or not member.active:
        raise HTTPException(404, "找不到團隊")
    if admin and member.role != "tenant_admin":
        raise HTTPException(403, "需要團隊管理權限")
    return member


def membership_list(db: Session, person_id: str):
    rows = db.execute(
        select(Membership, Tenant)
        .join(Tenant)
        .where(Membership.person_id == person_id, Membership.active.is_(True), Tenant.active.is_(True))
    ).all()
    return [{"tenant_id": t.id, "name": t.name, "role": m.role} for m, t in rows]
