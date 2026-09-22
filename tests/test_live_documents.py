import pytest
from fastapi.testclient import TestClient
from test_documents import setup, text_pdf, upload

from kcs.document_worker import run_one
from kcs.engine import OpenViking, document_uri
from kcs.models import Document


def test_real_document_formats_index_context_and_delete(app, request):
    if not request.config.getoption("live_model"):
        pytest.skip("requires real private engine and embedding service")
    with TestClient(app) as admin, TestClient(app) as machine:
        _, _, subject, _, base = setup(admin, machine)
        docs = []
        try:
            for name, body in [
                ("guide.md", b"# Amber\nSupport is available until 18:00."),
                ("notes.txt", b"For Amber urgent requests use extension 6318."),
                ("hours.pdf", text_pdf()),
            ]:
                d = upload(admin, base, body, name).json()
                docs.append(d)
                assert run_one(app.state.database, app.state.settings)
                detail = admin.get(base + "/documents/" + d["id"]).json()
                assert detail["state"] == "succeeded", detail
            r = machine.post(
                "/v1/context",
                json={"subject_id": subject["id"], "query": "When does Amber support close?", "limit": 10},
            )
            assert r.status_code == 200, r.text
            assert r.json()["documents"] and "18:00" in r.json()["context"]
            assert {d["filename"] for d in r.json()["documents"]} >= {"hours.pdf", "guide.md"}
            for d in docs:
                assert admin.delete(base + "/documents/" + d["id"]).status_code == 202
                run_one(app.state.database, app.state.settings)
            r = machine.post("/v1/context", json={"subject_id": subject["id"], "query": "Amber support"})
            assert r.json()["documents"] == []
        finally:
            with app.state.database.sessions() as db, OpenViking(app.state.settings) as engine:
                for d in docs:
                    row = db.get(Document, d["id"])
                    for number in range(row.chunk_count):
                        engine.delete(document_uri(row, number))
