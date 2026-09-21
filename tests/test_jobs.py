import json

import pytest
from fastapi.testclient import TestClient
from test_agents_spaces import admin_login, create, setup_agent


def submitted(admin, machine):
    tenant = admin_login(admin)
    agent, subject, credential = setup_agent(admin, tenant)
    machine.headers["Authorization"] = "Bearer " + credential["token"]
    session = create(machine, "/v1/sessions", {"subject_id": subject["id"], "idempotency_key": "s"})
    message = create(
        machine,
        f"/v1/sessions/{session['id']}/messages",
        {"message_id": "m1", "role": "user", "content": "I prefer jasmine tea."},
    )
    response = machine.post(f"/v1/sessions/{session['id']}/commit", json={"idempotency_key": "c1"})
    assert response.status_code == 202, response.text
    return tenant, agent, subject, session, message, response.json()


def test_commit_is_durable_deduplicated_and_snapshot_bound(app):
    from kcs.database import Database
    from kcs.models import BackgroundJob

    with TestClient(app) as admin, TestClient(app) as machine:
        _, _, _, session, _, job = submitted(admin, machine)
        endpoint = f"/v1/sessions/{session['id']}/commit"
        assert machine.post(endpoint, json={"idempotency_key": "c1"}).json()["id"] == job["id"]
        assert machine.post(endpoint, json={"idempotency_key": "alternate"}).json()["id"] == job["id"]
        create(
            machine,
            f"/v1/sessions/{session['id']}/messages",
            {"message_id": "m2", "role": "user", "content": "New message"},
        )
        assert machine.post(endpoint, json={"idempotency_key": "alternate"}).json()["id"] == job["id"]
        newer = machine.post(endpoint, json={"idempotency_key": "new"}).json()
        assert newer["id"] != job["id"] and newer["through_sequence"] == 2
        reopened = Database(app.state.settings.database_url)
        try:
            with reopened.sessions() as db:
                persisted = db.get(BackgroundJob, job["id"])
                assert persisted.state == "pending" and persisted.through_sequence == 1
        finally:
            reopened.engine.dispose()


def test_worker_stages_only_candidates_with_valid_provenance(app):
    from sqlalchemy import select

    from kcs.jobs import run_one
    from kcs.model_service import ChatResult
    from kcs.models import MemoryCandidate

    with TestClient(app) as admin, TestClient(app) as machine:
        tenant, agent, subject, _, message, job = submitted(admin, machine)

        def extract(messages):
            assert "jasmine tea" in str(messages)
            return ChatResult(
                json.dumps(
                    {"memories": [{"content": "Prefers jasmine tea", "source_message_ids": [message["id"]]}]}
                ),
                20,
                10,
            )

        assert run_one(app.state.database, app.state.settings, complete_chat=extract)
        status = machine.get(f"/v1/jobs/{job['id']}")
        assert status.status_code == 200 and status.json()["state"] == "succeeded"
        with app.state.database.sessions() as db:
            candidates = list(db.scalars(select(MemoryCandidate)))
            assert len(candidates) == 1 and candidates[0].status == "candidate"
            assert (candidates[0].tenant_id, candidates[0].agent_id, candidates[0].subject_id) == (
                tenant,
                agent["id"],
                subject["id"],
            )
            assert candidates[0].source_message_ids == [message["id"]]
        assert run_one(app.state.database, app.state.settings, complete_chat=extract) is False


@pytest.mark.parametrize(
    "content", ["not json", '{"memories":[{"content":"x","source_message_ids":["foreign"]}]}']
)
def test_invalid_model_output_fails_without_publishing_candidates(app, content):
    from sqlalchemy import func, select

    from kcs.jobs import run_one
    from kcs.model_service import ChatResult
    from kcs.models import MemoryCandidate

    with TestClient(app) as admin, TestClient(app) as machine:
        _, _, _, _, _, job = submitted(admin, machine)
        run_one(
            app.state.database, app.state.settings, complete_chat=lambda messages: ChatResult(content, 1, 1)
        )
        result = machine.get(f"/v1/jobs/{job['id']}").json()
        assert result["state"] == "failed" and result["error_code"] == "extraction_invalid_response"
        with app.state.database.sessions() as db:
            assert db.scalar(select(func.count()).select_from(MemoryCandidate)) == 0


