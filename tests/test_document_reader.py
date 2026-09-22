from types import SimpleNamespace

from fastapi.testclient import TestClient
from test_documents import setup
from test_publication import Engine
from test_resource_namespaces import second_user

from kcs.document_parser import parse_bytes
from kcs.document_reader import complete_text, summarize
from kcs.document_worker import run_one
from kcs.models import Document


def test_reader_full_text_and_private_boundary(app, monkeypatch):
    with TestClient(app) as admin, TestClient(app) as machine, TestClient(app) as other:
        tenant, _, _, _, base = setup(admin, machine)
        second_user(app, tenant, other)
        text = ("Section content with overlap.\n" * 1500) + "UNIQUE DOCUMENT TAIL"
        doc = admin.post(base + "/documents", params={"filename": "long.txt"}, content=text.encode()).json()
        path = base + "/documents/" + doc["id"]
        assert admin.get(path + "/content").status_code == 409
        assert run_one(app.state.database, app.state.settings, engine_factory=Engine)
        assert admin.get(path).json()["has_more"]
        assert admin.get(path + "/content").json()["pages"] == [{"page": None, "content": text}]
        assert other.get(path + "/content").status_code == 404
        assert other.post(path + "/summary").status_code == 404

        def summary(settings, pages):
            assert pages[0]["content"].endswith("UNIQUE DOCUMENT TAIL")
            return "Whole document summary"

        monkeypatch.setattr("kcs.document_routes.summarize", summary)
        assert admin.post(path + "/summary").json()["summary"] == "Whole document summary"

        def delete_during_summary(settings, pages):
            with app.state.database.sessions.begin() as db:
                db.get(Document, doc["id"]).deleted = True
            return "must not be returned"

        monkeypatch.setattr("kcs.document_routes.summarize", delete_during_summary)
        assert admin.post(path + "/summary").status_code == 409
        assert admin.get(path + "/content").status_code == 410


def test_reassembly_removes_only_parser_overlap():
    text = "0123456789 abcdefghijklmnop\n" * 1000
    chunks = parse_bytes(text.encode(), ".txt")
    rows = [SimpleNamespace(number=i, **c) for i, c in enumerate(chunks)]

    class DB:
        def scalars(self, query):
            return rows

    doc = SimpleNamespace(id="test", deleted=False, filename="file.pdf", chunk_count=len(rows))
    assert complete_text(DB(), doc) == [{"page": None, "content": text.strip()}]


def test_summary_covers_all_parts(monkeypatch):
    calls = []

    class Service:
        def __init__(self, settings):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def chat(self, messages, **kwargs):
            calls.append(messages[-1]["content"])
            return SimpleNamespace(text="summary-" + str(len(calls)))

    monkeypatch.setattr("kcs.document_reader.ModelService", Service)
    text = "a" * 25000 + "END"
    assert summarize(None, [{"content": text}]) == "summary-3"
    assert "".join(calls[:2]) == text
    assert calls[2] == "summary-1\n\nsummary-2"
