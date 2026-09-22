from fastapi.testclient import TestClient
from sqlalchemy import select
from test_agents_spaces import create
from test_documents import setup
from test_publication import Engine

from kcs.document_worker import run_one
from kcs.models import AgentCredential, Membership, Person
from kcs.security import password_hasher


def upload(client, base, **params):
    return client.post(
        base + "/documents",
        params={"filename": "guide.md", **params},
        content=b"Namespace marker: private knowledge.",
    )


def second_user(app, tenant, client):
    with app.state.database.sessions.begin() as db:
        person = Person(
            email="other@example.test", password_hash=password_hasher.hash("correct-horse-other-123")
        )
        db.add(person)
        db.flush()
        identity = person.id
        db.add(Membership(tenant_id=tenant, person_id=identity, role="tenant_admin"))
    result = client.post(
        "/v1/auth/login", json={"email": "other@example.test", "password": "correct-horse-other-123"}
    )
    assert result.status_code == 200, result.text
    client.headers["X-CSRF-Token"] = result.json()["csrf_token"]
    return identity


def test_default_is_authenticated_person_and_space_not_subject(app):
    with TestClient(app) as admin, TestClient(app) as machine, TestClient(app) as other:
        tenant, _, _, _, base = setup(admin, machine)
        second_user(app, tenant, other)
        folder = admin.post(base + "/folders", json={"name": "test"})
        assert folder.status_code == 201, folder.text
        assert other.get(base + "/folders").json()["items"] == []
        assert upload(other, base, folder="test").status_code == 404
        private = upload(admin, base, folder="test").json()
        assert private["scope"] == "private"
        assert private["location"] == "user/default/resources/test"
        other_doc = upload(other, base).json()
        shared = upload(admin, base, scope="shared").json()
        assert len({private["id"], other_doc["id"], shared["id"]}) == 3
        for client, forbidden in [(admin, other_doc), (other, private)]:
            assert client.get(base + "/documents/" + forbidden["id"]).status_code == 404
            assert client.delete(base + "/documents/" + forbidden["id"]).status_code == 404
            assert forbidden["id"] not in client.get(base + "/context").text
            assert len(client.get(base + "/documents").json()["items"]) == 2
            assert client.get(base).json()["document_count"] == 2
        tree = admin.get(base + "/context").json()
        assert tree["namespace"]["identity"] == "authenticated_user"
        assert tree["subjects"] == []
        assert [d["name"] for d in tree["namespace"]["directories"]] == [
            "memories",
            "peers",
            "privacy",
            "resources",
            "sessions",
            "skills",
        ]
        other_space = create(admin, f"/v1/tenants/{tenant}/spaces", {"name": "Other"})
        second_base = f"/v1/tenants/{tenant}/spaces/{other_space['id']}"
        assert admin.get(second_base + "/folders").json()["items"] == []
        assert admin.get(second_base + "/documents/" + private["id"]).status_code == 404
        for bad in ["../escape", "a/b", "..", "a\\b", "a%2fb", "viking:", " x"]:
            assert admin.post(base + "/folders", json={"name": bad}).status_code == 422
        assert admin.post(base + "/folders", json={"name": "test", "scope": "shared"}).status_code == 201
        assert len(admin.get(base + "/folders", params={"scope": "shared"}).json()["items"]) == 1


