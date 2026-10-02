from fastapi.testclient import TestClient
from test_documents import setup
from test_personal_context import enable, grant, item, paths
from test_publication import Engine

from kcs.model_service import EmbeddingResult, ModelServiceError
from kcs.models import NamespaceEntry


class Embedder:
    def __init__(self, hook=None, error=False):
        self.hook, self.error, self.inputs = hook, error, []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def embed(self, texts):
        self.inputs.extend(texts)
        if self.hook:
            self.hook()
        if self.error:
            raise ModelServiceError("model_unavailable")
        return EmbeddingResult([[1.0, 0.0] for _ in texts], None)


def test_personal_index_lifecycle_and_semantic_readback(app):
    from kcs.personal_index import run_one

    engine, model = Engine(), Embedder()
    app.state.context_engine_factory = lambda: engine
    app.state.personal_model_factory = lambda: model
    with TestClient(app) as admin, TestClient(app) as machine:
        _, agent, subject, space, base = setup(admin, machine)
        human, _ = paths(base, space, "memories")
        grant(admin, human, agent)
        row = item(admin, human, title="Travel", content="I avoid flying overnight.")
        assert not run_one(app.state.database, app.state.settings, model_factory=lambda: model)
        row = enable(admin, human, row)
        assert run_one(app.state.database, app.state.settings, model_factory=lambda: model)
        assert not run_one(app.state.database, app.state.settings, model_factory=lambda: model)
        query = {"subject_id": subject["id"], "space_ids": [space["id"]], "query": "red-eye preference"}
        result = machine.post("/v1/context", json=query).json()
        assert result["personal_context"][0]["id"] == row["id"]
        assert result["personal_context_retrieval"] == "hybrid"
        # Provider failure explicitly degrades; semantic-only match must not be fabricated.
        app.state.personal_model_factory = lambda: Embedder(error=True)
        degraded = machine.post("/v1/context", json=query).json()
        assert degraded["personal_context"] == []
        assert degraded["personal_retrieval"]["degraded_reason"] == "model_unavailable"
        app.state.personal_model_factory = lambda: model
        row = enable(admin, human, row, content="New current preference")
        with app.state.database.sessions() as db:
            assert db.get(NamespaceEntry, row["id"]).embedding_vectors is None

        # A delete while the provider is running must fence out its late result.
        def erase():
            assert (
                admin.post(
                    human + "/entries/" + row["id"] + "/delete", json={"version": row["version"]}
                ).status_code
                == 200
            )

        assert run_one(app.state.database, app.state.settings, model_factory=lambda: Embedder(hook=erase))
        with app.state.database.sessions() as db:
            stored = db.get(NamespaceEntry, row["id"])
            assert stored.embedding_vectors is None and stored.content == ""
        assert machine.post("/v1/context", json=query).json()["personal_context"] == []


def test_index_retry_exhaustion_model_change_and_owner_retry(app):
    from kcs.personal_index import run_one

    with TestClient(app) as admin, TestClient(app) as machine:
        _, agent, _, space, base = setup(admin, machine)
        human, api = paths(base, space, "skills")
        grant(admin, human, agent)
        row = enable(admin, human, item(admin, human))
        for attempt in range(3):
            with app.state.database.sessions.begin() as db:
                db.get(NamespaceEntry, row["id"]).embedding_available_at = 0
            assert run_one(app.state.database, app.state.settings, model_factory=lambda: Embedder(error=True))
        assert not run_one(app.state.database, app.state.settings, model_factory=lambda: Embedder())
        response = admin.post(human + "/entries/" + row["id"] + "/reindex", json={"version": row["version"]})
        assert response.status_code == 202, response.text
        assert machine.post(api + "/entries/" + row["id"] + "/reindex", json={}).status_code == 405
        assert run_one(app.state.database, app.state.settings, model_factory=lambda: Embedder())
        app.state.settings.embedding_model = "changed-model"
        assert run_one(app.state.database, app.state.settings, model_factory=lambda: Embedder())


def test_revoke_during_query_embedding_is_rechecked(app):
    from kcs.personal_index import run_one

    app.state.context_engine_factory = lambda: Engine()
    with TestClient(app) as admin, TestClient(app) as machine:
        _, agent, subject, space, base = setup(admin, machine)
        human, _ = paths(base, space, "memories")
        grant(admin, human, agent)
        enable(admin, human, item(admin, human))
        run_one(app.state.database, app.state.settings, model_factory=lambda: Embedder())
        app.state.personal_model_factory = lambda: Embedder(
            hook=lambda: grant(admin, human, agent, read=False)
        )
        result = machine.post(
            "/v1/context",
            json={"subject_id": subject["id"], "space_ids": [space["id"]], "query": "paraphrased question"},
        )
        assert result.status_code == 200, result.text
        assert result.json()["personal_context"] == []
        assert result.json()["personal_retrieval"]["readable_count"] == 0


