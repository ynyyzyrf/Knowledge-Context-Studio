from fastapi.testclient import TestClient
from test_agents_spaces import admin_login, create, setup_agent
from test_publication import Engine

from kcs.document_parser import parse_bytes
from kcs.document_worker import run_one


def upload(client, base, content=b"Project Amber support hours are 09:00 to 18:00.", name="guide.md"):
    return client.post(
        base + "/documents",
        params={"filename": name, "scope": "shared"},
        content=content,
        headers={"Content-Type": "application/octet-stream"},
    )


def test_upload_deduplicates_and_rejects_unsupported_files(app):
    with TestClient(app) as admin:
        tenant = admin_login(admin)
        space = create(admin, f"/v1/tenants/{tenant}/spaces", {"name": "Product docs"})
        base = f"/v1/tenants/{tenant}/spaces/{space['id']}"
        response = upload(admin, base)
        assert response.status_code == 202, response.text
        duplicate = upload(admin, base)
        assert duplicate.json()["id"] == response.json()["id"]
        assert upload(admin, base, b"binary", "payload.exe").status_code == 415
        assert upload(admin, base, b"", "empty.txt").status_code == 422
        assert len(admin.get(base + "/documents").json()["items"]) == 1


def test_dedup_keeps_pdf_and_text_parser_identities_separate(app):
    with TestClient(app) as admin, TestClient(app) as machine:
        _, _, _, _, base = setup(admin, machine)
        failed_pdf = upload(admin, base, b"plain text", "wrong.pdf").json()
        corrected = upload(admin, base, b"plain text", "correct.txt").json()
        assert corrected["id"] != failed_pdf["id"]


def test_parser_process_has_enforced_memory_ceiling():
    import subprocess
    import sys

    probe = "from kcs.parser_limits import limit_memory\nhandle=limit_memory(128*1024*1024)\ntry:\n bytearray(256*1024*1024)\nexcept MemoryError:\n print('LIMIT_ENFORCED')\n"
    result = subprocess.run([sys.executable, "-c", probe], capture_output=True, timeout=10, check=True)
    assert result.stdout.strip() == b"LIMIT_ENFORCED"


def test_transient_index_failure_exhausts_then_manual_retry_and_cleanup_recovers(app):
    from kcs.engine import EngineError
    from kcs.models import Document

    class Unavailable(Engine):
        def publish(self, uri, content):
            super().publish(uri, content)
            raise EngineError("engine_unavailable")

        def delete(self, uri):
            raise EngineError("engine_unavailable")

    engine = Unavailable()
    app.state.context_engine_factory = lambda: engine
    with TestClient(app) as admin, TestClient(app) as machine:
        _, _, subject, _, base = setup(admin, machine)
        doc = upload(admin, base).json()
        path = base + "/documents/" + doc["id"]
        query = {"subject_id": subject["id"], "query": "support"}

        def due():
            with app.state.database.sessions.begin() as db:
                db.get(Document, doc["id"]).available_at = 0

        for expected in ("retry", "retry", "failed"):
            due()
            assert run_one(app.state.database, app.state.settings, engine_factory=lambda: engine)
            assert admin.get(path).json()["state"] == expected
            assert machine.post("/v1/context", json=query).json()["documents"] == []
        assert admin.post(path + "/retry").status_code == 202
        healthy = Engine()
        healthy.content = engine.content
        assert run_one(app.state.database, app.state.settings, engine_factory=lambda: healthy)
        assert admin.get(path).json()["state"] == "succeeded"
        assert admin.delete(path).status_code == 202
        for _ in range(4):
            due()
            assert run_one(app.state.database, app.state.settings, engine_factory=lambda: engine)
            assert admin.get(path).json()["state"] == "retry"
            assert machine.post("/v1/context", json=query).json()["documents"] == []
        due()
        assert run_one(app.state.database, app.state.settings, engine_factory=lambda: healthy)
        assert not healthy.content


def setup(admin, machine):
    tenant = admin_login(admin)
    agent, subject, credential = setup_agent(admin, tenant)
    machine.headers["Authorization"] = "Bearer " + credential["token"]
    space = create(admin, f"/v1/tenants/{tenant}/spaces", {"name": "Knowledge"})
    base = f"/v1/tenants/{tenant}/spaces/{space['id']}"
    assert admin.put(base + f"/agents/{agent['id']}", json={"active": True}).status_code == 200
    return tenant, agent, subject, space, base


def test_index_readback_grant_recheck_and_delete(app):
    engine = Engine()
    app.state.context_engine_factory = lambda: engine
    with TestClient(app) as admin, TestClient(app) as machine:
        _, agent, subject, space, base = setup(admin, machine)
        doc = upload(admin, base).json()
        query = {"subject_id": subject["id"], "query": "When is support available?"}
        assert machine.post("/v1/context", json=query).json()["documents"] == []
        assert run_one(app.state.database, app.state.settings, engine_factory=lambda: engine)
        found = machine.post("/v1/context", json=query).json()
        assert found["documents"][0]["id"] == doc["id"]
        assert "09:00" in found["context"]
        # Engine deliberately returns every URI; product space grants still apply.
        other = create(admin, base.rsplit("/spaces/", 1)[0] + "/spaces", {"name": "Private"})
        secret_base = base.rsplit("/", 1)[0] + "/" + other["id"]
        secret = upload(admin, secret_base, b"Private launch secret").json()
        run_one(app.state.database, app.state.settings, engine_factory=lambda: engine)
        assert secret["id"] not in str(machine.post("/v1/context", json=query).json())
        engine.on_find = lambda: admin.put(base + f"/agents/{agent['id']}", json={"active": False})
        assert machine.post("/v1/context", json=query).json()["documents"] == []
        engine.on_find = None
        assert machine.post("/v1/context", json={**query, "space_ids": [space["id"]]}).status_code == 404
        admin.put(base + f"/agents/{agent['id']}", json={"active": True})
        assert admin.delete(base + "/documents/" + doc["id"]).status_code == 202
        assert machine.post("/v1/context", json=query).json()["documents"] == []
        run_one(app.state.database, app.state.settings, engine_factory=lambda: engine)
        assert all(doc["id"] not in uri for uri in engine.content)
        preview = admin.get(base + "/documents/" + doc["id"]).json()
        assert preview["chunks"] == [] and preview["deleted"]