def test_private_search_acl_identity_recheck_and_legacy_tokens(app):
    engine = Engine()  # Returns all hits, including foreign namespaces.
    app.state.context_engine_factory = lambda: engine
    with TestClient(app) as admin, TestClient(app) as machine, TestClient(app) as other:
        tenant, agent, subject, space, base = setup(admin, machine)
        second_user(app, tenant, other)
        own = upload(admin, base).json()
        upload(other, base)
        shared = upload(admin, base, scope="shared").json()
        for _ in range(3):
            assert run_one(app.state.database, app.state.settings, engine_factory=lambda: engine)
        path = f"/v1/spaces/{space['id']}/user/default/resources/search"
        grant = base + f"/user/default/agent-access/{agent['id']}"
        assert machine.post(path, json={"query": "marker"}).status_code == 404
        assert admin.put(grant, json={"active": True}).status_code == 200
        result = machine.post(path, json={"query": "marker"})
        assert result.status_code == 200, result.text
        assert [x["document_id"] for x in result.json()["items"]] == [own["id"]]
        # Human search includes only current user's private + space shared documents.
        assert {
            x["document_id"] for x in admin.post(base + "/search", json={"query": "marker"}).json()["items"]
        } == {own["id"], shared["id"]}
        assert (
            own["id"]
            in machine.post("/v1/context", json={"subject_id": subject["id"], "query": "marker"}).text
        )
        engine.on_find = lambda: admin.put(grant, json={"active": False})
        assert machine.post(path, json={"query": "marker"}).status_code == 404
        assert (
            own["id"]
            not in machine.post("/v1/context", json={"subject_id": subject["id"], "query": "marker"}).text
        )
        engine.on_find = None
        admin.put(grant, json={"active": True})
        with app.state.database.sessions.begin() as db:
            credential = db.scalar(select(AgentCredential).where(AgentCredential.agent_id == agent["id"]))
            credential.namespace_person_id = None
        assert machine.post(path, json={"query": "marker"}).status_code == 404
        assert machine.post(
            path.replace("default", "someone-else"), json={"query": "marker"}
        ).status_code in (404, 405)
        assert machine.post(path.replace("resources", "privacy"), json={"query": "marker"}).status_code in (
            404,
            405,
        )


def test_rotation_preserves_namespace_owner_and_space_revoke_blocks(app):
    with TestClient(app) as admin, TestClient(app) as machine, TestClient(app) as other:
        tenant, agent, _, space, base = setup(admin, machine)
        second_user(app, tenant, other)
        with app.state.database.sessions.begin() as db:
            original = db.scalar(select(AgentCredential).where(AgentCredential.agent_id == agent["id"]))
            original_id, owner = original.id, original.namespace_person_id
        endpoint = f"/v1/tenants/{tenant}/agents/{agent['id']}/credentials/{original_id}/rotate"
        assert other.post(endpoint, json={}).status_code == 403
        rotated = create(
            admin, f"/v1/tenants/{tenant}/agents/{agent['id']}/credentials/{original_id}/rotate", {}
        )
        with app.state.database.sessions.begin() as db:
            assert db.get(AgentCredential, rotated["id"]).namespace_person_id == owner
        machine.headers["Authorization"] = "Bearer " + rotated["token"]
        admin.put(base + f"/user/default/agent-access/{agent['id']}", json={"active": True})
        admin.put(base + f"/agents/{agent['id']}", json={"active": False})
        assert (
            machine.post(
                f"/v1/spaces/{space['id']}/user/default/resources/search", json={"query": "hello"}
            ).status_code
            == 404
        )


def test_same_agent_tokens_resolve_different_users_and_spaces(app):
    engine = Engine()
    app.state.context_engine_factory = lambda: engine
    with TestClient(app) as admin, TestClient(app) as machine, TestClient(app) as other:
        tenant, agent, subject, space, base = setup(admin, machine)
        other_person = second_user(app, tenant, other)
        own = upload(admin, base).json()
        other_doc = upload(other, base).json()
        second = create(admin, f"/v1/tenants/{tenant}/spaces", {"name": "Independent"})
        second_base = f"/v1/tenants/{tenant}/spaces/{second['id']}"
        foreign = upload(admin, second_base).json()
        for _ in range(3):
            assert run_one(app.state.database, app.state.settings, engine_factory=lambda: engine)
        grant = base + f"/user/default/agent-access/{agent['id']}"
        admin.put(grant, json={"active": True})
        other.put(grant, json={"active": True})
        path = f"/v1/spaces/{space['id']}/user/default/resources/search"
        assert [x["document_id"] for x in machine.post(path, json={"query": "marker"}).json()["items"]] == [
            own["id"]
        ]
        token = create(
            other,
            f"/v1/tenants/{tenant}/agents/{agent['id']}/credentials",
            {"subject_ids": [subject["id"]], "expires_in_days": 1},
        )
        machine.headers["Authorization"] = "Bearer " + token["token"]
        result = machine.post(path, json={"query": "marker"})
        assert [x["document_id"] for x in result.json()["items"]] == [other_doc["id"]]
        assert foreign["id"] not in result.text
        assert (
            machine.post(path.replace(space["id"], second["id"]), json={"query": "marker"}).status_code == 404
        )
        with app.state.database.sessions.begin() as db:
            db.get(Membership, (tenant, other_person)).active = False
        assert machine.post(path, json={"query": "marker"}).status_code == 404
