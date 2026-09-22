from fastapi.testclient import TestClient
from test_memory_governance import staged


def test_context_does_not_expose_candidates_or_pending_memories(app):
    with TestClient(app) as admin, TestClient(app) as machine:
        tenant, _, subject, _, candidate = staged(app, admin, machine)
        endpoint = f"/v1/subjects/{subject['id']}/memories"
        response = machine.get(endpoint)
        assert response.status_code == 200
        assert response.json()["items"] == []
        admin.post(f"/v1/tenants/{tenant}/candidates/{candidate}/approve", json={"expected_version": 1})
        assert machine.get(endpoint).json()["items"] == []
        assert machine.get("/v1/subjects/foreign/memories").status_code == 404
        assert admin.get(endpoint).status_code == 401


def test_context_rejects_caller_supplied_identity_and_engine_paths(app):
    with TestClient(app) as admin, TestClient(app) as machine:
        _, _, subject, _, _ = staged(app, admin, machine)
        response = machine.post(
            "/v1/context",
            json={"subject_id": subject["id"], "query": "preferences", "target_uri": "viking://resources"},
        )
        assert response.status_code == 422
        response = machine.post("/v1/context", json={"subject_id": "foreign", "query": "preferences"})
        assert response.status_code == 404