def test_delete_during_index_is_fenced_and_cleaned(app):
    engine = Engine()
    with TestClient(app) as admin, TestClient(app) as machine:
        _, _, _, _, base = setup(admin, machine)
        doc = upload(admin, base).json()
        engine.on_publish = lambda: admin.delete(base + "/documents/" + doc["id"])
        run_one(app.state.database, app.state.settings, engine_factory=lambda: engine)
        engine.on_publish = None
        run_one(app.state.database, app.state.settings, engine_factory=lambda: engine)
        assert engine.content == {}
        assert admin.get(base + "/documents/" + doc["id"]).json()["state"] == "succeeded"


def test_parser_rejects_scanned_pdf_binary_and_limits():
    import io

    import pytest
    from pypdf import PdfWriter

    from kcs.document_parser import ParseError

    pdf = PdfWriter()
    pdf.add_blank_page(300, 300)
    data = io.BytesIO()
    pdf.write(data)
    with pytest.raises(ParseError, match="ocr_required"):
        parse_bytes(data.getvalue(), ".pdf")
    with pytest.raises(ParseError, match="requires_utf8"):
        parse_bytes(b"\xff\xfe", ".txt")
    with pytest.raises(ParseError, match="text_limit"):
        parse_bytes(b"a" * 200001, ".md")
    text = "支援服務\n" * 600
    chunks = parse_bytes(text.encode(), ".md")
    assert len(chunks) > 1 and chunks[0]["content"][-200:] == chunks[1]["content"][:200]


def text_pdf(text="Project Amber support closes at 18:00."):
    import io

    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(600, 800)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 50 750 Td ({text}) Tj ET".encode())
    page[NameObject("/Contents")] = stream
    result = io.BytesIO()
    writer.write(result)
    return result.getvalue()


def test_text_pdf_extracts_page_source_and_failure_never_publishes(app):
    engine = Engine()
    with TestClient(app) as admin, TestClient(app) as machine:
        _, _, _, _, base = setup(admin, machine)
        pdf = upload(admin, base, text_pdf(), "hours.pdf").json()
        run_one(app.state.database, app.state.settings, engine_factory=lambda: engine)
        preview = admin.get(base + "/documents/" + pdf["id"]).json()
        assert preview["state"] == "succeeded"
        assert preview["chunks"][0]["page"] == 1 and "18:00" in preview["chunks"][0]["content"]
        bad = upload(admin, base, b"not a pdf", "bad.pdf").json()
        run_one(app.state.database, app.state.settings, engine_factory=lambda: engine)
        preview = admin.get(base + "/documents/" + bad["id"]).json()
        assert preview["state"] == "failed" and preview["error_code"] == "document_invalid_pdf"
        assert all(bad["id"] not in uri for uri in engine.content)


def test_upload_requires_editor_scope_and_size_bound(app):
    from sqlalchemy import select

    from kcs.models import Membership, Person, PersonSpaceGrant

    with TestClient(app) as admin, TestClient(app) as machine:
        tenant, _, _, space, base = setup(admin, machine)
        assert upload(machine, base).status_code == 401
        assert upload(admin, base, b"x" * (10 * 1024 * 1024 + 1)).status_code == 413
        assert upload(admin, base, b"x", "../escape.md").status_code == 422
        with app.state.database.sessions.begin() as db:
            person = db.scalar(select(Person).where(Person.email == "admin@example.test"))
            db.get(Membership, (tenant, person.id)).role = "viewer"
            db.add(
                PersonSpaceGrant(tenant_id=tenant, space_id=space["id"], person_id=person.id, level="viewer")
            )
        assert admin.get(base + "/documents").status_code == 200
        assert upload(admin, base).status_code == 403
        with app.state.database.sessions.begin() as db:
            db.get(Membership, (tenant, person.id)).role = "editor"
            db.get(PersonSpaceGrant, (tenant, space["id"], person.id)).level = "editor"
        assert upload(admin, base).status_code == 202


def test_expired_index_lease_can_be_recovered_and_late_finish_cannot_commit(app):
    import time

    from kcs.document_worker import claim, finish
    from kcs.models import Document

    engine = Engine()
    with TestClient(app) as admin, TestClient(app) as machine:
        _, _, _, _, base = setup(admin, machine)
        doc = upload(admin, base).json()
        old = claim(app.state.database, 60)
        assert claim(app.state.database, 60) is None
        with app.state.database.sessions.begin() as db:
            db.get(Document, doc["id"]).lease_until = time.time() - 1
        assert run_one(app.state.database, app.state.settings, engine_factory=lambda: engine)
        finish(app.state.database, old, "engine_unavailable")
        assert admin.get(base + "/documents/" + doc["id"]).json()["state"] == "succeeded"
