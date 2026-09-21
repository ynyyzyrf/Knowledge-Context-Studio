from sqlalchemy import select

from .models import Membership, Person, Tenant
from .security import password_hasher


def bootstrap_admin(database, *, email: str, password: str, tenant_name: str):
    if len(password) < 16:
        raise ValueError("Bootstrap password must be at least 16 characters")
    with database.sessions.begin() as db:
        if db.scalar(select(Person.id).limit(1)):
            raise ValueError("Already initialized; use member management")
        person = Person(email=email.strip().lower(), password_hash=password_hasher.hash(password))
        tenant = Tenant(name=tenant_name)
        db.add_all([person, tenant])
        db.flush()
        db.add(Membership(tenant_id=tenant.id, person_id=person.id, role="tenant_admin"))
        return {"person_id": person.id, "tenant_id": tenant.id}