def test_expired_lease_and_concurrent_edit_cannot_install_old_vectors(app):
    import time

    from kcs.personal_index import claim, run_one

    with TestClient(app) as admin, TestClient(app) as machine:
        _, _, _, space, base = setup(admin, machine)
        human, _ = paths(base, space, "peers")
        row = enable(admin, human, item(admin, human))
        assert claim(app.state.database, app.state.settings)
        assert not run_one(app.state.database, app.state.settings, model_factory=lambda: Embedder())
        with app.state.database.sessions.begin() as db:
            db.get(NamespaceEntry, row["id"]).embedding_lease_until = time.time() - 1

        def edit():
            enable(admin, human, row, content="new version must not use the old embedding")

        assert run_one(app.state.database, app.state.settings, model_factory=lambda: Embedder(hook=edit))
        with app.state.database.sessions() as db:
            stored = db.get(NamespaceEntry, row["id"])
            assert stored.embedding_vectors is None and stored.version == row["version"] + 1
        assert run_one(app.state.database, app.state.settings, model_factory=lambda: Embedder())


def test_index_covers_long_content_and_owner_disabled_during_embedding(app):
    from kcs.models import Person
    from kcs.personal_index import run_one

    with TestClient(app) as admin, TestClient(app) as machine:
        _, _, _, space, base = setup(admin, machine)
        human, _ = paths(base, space, "skills")
        row = enable(admin, human, item(admin, human, content="x" * 39990 + "tail-marker"[:10]))
        model = Embedder()
        assert run_one(app.state.database, app.state.settings, model_factory=lambda: model)
        assert len(model.inputs) == 20 and model.inputs[-1].endswith("tail-marker"[:10])
        row = enable(admin, human, row, content="current content")

        def disable():
            with app.state.database.sessions.begin() as db:
                owner = db.get(NamespaceEntry, row["id"]).person_id
                db.get(Person, owner).active = False

        assert run_one(app.state.database, app.state.settings, model_factory=lambda: Embedder(hook=disable))
        with app.state.database.sessions() as db:
            assert db.get(NamespaceEntry, row["id"]).embedding_vectors is None
        assert not run_one(app.state.database, app.state.settings, model_factory=lambda: Embedder())


def test_old_model_and_cross_person_vectors_are_excluded(app):
    from test_resource_namespaces import second_user

    from kcs.personal_index import run_one

    app.state.context_engine_factory = lambda: Engine()
    with TestClient(app) as admin, TestClient(app) as machine, TestClient(app) as other:
        tenant, agent, subject, space, base = setup(admin, machine)
        second_user(app, tenant, other)
        human, _ = paths(base, space, "memories")
        grant(admin, human, agent)
        own = enable(admin, human, item(admin, human, content="only me"))
        foreign = enable(other, human, item(other, human, content="foreign secret"))
        for _ in range(2):
            assert run_one(app.state.database, app.state.settings, model_factory=lambda: Embedder())
        app.state.personal_model_factory = lambda: Embedder()
        query = {"subject_id": subject["id"], "query": "another phrasing", "space_ids": [space["id"]]}
        body = machine.post("/v1/context", json=query).json()
        assert [r["id"] for r in body["personal_context"]] == [own["id"]]
        assert foreign["id"] not in str(body)
        app.state.settings.embedding_model = "another-model"
        detail = admin.get(human + "/entries/" + own["id"]).json()
        assert detail["indexing"]["state"] == "pending"
        body = machine.post("/v1/context", json=query).json()
        assert body["personal_context"] == [] and body["personal_retrieval"]["indexed_count"] == 0


def test_edit_during_query_does_not_use_old_vector(app):
    from kcs.personal_index import run_one

    app.state.context_engine_factory = lambda: Engine()
    with TestClient(app) as admin, TestClient(app) as machine:
        _, agent, subject, space, base = setup(admin, machine)
        human, _ = paths(base, space, "memories")
        grant(admin, human, agent)
        row = enable(admin, human, item(admin, human))
        run_one(app.state.database, app.state.settings, model_factory=lambda: Embedder())
        app.state.personal_model_factory = lambda: Embedder(
            hook=lambda: enable(admin, human, row, content="unrelated updated statement")
        )
        body = machine.post(
            "/v1/context",
            json={"subject_id": subject["id"], "space_ids": [space["id"]], "query": "paraphrase"},
        ).json()
        assert body["personal_context"] == []