def test_expired_worker_lease_is_reclaimed_and_stale_completion_rejected(app):
    from sqlalchemy import update

    from kcs.jobs import claim, complete
    from kcs.models import BackgroundJob

    with TestClient(app) as admin, TestClient(app) as machine:
        _, _, _, _, _, job = submitted(admin, machine)
        first = claim(app.state.database, lease_seconds=60)
        assert first.id == job["id"]
        assert claim(app.state.database, lease_seconds=60) is None
        with app.state.database.sessions.begin() as db:
            db.execute(update(BackgroundJob).where(BackgroundJob.id == first.id).values(lease_until=0))
        second = claim(app.state.database, lease_seconds=60)
        assert second.id == first.id and second.lease_token != first.lease_token
        assert complete(app.state.database, first, [], None, None) is False
        assert complete(app.state.database, second, [], 3, 2) is True
        assert machine.get(f"/v1/jobs/{job['id']}").json()["attempt"] == 2


def test_model_error_retry_and_subject_revocation(app):
    from sqlalchemy import update

    from kcs.jobs import run_one
    from kcs.model_service import ModelServiceError
    from kcs.models import BackgroundJob

    with TestClient(app) as admin, TestClient(app) as machine:
        tenant, agent, subject, _, _, job = submitted(admin, machine)

        def unavailable(messages):
            raise ModelServiceError("model_rate_limited")

        run_one(app.state.database, app.state.settings, complete_chat=unavailable)
        assert machine.get(f"/v1/jobs/{job['id']}").json()["state"] == "retry"
        with app.state.database.sessions.begin() as db:
            db.execute(update(BackgroundJob).where(BackgroundJob.id == job["id"]).values(available_at=0))
        admin.patch(
            f"/v1/tenants/{tenant}/agents/{agent['id']}/subjects/{subject['id']}", json={"active": False}
        )
        run_one(
            app.state.database,
            app.state.settings,
            complete_chat=lambda messages: pytest.fail("Must not call model"),
        )
        assert machine.get(f"/v1/jobs/{job['id']}").status_code == 404
        with app.state.database.sessions() as db:
            row = db.get(BackgroundJob, job["id"])
            assert row.state == "failed" and row.error_code == "authorization_revoked"


def test_revocation_during_model_call_discards_result(app):
    from sqlalchemy import func, select

    from kcs.jobs import run_one
    from kcs.model_service import ChatResult
    from kcs.models import BackgroundJob, MemoryCandidate

    with TestClient(app) as admin, TestClient(app) as machine:
        tenant, agent, subject, _, message, job = submitted(admin, machine)

        def revoke_then_return(messages):
            response = admin.patch(
                f"/v1/tenants/{tenant}/agents/{agent['id']}/subjects/{subject['id']}", json={"active": False}
            )
            assert response.status_code == 200
            return ChatResult(
                json.dumps({"memories": [{"content": "Tea", "source_message_ids": [message["id"]]}]}), 3, 3
            )

        run_one(app.state.database, app.state.settings, complete_chat=revoke_then_return)
        with app.state.database.sessions() as db:
            assert db.get(BackgroundJob, job["id"]).error_code == "authorization_revoked"
            assert db.scalar(select(func.count()).select_from(MemoryCandidate)) == 0


def test_job_access_does_not_leak_other_agent_or_subject(app):
    with TestClient(app) as admin, TestClient(app) as machine, TestClient(app) as other:
        tenant, agent, _, _, _, job = submitted(admin, machine)
        _, _, credential = setup_agent(admin, tenant)
        other.headers["Authorization"] = "Bearer " + credential["token"]
        assert other.get(f"/v1/jobs/{job['id']}").status_code == 404
        assert other.post(f"/v1/jobs/{job['id']}/retry").status_code == 404
        base = f"/v1/tenants/{tenant}/agents/{agent['id']}"
        subject_b = create(admin, base + "/subjects", {"name": "B"})
        limited = create(admin, base + "/credentials", {"subject_ids": [subject_b["id"]]})
        other.headers["Authorization"] = "Bearer " + limited["token"]
        assert other.get(f"/v1/jobs/{job['id']}").status_code == 404


def test_exhausted_abandoned_job_and_explicit_retry(app):
    from kcs.jobs import claim
    from kcs.models import BackgroundJob

    with TestClient(app) as admin, TestClient(app) as machine:
        _, _, _, _, _, job = submitted(admin, machine)
        with app.state.database.sessions.begin() as db:
            row = db.get(BackgroundJob, job["id"])
            row.state, row.attempt, row.lease_until = "running", 3, 0
        assert claim(app.state.database) is None
        failed = machine.get(f"/v1/jobs/{job['id']}").json()
        assert failed["state"] == "failed" and failed["error_code"] == "worker_lease_exhausted"
        assert machine.post(f"/v1/jobs/{job['id']}/retry").status_code == 202
        next_lease = claim(app.state.database)
        assert next_lease.id == job["id"]
