import time

from fastapi.testclient import TestClient


def admin_login(client):
    result = client.post(
        "/v1/auth/login", json={"email": "admin@example.test", "password": "correct-horse-battery-123"}
    )
    assert result.status_code == 200
    data = result.json()
    client.headers["X-CSRF-Token"] = data["csrf_token"]
    return data["memberships"][0]["tenant_id"]


def create(client, path, body):
    response = client.post(path, json=body)
    assert response.status_code == 201, response.text
    return response.json()


def setup_agent(client, tenant):
    base = f"/v1/tenants/{tenant}"
    agent = create(client, base + "/agents", {"name": "Support"})
    subject = create(client, base + f"/agents/{agent['id']}/subjects", {"name": "Customer A"})
    credential = create(
        client,
        base + f"/agents/{agent['id']}/credentials",
        {"subject_ids": [subject["id"]], "expires_in_days": 30},
    )
    return agent, subject, credential


def test_credential_rotation_disable_and_no_secret_listing(app):
    with TestClient(app) as admin, TestClient(app) as machine:
        tenant = admin_login(admin)
        agent, subject, credential = setup_agent(admin, tenant)
        base = f"/v1/tenants/{tenant}/agents/{agent['id']}"
        machine.headers["Authorization"] = "Bearer " + credential["token"]
        identity = machine.get("/v1/agent/me")
        assert identity.status_code == 200
        assert identity.json()["subject_ids"] == [subject["id"]]
        assert identity.json()["agent_id"] == agent["id"]
        forged = machine.get("/v1/agent/me", headers={"X-Tenant-ID": "foreign", "X-Agent-ID": "foreign"})
        assert forged.json()["tenant_id"] == tenant and forged.json()["agent_id"] == agent["id"]
        listed = admin.get(base + "/credentials")
        assert listed.status_code == 200
        assert credential["token"] not in listed.text and "token_hash" not in listed.text
        rotated = create(admin, base + f"/credentials/{credential['id']}/rotate", {})
        assert machine.get("/v1/agent/me").status_code == 401
        machine.headers["Authorization"] = "Bearer " + rotated["token"]
        assert machine.get("/v1/agent/me").status_code == 200
        assert admin.patch(base, json={"active": False}).status_code == 200
        assert machine.get("/v1/agent/me").status_code == 401
        audit = admin.get(f"/v1/tenants/{tenant}/audit").text
        assert credential["token"] not in audit and rotated["token"] not in audit


def test_database_rejects_cross_tenant_and_cross_agent_links(app):
    import pytest
    from sqlalchemy.exc import IntegrityError

    from kcs.models import Agent, AgentSpaceGrant, CredentialSubject, Tenant

    with TestClient(app) as admin:
        tenant = admin_login(admin)
        agent, _, credential = setup_agent(admin, tenant)
        _, other_subject, _ = setup_agent(admin, tenant)
        space = create(admin, f"/v1/tenants/{tenant}/spaces", {"name": "Local"})
        with app.state.database.sessions.begin() as db:
            foreign = Tenant(name="Other tenant")
            db.add(foreign)
            db.flush()
            foreign_agent = Agent(tenant_id=foreign.id, name="Foreign agent")
            db.add(foreign_agent)
            db.flush()
            foreign_agent_id = foreign_agent.id
        with pytest.raises(IntegrityError), app.state.database.sessions.begin() as db:
            db.add(AgentSpaceGrant(tenant_id=tenant, space_id=space["id"], agent_id=foreign_agent_id))
        with pytest.raises(IntegrityError), app.state.database.sessions.begin() as db:
            db.add(
                CredentialSubject(
                    tenant_id=tenant,
                    agent_id=agent["id"],
                    credential_id=credential["id"],
                    subject_id=other_subject["id"],
                )
            )


def test_explicit_credential_revocation_is_idempotent(app):
    with TestClient(app) as admin, TestClient(app) as machine:
        tenant = admin_login(admin)
        agent, _, credential = setup_agent(admin, tenant)
        machine.headers["Authorization"] = "Bearer " + credential["token"]
        endpoint = f"/v1/tenants/{tenant}/agents/{agent['id']}/credentials/{credential['id']}"
        assert machine.get("/v1/agent/me").status_code == 200
        assert admin.delete(endpoint).status_code == 204
        assert admin.delete(endpoint).status_code == 204
        assert machine.get("/v1/agent/me").status_code == 401
        assert admin.post(endpoint + "/rotate", json={}).status_code == 409


