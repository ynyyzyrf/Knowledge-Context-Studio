"""Opt-in real engine/vector API acceptance; staging uses an explicit deterministic fixture."""

import pytest
from fastapi.testclient import TestClient
from test_publication import approved

from kcs.engine import OpenViking, subject_uri
from kcs.publication import run_one


def test_real_vector_publication_context_edit_delete(app, request):
    if not request.config.getoption("--live-model"):
        pytest.skip("requires configured private engine and billed embedding calls")
    s = app.state.settings
    with TestClient(app) as admin, TestClient(app) as machine:
        base, agent, subject, message, memory = approved(app, admin, machine)
        root = subject_uri(base.split("/")[-1], agent["id"], subject["id"])
        endpoint = base + f"/memories/{memory['id']}"
        query = {"subject_id": subject["id"], "query": "Which beverage does this person prefer?"}
        try:
            assert run_one(app.state.database, s)
            response = machine.post("/v1/context", json=query)
            assert response.status_code == 200, response.text
            assert response.json()["memories"][0]["source_message_ids"] == [message["id"]]
            assert "jasmine tea" in response.json()["context"]
            assert (
                admin.patch(
                    endpoint,
                    json={"expected_version": 1, "content": "Prefers green tea", "reason": "Correction"},
                ).status_code
                == 202
            )
            assert machine.get(f"/v1/subjects/{subject['id']}/memories").json()["items"] == []
            for _ in range(3):
                run_one(app.state.database, s)
            result = machine.post("/v1/context", json=query).json()
            assert result["memories"][0]["version"] == 2
            assert "jasmine" not in result["context"] and "green tea" in result["context"]
            assert (
                admin.post(
                    endpoint + "/delete", json={"expected_version": 2, "reason": "Acceptance cleanup"}
                ).status_code
                == 202
            )
            for _ in range(3):
                run_one(app.state.database, s)
            assert machine.post("/v1/context", json=query).json()["memories"] == []
            with OpenViking(s) as engine:
                assert engine.find(root, "preferred beverage", 10) == []
        finally:
            with OpenViking(s) as engine:
                for version in (1, 2, 3):
                    engine.delete(f"{root}/{memory['id']}/v{version}.md")
