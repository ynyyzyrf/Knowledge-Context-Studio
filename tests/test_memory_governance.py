import json

from fastapi.testclient import TestClient
from sqlalchemy import select
from test_jobs import submitted

from kcs.jobs import run_one
from kcs.model_service import ChatResult
from kcs.models import AuditEvent, MemoryCandidate


def staged(app, admin, machine):
    tenant, agent, subject, _, message, job = submitted(admin, machine)
    run_one(
        app.state.database,
        app.state.settings,
        complete_chat=lambda messages: ChatResult(
            json.dumps(
                {"memories": [{"content": "Prefers jasmine tea", "source_message_ids": [message["id"]]}]}
            ),
            4,
            3,
        ),
    )
    with app.state.database.sessions() as db:
        candidate = db.scalar(select(MemoryCandidate).where(MemoryCandidate.job_id == job["id"]))
        candidate_id = candidate.id
    return tenant, agent, subject, message, candidate_id


def test_approval_is_pending_publication_and_has_provenance(app):
    with TestClient(app) as admin, TestClient(app) as machine:
        tenant, agent, subject, message, candidate = staged(app, admin, machine)
        base = f"/v1/tenants/{tenant}"
        evidence = admin.get(base + f"/candidates/{candidate}/provenance")
        assert evidence.status_code == 200
        assert evidence.json()["messages"][0]["id"] == message["id"]
        response = admin.post(base + f"/candidates/{candidate}/approve", json={"expected_version": 1})
        assert response.status_code == 202, response.text
        memory = response.json()
        assert memory["status"] == "pending" and memory["version"] == 1
        assert memory["source_message_ids"] == [message["id"]]
        assert memory["publication"]["state"] == "pending"
        assert (
            admin.post(base + f"/candidates/{candidate}/approve", json={"expected_version": 1}).status_code
            == 409
        )
        cognition = admin.get(base + f"/agents/{agent['id']}/subjects/{subject['id']}/cognition")
        assert cognition.status_code == 200
        assert cognition.json()["memories"][0]["id"] == memory["id"]
        assert cognition.json()["candidates"][0]["status"] == "approved"
        evidence = admin.get(base + f"/memories/{memory['id']}/provenance")
        assert evidence.status_code == 200
        assert evidence.json()["messages"][0]["id"] == message["id"]
        assert "jasmine tea" in evidence.json()["messages"][0]["content"]


def test_edit_conflict_disable_and_delete_preserve_tombstone(app):
    from kcs.models import MemoryProjection, MemoryRevision

    with TestClient(app) as admin, TestClient(app) as machine:
        tenant, _, _, _, candidate = staged(app, admin, machine)
        base = f"/v1/tenants/{tenant}"
        memory = admin.post(base + f"/candidates/{candidate}/approve", json={"expected_version": 1}).json()
        endpoint = base + f"/memories/{memory['id']}"
        edited = admin.patch(
            endpoint, json={"expected_version": 1, "content": "Prefers green tea", "reason": "Correction"}
        )
        assert edited.status_code == 202, edited.text
        assert edited.json()["version"] == 2 and edited.json()["status"] == "pending"
        assert (
            admin.patch(
                endpoint, json={"expected_version": 1, "content": "Stale", "reason": "Old tab"}
            ).status_code
            == 409
        )
        disabled = admin.post(endpoint + "/disable", json={"expected_version": 2, "reason": "Stop retrieval"})
        assert disabled.status_code == 202 and disabled.json()["status"] == "disabled"
        deleted = admin.post(endpoint + "/delete", json={"expected_version": 3, "reason": "Remove fact"})
        assert deleted.status_code == 202 and deleted.json()["status"] == "deleted"
        assert deleted.json()["content"] is None
        assert (
            admin.patch(
                endpoint, json={"expected_version": 4, "content": "Revive", "reason": "No"}
            ).status_code
            == 409
        )
        with app.state.database.sessions() as db:
            revisions = list(
                db.scalars(select(MemoryRevision).where(MemoryRevision.memory_id == memory["id"]))
            )
            assert len(revisions) == 4 and all(row.content is None for row in revisions)
            projections = list(
                db.scalars(select(MemoryProjection).where(MemoryProjection.memory_id == memory["id"]))
            )
            assert projections[-1].kind == "delete" or any(row.kind == "delete" for row in projections)
            assert db.get(MemoryCandidate, candidate).content == ""


