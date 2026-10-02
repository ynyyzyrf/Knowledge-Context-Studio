import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_agents_spaces import create, setup_agent
from test_documents import setup
from test_resource_namespaces import second_user

from kcs.models import AgentCredential, NamespaceEntry, NamespaceMessage, NamespaceRevision


def paths(base, space, kind):
    return base + f"/user/default/{kind}", f"/v1/spaces/{space['id']}/user/default/{kind}"


def grant(admin, human, agent, read=True, write=True):
    response = admin.put(human + "/agent-access/" + agent["id"], json={"can_read": read, "can_write": write})
    assert response.status_code == 200, response.text


def item(client, path, key="one", **kwargs):
    response = client.post(
        path + "/entries",
        json={"external_id": key, "title": "Context title", "content": "Exact useful knowledge", **kwargs},
    )
    assert response.status_code == 201, response.text
    return response.json()


def enable(admin, human, row, status="active", **kwargs):
    response = admin.put(
        human + "/entries/" + row["id"],
        json={
            "version": row["version"],
            "title": row["title"],
            "content": row["content"],
            "status": status,
            **kwargs,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("kind", ["memories", "sessions", "skills", "peers"])
def test_person_space_isolation_lifecycle_and_revocation(app, kind):
    with TestClient(app) as admin, TestClient(app) as machine, TestClient(app) as other:
        tenant, agent, _, space, base = setup(admin, machine)
        second_user(app, tenant, other)
        human, api = paths(base, space, kind)
        # Existing private resource grants do not implicitly enable new scopes.
        admin.put(base + "/user/default/agent-access/" + agent["id"], json={"active": True})
        assert machine.get(api + "/entries").status_code == 404
        grant(admin, human, agent)
        row = item(machine, api)
        assert machine.get(api + "/entries").json()["total"] == (1 if kind == "sessions" else 0)
        if kind != "sessions":
            assert machine.get(api + "/entries/" + row["id"]).status_code == 404
            row = enable(admin, human, row)
        assert machine.get(api + "/entries/" + row["id"]).json()["content"] == row["content"]
        assert other.get(human + "/entries").json()["total"] == 0
        assert other.get(human + "/entries/" + row["id"]).status_code == 404
        other_space = create(admin, f"/v1/tenants/{tenant}/spaces", {"name": "Other"})
        foreign = f"/v1/tenants/{tenant}/spaces/{other_space['id']}/user/default/{kind}/entries/{row['id']}"
        assert admin.get(foreign).status_code == 404
        assert machine.get(api + "/entries", params={"tenant_id": tenant}).status_code == 422
        assert machine.put(api + "/entries/" + row["id"], json={}).status_code == 405
        previous = row
        row = enable(admin, human, row, content="Corrected current knowledge")
        stale = admin.put(
            human + "/entries/" + row["id"],
            json={"version": previous["version"], "title": "stale", "content": "stale", "status": "active"},
        )
        assert stale.status_code == 409
        detail = admin.get(human + "/entries/" + row["id"]).json()
        assert len(detail["revisions"]) >= 2
        # A write-only grant cannot read content or reveal revised content through a retry.
        grant(admin, human, agent, read=False)
        assert machine.get(api + "/entries/" + row["id"]).status_code == 404
        replay = item(machine, api)
        assert replay["id"] == row["id"] and "content" not in replay
        grant(admin, human, agent)
        row = enable(admin, human, row, status="disabled")
        assert machine.get(api + "/entries/" + row["id"]).status_code == 404
        row = enable(admin, human, row)
        assert (
            admin.post(
                human + "/entries/" + row["id"] + "/delete", json={"version": row["version"]}
            ).status_code
            == 200
        )
        assert machine.get(api + "/entries/" + row["id"]).status_code == 404
        with app.state.database.sessions() as db:
            assert db.get(NamespaceEntry, row["id"]).content == ""
            assert all(
                r.content == ""
                for r in db.scalars(select(NamespaceRevision).where(NamespaceRevision.entry_id == row["id"]))
            )
        assert (
            machine.post(
                api + "/entries",
                json={"external_id": "one", "title": "Context title", "content": "Exact useful knowledge"},
            ).status_code
            == 409
        )


def test_session_to_memory_sources_idempotency_and_erasure(app):
    with TestClient(app) as admin, TestClient(app) as machine:
        _, agent, _, space, base = setup(admin, machine)
        human, api = paths(base, space, "sessions")
        memories, agent_memories = paths(base, space, "memories")
        grant(admin, human, agent)
        grant(admin, memories, agent)
        session = item(machine, api)
        body = {"external_id": "msg-one", "role": "user", "content": "Remember the agreed support hours."}
        path = api + "/entries/" + session["id"] + "/messages"
        response = machine.post(path, json=body)
        assert response.status_code == 201, response.text
        msg = response.json()
        assert machine.post(path, json=body).json()["id"] == msg["id"]
        assert machine.post(path, json={**body, "content": "changed"}).status_code == 409
        assert machine.get(path).json()["items"][0]["content"] == body["content"]
        candidate = item(machine, agent_memories, source_message_ids=[msg["id"]])
        source = admin.get(memories + "/entries/" + candidate["id"] + "/sources").json()
        assert source["items"][0]["content"] == body["content"]
        enable(admin, memories, candidate)
        assert machine.get(agent_memories + "/entries").json()["total"] == 1
        assert (
            admin.post(
                human + "/entries/" + session["id"] + "/delete", json={"version": session["version"]}
            ).status_code
            == 200
        )
        assert machine.get(path).status_code == 404
        source = admin.get(memories + "/entries/" + candidate["id"] + "/sources").json()
        assert source["items"] == [] and source["unavailable_count"] == 1
        with app.state.database.sessions() as db:
            assert db.get(NamespaceMessage, msg["id"]).content == ""


def test_token_and_space_scope_no_cross_agent_session_writes(app):
    with TestClient(app) as admin, TestClient(app) as machine, TestClient(app) as second:
        tenant, agent, _, space, base = setup(admin, machine)
        human, api = paths(base, space, "sessions")
        grant(admin, human, agent)
        session = item(machine, api)
        other_agent, _, credential = setup_agent(admin, tenant)
        second.headers["Authorization"] = "Bearer " + credential["token"]
        admin.put(base + "/agents/" + other_agent["id"], json={"active": True})
        grant(admin, human, other_agent)
        body = {"external_id": "msg", "role": "assistant", "content": "forged append"}
        assert second.post(api + "/entries/" + session["id"] + "/messages", json=body).status_code == 403
        admin.put(base + "/agents/" + agent["id"], json={"active": False})
        assert machine.get(api + "/entries").status_code == 404
        admin.put(base + "/agents/" + agent["id"], json={"active": True})
        with app.state.database.sessions.begin() as db:
            db.get(AgentCredential, credential["id"]).namespace_person_id = None
        assert second.get(api + "/entries").status_code == 404


def test_pagination_csrf_source_injection_and_privacy(app):
    with TestClient(app) as admin, TestClient(app) as machine, TestClient(app) as other:
        tenant, agent, _, space, base = setup(admin, machine)
        second_user(app, tenant, other)
        human, api = paths(base, space, "memories")
        grant(admin, human, agent)
        for i in range(13):
            row = item(admin, human, key=str(i))
            enable(admin, human, row)
        first = machine.get(api + "/entries", params={"limit": 10}).json()
        second = machine.get(api + "/entries", params={"limit": 10, "offset": 10}).json()
        assert first["total"] == 13 and len(first["items"]) == 10 and len(second["items"]) == 3
        assert not ({r["id"] for r in first["items"]} & {r["id"] for r in second["items"]})
        assert machine.get(api + "/entries", params={"q": "%"}).json()["items"] == []
        assert machine.get(api.replace("memories", "privacy") + "/entries").status_code == 422
        assert (
            admin.post(
                human + "/entries",
                json={"external_id": "forged", "title": "No", "content": "No", "person_id": "other"},
            ).status_code
            == 422
        )
        sessions, _ = paths(base, space, "sessions")
        s = item(other, sessions)
        message = other.post(
            sessions + "/entries/" + s["id"] + "/messages",
            json={"external_id": "one", "role": "user", "content": "foreign source"},
        ).json()
        assert (
            admin.post(
                human + "/entries",
                json={
                    "external_id": "bad-source",
                    "title": "No",
                    "content": "No",
                    "source_message_ids": [message["id"]],
                },
            ).status_code
            == 404
        )
        csrf = admin.headers.pop("X-CSRF-Token")
        assert (
            admin.post(
                human + "/entries", json={"external_id": "csrf", "title": "No", "content": "No"}
            ).status_code
            == 403
        )
        admin.headers["X-CSRF-Token"] = csrf


def test_context_readback_space_scopes_and_revoke_during_engine_call(app):
    from test_publication import Engine

    from kcs.models import NamespaceScopeGrant

    engine = Engine()
    app.state.context_engine_factory = lambda: engine
    with TestClient(app) as admin, TestClient(app) as machine:
        _, agent, subject, space, base = setup(admin, machine)
        human, _ = paths(base, space, "memories")
        grant(admin, human, agent)
        row = item(admin, human, content="Unique personal support policy")
        query = {"subject_id": subject["id"], "query": "support", "space_ids": [space["id"]]}
        assert machine.post("/v1/context", json=query).json()["personal_context"] == []
        row = enable(admin, human, row)
        result = machine.post("/v1/context", json=query).json()
        assert result["personal_context"][0]["id"] == row["id"]
        assert "Unique personal support policy" in result["context"]
        assert machine.post("/v1/context", json={**query, "space_ids": []}).json()["personal_context"] == []
        assert admin.get(base).json()["memory_count"] == 1
        old_find = engine.find

        def revoke(*args):
            with app.state.database.sessions.begin() as db:
                g = db.scalar(
                    select(NamespaceScopeGrant).where(
                        NamespaceScopeGrant.agent_id == agent["id"], NamespaceScopeGrant.kind == "memories"
                    )
                )
                g.can_read = False
            return old_find(*args)

        engine.find = revoke
        assert machine.post("/v1/context", json=query).json()["personal_context"] == []