def test_credential_subject_scope_is_explicit_and_agent_bound(app):
    with TestClient(app) as admin, TestClient(app) as machine:
        tenant = admin_login(admin)
        agent, subject, credential = setup_agent(admin, tenant)
        other_agent, other_subject, _ = setup_agent(admin, tenant)
        base = f"/v1/tenants/{tenant}/agents/{agent['id']}"
        assert (
            admin.post(base + "/credentials", json={"subject_ids": [], "expires_in_days": 30}).status_code
            == 422
        )
        assert (
            admin.post(
                base + "/credentials", json={"subject_ids": [other_subject["id"]], "expires_in_days": 30}
            ).status_code
            == 404
        )
        assert (
            admin.patch(
                f"/v1/tenants/{tenant}/agents/{other_agent['id']}/subjects/{subject['id']}",
                json={"active": False},
            ).status_code
            == 404
        )
        machine.headers["Authorization"] = "Bearer " + credential["token"]
        assert admin.patch(base + f"/subjects/{subject['id']}", json={"active": False}).status_code == 200
        assert machine.get("/v1/agent/me").json()["subject_ids"] == []


def test_space_grants_and_foreign_tenant_objects_are_hidden(app):
    from kcs.models import Tenant

    with TestClient(app) as admin, TestClient(app) as machine:
        tenant = admin_login(admin)
        agent, _, credential = setup_agent(admin, tenant)
        base = f"/v1/tenants/{tenant}"
        first = create(admin, base + "/spaces", {"name": "Allowed"})
        second = create(admin, base + "/spaces", {"name": "Hidden"})
        assert first["sync_state"] == "pending"
        machine.headers["Authorization"] = "Bearer " + credential["token"]
        assert machine.get("/v1/agent/me").json()["space_ids"] == []
        grant_url = base + f"/spaces/{first['id']}/agents/{agent['id']}"
        assert admin.put(grant_url, json={"active": True}).status_code == 200
        assert machine.get("/v1/agent/me").json()["space_ids"] == [first["id"]]
        assert second["id"] not in machine.get("/v1/agent/me").text
        assert admin.put(grant_url, json={"active": False}).status_code == 200
        assert machine.get("/v1/agent/me").json()["space_ids"] == []
        with app.state.database.sessions.begin() as db:
            foreign = Tenant(name="Foreign")
            db.add(foreign)
            db.flush()
            foreign_id = foreign.id
        for suffix in ("agents", "spaces"):
            assert admin.get(f"/v1/tenants/{foreign_id}/{suffix}").status_code == 404
        assert (
            admin.patch(f"/v1/tenants/{foreign_id}/agents/{agent['id']}", json={"active": False}).status_code
            == 404
        )


def test_person_space_visibility_requires_explicit_grant(app):
    with TestClient(app) as admin, TestClient(app) as viewer:
        tenant = admin_login(admin)
        base = f"/v1/tenants/{tenant}"
        person = create(
            admin,
            base + "/members",
            {"email": "reader@example.test", "password": "reader-password-long", "role": "viewer"},
        )
        space = create(admin, base + "/spaces", {"name": "Restricted"})
        signed = viewer.post(
            "/v1/auth/login", json={"email": "reader@example.test", "password": "reader-password-long"}
        ).json()
        viewer.headers["X-CSRF-Token"] = signed["csrf_token"]
        assert viewer.get(base + "/spaces").json()["items"] == []
        assert viewer.get(base + f"/spaces/{space['id']}").status_code == 404
        assert viewer.post(base + "/agents", json={"name": "Forbidden"}).status_code == 403
        grant = base + f"/spaces/{space['id']}/people/{person['person_id']}"
        assert admin.put(grant, json={"active": True, "level": "viewer"}).status_code == 200
        assert viewer.get(base + f"/spaces/{space['id']}").status_code == 200
        assert len(viewer.get(base + "/spaces").json()["items"]) == 1
        assert viewer.put(grant, json={"active": True, "level": "editor"}).status_code == 403
        assert admin.put(grant, json={"active": False, "level": "viewer"}).status_code == 200
        assert viewer.get(base + f"/spaces/{space['id']}").status_code == 404


def test_expired_credential_and_disabled_tenant_fail(app):
    from sqlalchemy import update

    from kcs.models import AgentCredential, Tenant

    with TestClient(app) as admin, TestClient(app) as machine:
        tenant = admin_login(admin)
        _, _, credential = setup_agent(admin, tenant)
        machine.headers["Authorization"] = "Bearer " + credential["token"]
        with app.state.database.sessions.begin() as db:
            db.execute(
                update(AgentCredential)
                .where(AgentCredential.id == credential["id"])
                .values(expires_at=time.time() - 1)
            )
        assert machine.get("/v1/agent/me").status_code == 401
        _, _, current = setup_agent(admin, tenant)
        machine.headers["Authorization"] = "Bearer " + current["token"]
        with app.state.database.sessions.begin() as db:
            db.execute(update(Tenant).where(Tenant.id == tenant).values(active=False))
        assert machine.get("/v1/agent/me").status_code == 401
