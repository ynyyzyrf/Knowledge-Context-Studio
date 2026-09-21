from fastapi.testclient import TestClient
from test_agents_spaces import admin_login, create, setup_agent


def test_session_binding_messages_and_idempotency(app):
    with TestClient(app) as admin, TestClient(app) as machine:
        tenant = admin_login(admin)
        _, subject, credential = setup_agent(admin, tenant)
        machine.headers["Authorization"] = "Bearer " + credential["token"]
        body = {"subject_id": subject["id"], "idempotency_key": "session-1"}
        session = create(machine, "/v1/sessions", body)
        assert create(machine, "/v1/sessions", body)["id"] == session["id"]
        path = f"/v1/sessions/{session['id']}/messages"
        message = {"message_id": "message-1", "role": "user", "content": "I prefer tea."}
        first = create(machine, path, message)
        assert create(machine, path, message)["id"] == first["id"]
        assert machine.post(path, json={**message, "content": "Changed"}).status_code == 409
        assert machine.post(path, json={**message, "subject_id": "someone-else"}).status_code == 422
        stored = machine.get(path)
        assert stored.status_code == 200
        assert len(stored.json()["items"]) == 1
        assert stored.json()["items"][0]["content"] == message["content"]
        assert len(machine.get("/v1/sessions").json()["items"]) == 1


def test_other_subject_credential_cannot_read_or_write_session(app):
    with TestClient(app) as admin, TestClient(app) as first, TestClient(app) as second:
        tenant = admin_login(admin)
        agent, subject, credential = setup_agent(admin, tenant)
        base = f"/v1/tenants/{tenant}/agents/{agent['id']}"
        other_subject = create(admin, base + "/subjects", {"name": "B"})
        other_credential = create(
            admin, base + "/credentials", {"subject_ids": [other_subject["id"]], "expires_in_days": 30}
        )
        first.headers["Authorization"] = "Bearer " + credential["token"]
        second.headers["Authorization"] = "Bearer " + other_credential["token"]
        session = create(first, "/v1/sessions", {"subject_id": subject["id"], "idempotency_key": "x"})
        path = f"/v1/sessions/{session['id']}/messages"
        assert second.get(path).status_code == 404
        assert (
            second.post(path, json={"message_id": "injected", "role": "user", "content": "x"}).status_code
            == 404
        )
        assert second.get("/v1/sessions").json()["items"] == []
        assert (
            second.post(
                "/v1/sessions", json={"subject_id": subject["id"], "idempotency_key": "bad"}
            ).status_code
            == 404
        )
        admin.patch(base + f"/subjects/{subject['id']}", json={"active": False})
        assert first.get(path).status_code == 404


def test_session_key_cannot_rebind_subject_and_other_agent_cannot_read(app):
    with TestClient(app) as admin, TestClient(app) as first, TestClient(app) as second:
        tenant = admin_login(admin)
        agent, subject, _ = setup_agent(admin, tenant)
        base = f"/v1/tenants/{tenant}/agents/{agent['id']}"
        other = create(admin, base + "/subjects", {"name": "Other"})
        broad = create(admin, base + "/credentials", {"subject_ids": [subject["id"], other["id"]]})
        first.headers["Authorization"] = "Bearer " + broad["token"]
        session = create(first, "/v1/sessions", {"subject_id": subject["id"], "idempotency_key": "fixed"})
        assert (
            first.post(
                "/v1/sessions", json={"subject_id": other["id"], "idempotency_key": "fixed"}
            ).status_code
            == 409
        )
        _, _, other_agent_credential = setup_agent(admin, tenant)
        second.headers["Authorization"] = "Bearer " + other_agent_credential["token"]
        assert second.get(f"/v1/sessions/{session['id']}/messages").status_code == 404
