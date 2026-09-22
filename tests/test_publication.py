from fastapi.testclient import TestClient
from test_memory_governance import staged

from kcs.engine import EngineError
from kcs.publication import run_one


class Engine:
    def __init__(self):
        self.content = {}
        self.on_publish = None
        self.on_find = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def publish(self, uri, content):
        self.content[uri] = content
        if self.on_publish:
            self.on_publish()

    def delete(self, uri):
        self.content.pop(uri, None)

    def find(self, root, query, limit):
        if self.on_find:
            self.on_find()
        # Deliberately return all URIs, even those outside the requested scope.
        return [(uri, 1.0) for uri in self.content][:limit]


def approved(app, admin, machine):
    tenant, agent, subject, message, candidate = staged(app, admin, machine)
    base = f"/v1/tenants/{tenant}"
    memory = admin.post(base + f"/candidates/{candidate}/approve", json={"expected_version": 1}).json()
    return base, agent, subject, message, memory


def test_published_memory_is_readable_then_edit_and_disable_revoke_it(app):
    engine = Engine()
    app.state.context_engine_factory = lambda: engine
    with TestClient(app) as admin, TestClient(app) as machine:
        base, _, subject, message, memory = approved(app, admin, machine)
        assert run_one(app.state.database, app.state.settings, engine_factory=lambda: engine)
        rows = machine.get(f"/v1/subjects/{subject['id']}/memories").json()["items"]
        assert rows[0]["id"] == memory["id"] and rows[0]["source_message_ids"] == [message["id"]]
        query = {"subject_id": subject["id"], "query": "drinks"}
        found = machine.post("/v1/context", json=query)
        assert found.status_code == 200 and "jasmine tea" in found.json()["context"]
        endpoint = base + f"/memories/{memory['id']}"
        admin.patch(endpoint, json={"expected_version": 1, "content": "Green tea", "reason": "Correction"})
        assert machine.post("/v1/context", json=query).json()["memories"] == []
        run_one(app.state.database, app.state.settings, engine_factory=lambda: engine)
        found = machine.post("/v1/context", json=query).json()["memories"]
        assert len(found) == 1 and found[0]["version"] == 2 and found[0]["content"] == "Green tea"
        admin.post(endpoint + "/disable", json={"expected_version": 2, "reason": "Stop"})
        assert machine.post("/v1/context", json=query).json()["memories"] == []
        run_one(app.state.database, app.state.settings, engine_factory=lambda: engine)
        assert not engine.content


def test_revocation_during_retrieval_is_checked_after_engine_returns(app):
    engine = Engine()
    app.state.context_engine_factory = lambda: engine
    with TestClient(app) as admin, TestClient(app) as machine:
        base, agent, subject, _, _ = approved(app, admin, machine)
        run_one(app.state.database, app.state.settings, engine_factory=lambda: engine)
        engine.on_find = lambda: admin.patch(base + f"/agents/{agent['id']}", json={"active": False})
        assert (
            machine.post("/v1/context", json={"subject_id": subject["id"], "query": "tea"}).status_code == 401
        )


def test_inflight_old_publication_cannot_activate_edited_revision(app):
    engine = Engine()
    with TestClient(app) as admin, TestClient(app) as machine:
        base, _, subject, _, memory = approved(app, admin, machine)
        engine.on_publish = lambda: admin.patch(
            base + f"/memories/{memory['id']}",
            json={"expected_version": 1, "content": "Corrected", "reason": "During publication"},
        )
        run_one(app.state.database, app.state.settings, engine_factory=lambda: engine)
        assert machine.get(f"/v1/subjects/{subject['id']}/memories").json()["items"] == []
        engine.on_publish = None
        run_one(app.state.database, app.state.settings, engine_factory=lambda: engine)
        run_one(app.state.database, app.state.settings, engine_factory=lambda: engine)
        assert machine.get(f"/v1/subjects/{subject['id']}/memories").json()["items"][0]["version"] == 2


def test_engine_failure_never_activates_memory(app):
    engine = Engine()

    def fail():
        raise EngineError("engine_index_incomplete")

    engine.on_publish = fail
    with TestClient(app) as admin, TestClient(app) as machine:
        _, _, subject, _, _ = approved(app, admin, machine)
        run_one(app.state.database, app.state.settings, engine_factory=lambda: engine)
        assert machine.get(f"/v1/subjects/{subject['id']}/memories").json()["items"] == []


def test_late_failed_write_is_durably_cleaned(app):
    engine = Engine()
    with TestClient(app) as admin, TestClient(app) as machine:
        base, _, _, _, memory = approved(app, admin, machine)

        def fail_after_delete():
            late_content = dict(engine.content)
            admin.post(
                base + f"/memories/{memory['id']}/delete", json={"expected_version": 1, "reason": "Remove"}
            )
            run_one(app.state.database, app.state.settings, engine_factory=lambda: engine)
            engine.content.update(late_content)
            raise EngineError("engine_index_incomplete")

        engine.on_publish = fail_after_delete
        run_one(app.state.database, app.state.settings, engine_factory=lambda: engine)
        engine.on_publish = None
        for _ in range(4):
            run_one(app.state.database, app.state.settings, engine_factory=lambda: engine)
        assert engine.content == {}