def test_cognition_and_approval_require_tenant_admin(app):
    from test_agents_spaces import create

    with TestClient(app) as admin, TestClient(app) as machine, TestClient(app) as viewer:
        tenant, agent, subject, _, candidate = staged(app, admin, machine)
        base = f"/v1/tenants/{tenant}"
        create(
            admin,
            base + "/members",
            {"email": "viewer@example.test", "password": "viewer-long-password", "role": "viewer"},
        )
        data = viewer.post(
            "/v1/auth/login", json={"email": "viewer@example.test", "password": "viewer-long-password"}
        ).json()
        viewer.headers["X-CSRF-Token"] = data["csrf_token"]
        endpoint = base + f"/agents/{agent['id']}/subjects/{subject['id']}/cognition"
        assert viewer.get(endpoint).status_code == 403
        assert viewer.get(base + f"/candidates/{candidate}/provenance").status_code == 403
        assert admin.get(f"/v1/tenants/foreign/candidates/{candidate}/provenance").status_code == 404
        assert (
            viewer.post(base + f"/candidates/{candidate}/approve", json={"expected_version": 1}).status_code
            == 403
        )
        assert (
            admin.post(
                f"/v1/tenants/foreign/candidates/{candidate}/approve", json={"expected_version": 1}
            ).status_code
            == 404
        )
        assert machine.get(endpoint).status_code == 401


def test_rejected_candidate_cannot_be_approved(app):
    with TestClient(app) as admin, TestClient(app) as machine:
        tenant, _, _, _, candidate = staged(app, admin, machine)
        endpoint = f"/v1/tenants/{tenant}/candidates/{candidate}"
        response = admin.post(
            endpoint + "/reject", json={"expected_version": 1, "reason": "Not a durable fact"}
        )
        assert response.status_code == 200
        assert response.json()["status"] == "rejected"
        with app.state.database.sessions() as db:
            event = db.scalar(
                select(AuditEvent).where(
                    AuditEvent.action == "candidate.rejected", AuditEvent.target_id == candidate
                )
            )
            assert event.details["reason"] == "Not a durable fact"
        assert admin.post(endpoint + "/approve", json={"expected_version": 2}).status_code == 409


def test_cognition_paginates_lists_independently_with_scoped_totals(app):
    with TestClient(app) as admin, TestClient(app) as machine:
        tenant, agent, subject, message, first = staged(app, admin, machine)
        base = f"/v1/tenants/{tenant}"
        with app.state.database.sessions() as db:
            original = db.get(MemoryCandidate, first)
            original.created_at = 100
            ids = [first]
            for number in range(1, 23):
                candidate = MemoryCandidate(
                    tenant_id=tenant, agent_id=agent["id"], subject_id=subject["id"],
                    job_id=original.job_id, ordinal=number, content=f"Fact {number}",
                    source_message_ids=[message["id"]], created_at=100 + number,
                )
                db.add(candidate)
                db.flush()
                ids.append(candidate.id)
            db.commit()
        for candidate_id in ids[:12]:
            response = admin.post(base + f"/candidates/{candidate_id}/approve", json={"expected_version": 1})
            assert response.status_code == 202
        # Another subject's candidate must not affect either total or page contents.
        staged(app, admin, machine)
        endpoint = base + f"/agents/{agent['id']}/subjects/{subject['id']}/cognition"
        first_page = admin.get(endpoint, params={"limit": 10}).json()
        assert first_page["candidates_total"] == 23
        assert first_page["memories_total"] == 12
        assert len(first_page["candidates"]) == len(first_page["memories"]) == 10
        second = admin.get(endpoint, params={"limit": 10, "candidates_offset": 10, "memories_offset": 0}).json()
        assert second["memories"] == first_page["memories"]
        assert not ({c["id"] for c in first_page["candidates"]} & {c["id"] for c in second["candidates"]})
        last = admin.get(endpoint, params={"limit": 10, "candidates_offset": 20, "memories_offset": 10}).json()
        assert len(last["candidates"]) == 3 and len(last["memories"]) == 2
        assert {c["id"] for page in [first_page, second, last] for c in page["candidates"]} == set(ids)
        legacy = admin.get(endpoint, params={"limit": 10, "offset": 10}).json()
        assert legacy["candidates"] == second["candidates"]
        assert legacy["memories"] == last["memories"]
        empty = admin.get(endpoint, params={"limit": 10, "offset": 30}).json()
        assert empty["candidates"] == empty["memories"] == []
        assert empty["candidates_total"] == 23 and empty["memories_total"] == 12
        assert admin.get(endpoint, params={"candidates_offset": -1}).status_code == 422
        assert admin.get(endpoint, params={"memories_offset": -1}).status_code == 422
