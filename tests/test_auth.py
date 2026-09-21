from fastapi.testclient import TestClient


def login(client):
    response = client.post(
        "/v1/auth/login", json={"email": "admin@example.test", "password": "correct-horse-battery-123"}
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_login_session_logout_revokes(app):
    with TestClient(app) as client:
        assert client.get("/v1/auth/me").status_code == 401
        data = login(client)
        cookie = client.cookies.get("kcs_session")
        assert cookie and data["memberships"][0]["role"] == "tenant_admin"
        assert client.get("/v1/auth/me").status_code == 200
        assert client.post("/v1/auth/logout").status_code == 403
        assert client.post("/v1/auth/logout", headers={"X-CSRF-Token": data["csrf_token"]}).status_code == 204
        client.cookies.set("kcs_session", cookie)
        assert client.get("/v1/auth/me").status_code == 401


def test_wrong_password_and_cross_origin_fail(app):
    with TestClient(app) as client:
        bad = client.post("/v1/auth/login", json={"email": "admin@example.test", "password": "wrong"})
        assert bad.status_code == 401
        bad = client.post(
            "/v1/auth/login",
            headers={"Origin": "https://attacker.test"},
            json={"email": "admin@example.test", "password": "correct-horse-battery-123"},
        )
        assert bad.status_code == 403


def test_membership_and_disable_current_session(app):
    with TestClient(app) as admin:
        data = login(admin)
        tenant = data["memberships"][0]["tenant_id"]
        headers = {"X-CSRF-Token": data["csrf_token"]}
        created = admin.post(
            f"/v1/tenants/{tenant}/members",
            headers=headers,
            json={"email": "viewer@example.test", "password": "viewer-long-password-123", "role": "viewer"},
        )
        assert created.status_code == 201, created.text
        assert admin.get("/v1/tenants/not-my-tenant/members").status_code == 404
        with TestClient(app) as viewer:
            signed = viewer.post(
                "/v1/auth/login",
                json={"email": "viewer@example.test", "password": "viewer-long-password-123"},
            )
            assert signed.status_code == 200
            denied = viewer.post(
                f"/v1/tenants/{tenant}/members",
                headers={"X-CSRF-Token": signed.json()["csrf_token"]},
                json={"email": "x@example.test", "password": "another-long-password", "role": "tenant_admin"},
            )
            assert denied.status_code == 403
            disabled = admin.patch(
                f"/v1/tenants/{tenant}/members/{created.json()['person_id']}",
                headers=headers,
                json={"active": False},
            )
            assert disabled.status_code == 200
            assert viewer.get(f"/v1/tenants/{tenant}/members").status_code == 404
        audit = admin.get(f"/v1/tenants/{tenant}/audit").json()["items"]
        assert any(item["action"] == "member.disabled" for item in audit)
        assert "viewer-long-password" not in str(audit)


def test_last_admin_cannot_be_disabled(app):
    with TestClient(app) as client:
        data = login(client)
        tenant = data["memberships"][0]["tenant_id"]
        response = client.patch(
            f"/v1/tenants/{tenant}/members/{data['person']['id']}",
            headers={"X-CSRF-Token": data["csrf_token"]},
            json={"active": False},
        )
        assert response.status_code == 409


def test_session_expiration_and_password_lock(app):
    from sqlalchemy import update

    from kcs.models import LoginSession

    with TestClient(app) as client:
        login(client)
        with app.state.database.sessions.begin() as db:
            db.execute(update(LoginSession).values(expires_at=0))
        assert client.get("/v1/auth/me").status_code == 401
        for _ in range(5):
            assert (
                client.post(
                    "/v1/auth/login", json={"email": "admin@example.test", "password": "wrong"}
                ).status_code
                == 401
            )
        assert (
            client.post(
                "/v1/auth/login",
                json={"email": "admin@example.test", "password": "correct-horse-battery-123"},
            ).status_code
            == 401
        )


def test_existing_person_can_join_another_team_without_password_reset(app):
    from kcs.models import Membership, Tenant

    with TestClient(app) as client:
        data = login(client)
        with app.state.database.sessions.begin() as db:
            other = Tenant(name="Second Team")
            db.add(other)
            db.flush()
            other_id = other.id
            db.add(Membership(tenant_id=other.id, person_id=data["person"]["id"], role="tenant_admin"))
        tenant = data["memberships"][0]["tenant_id"]
        headers = {"X-CSRF-Token": data["csrf_token"]}
        created = client.post(
            f"/v1/tenants/{tenant}/members",
            headers=headers,
            json={"email": "shared@example.test", "password": "shared-original-password", "role": "viewer"},
        )
        assert created.status_code == 201
        invited = client.post(
            f"/v1/tenants/{other_id}/members/existing",
            headers=headers,
            json={"email": "shared@example.test", "role": "editor"},
        )
        assert invited.status_code == 201, invited.text
        with TestClient(app) as member:
            response = member.post(
                "/v1/auth/login",
                json={"email": "shared@example.test", "password": "shared-original-password"},
            )
            assert response.status_code == 200
            assert len(response.json()["memberships"]) == 2
