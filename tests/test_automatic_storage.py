"""Automatic storage of submitted content; no conversation collection."""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from test_documents import setup
from test_jobs import submitted
from test_personal_context import enable, grant, item, paths
from test_publication import Engine

from kcs.jobs import run_one
from kcs.model_service import ChatResult
from kcs.models import ConversationMessage, MemoryProjection, MemoryRecord
from kcs.publication import run_one as publish_one


def policy(admin, tenant, agent, mode="automatic"):
    response = admin.put(f"/v1/tenants/{tenant}/agents/{agent['id']}/memory-policy", json={"mode": mode})
    assert response.status_code == 200, response.text
    assert response.json()["memory_policy"] == mode


def extract(app, source, content="Prefers jasmine tea"):
    return run_one(
        app.state.database,
        app.state.settings,
        complete_chat=lambda _: ChatResult(
            json.dumps({"memories": [{"content": content, "source_message_ids": [source]}]}), 10, 5
        ),
    )


def result(machine, job):
    response = machine.get(f"/v1/jobs/{job['id']}")
    assert response.status_code == 200, response.text
    return response.json()["result"]


def test_policy_is_admin_only_and_preserves_manual_default(app):
    with TestClient(app) as admin, TestClient(app) as machine:
        tenant, agent, _, _, _, _ = submitted(admin, machine)
        assert machine.get("/v1/agent/me").json()["memory_policy"] == "manual"
        endpoint = f"/v1/tenants/{tenant}/agents/{agent['id']}/memory-policy"
        assert machine.put(endpoint, json={"mode": "automatic"}).status_code in (401, 403)
        policy(admin, tenant, agent)
        assert machine.get("/v1/agent/me").json()["memory_policy"] == "automatic"
        assert admin.put(endpoint, json={"mode": "anything"}).status_code == 422
        assert admin.put(endpoint.replace(tenant, "foreign"), json={"mode": "manual"}).status_code == 404


def test_automatic_creation_result_and_publication(app):
    with TestClient(app) as admin, TestClient(app) as machine:
        tenant, agent, subject, _, message, job = submitted(admin, machine)
        policy(admin, tenant, agent)
        extract(app, message["id"])
        outcome = result(machine, job)
        assert outcome["pipeline_state"] == "indexing"
        assert outcome["counts"]["created"] == 1
        row = outcome["items"][0]
        assert row["content"] == "Prefers jasmine tea"
        assert row["source_message_ids"] == [message["id"]]
        assert row["publication"]["state"] == "pending"
        assert row["memory_id"]
        engine = Engine()
        assert publish_one(app.state.database, app.state.settings, engine_factory=lambda: engine)
        assert result(machine, job)["pipeline_state"] == "ready"
        memories = machine.get(f"/v1/subjects/{subject['id']}/memories").json()["items"]
        assert len(memories) == 1 and memories[0]["id"] == row["memory_id"]
        assert admin.get(f"/v1/tenants/{tenant}/jobs").json()["items"][0]["agent_id"] == agent["id"]


def test_empty_and_manual_results_are_explicit(app):
    with TestClient(app) as admin, TestClient(app) as machine:
        _, _, _, session, message, job = submitted(admin, machine)
        extract(app, message["id"])
        assert result(machine, job)["counts"]["review_required"] == 1
        assert result(machine, job)["pipeline_state"] == "review_required"
        machine.post(
            f"/v1/sessions/{session['id']}/messages",
            json={"message_id": "two", "role": "user", "content": "Hi"},
        )
        new = machine.post(f"/v1/sessions/{session['id']}/commit", json={"idempotency_key": "two"}).json()
        run_one(
            app.state.database,
            app.state.settings,
            complete_chat=lambda _: ChatResult('{"memories":[]}', 1, 1),
        )
        empty = result(machine, new)
        assert empty["reason"] == "no_durable_facts"
        assert empty["pipeline_state"] == "no_changes" and empty["items"] == []


def test_automatic_dedup_and_assistant_sources(app):
    with TestClient(app) as admin, TestClient(app) as machine:
        tenant, agent, _, session, message, _job = submitted(admin, machine)
        policy(admin, tenant, agent)
        extract(app, message["id"])
        machine.post(
            f"/v1/sessions/{session['id']}/messages",
            json={"message_id": "two", "role": "assistant", "content": "Prefers jasmine tea"},
        )
        second = machine.post(f"/v1/sessions/{session['id']}/commit", json={"idempotency_key": "two"}).json()
        extract(app, message["id"], "  Prefers   jasmine tea  ")
        assert result(machine, second)["counts"]["deduplicated"] == 1
        with app.state.database.sessions() as db:
            assert db.scalar(select(func.count()).select_from(MemoryRecord)) == 1
            assistant = db.scalar(
                select(ConversationMessage.id).where(ConversationMessage.role == "assistant")
            )
        machine.post(
            f"/v1/sessions/{session['id']}/messages",
            json={"message_id": "three", "role": "user", "content": "Thanks"},
        )
        third = machine.post(f"/v1/sessions/{session['id']}/commit", json={"idempotency_key": "three"}).json()
        extract(app, assistant, "Assistant claim")
        assert result(machine, third)["items"][0]["reason"] == "user_source_required"


def test_result_tracks_publication_failure_and_deletion(app):
    with TestClient(app) as admin, TestClient(app) as machine:
        tenant, agent, _, _, message, job = submitted(admin, machine)
        policy(admin, tenant, agent)
        extract(app, message["id"])
        memory_id = result(machine, job)["items"][0]["memory_id"]
        with app.state.database.sessions.begin() as db:
            projection = db.scalar(select(MemoryProjection).where(MemoryProjection.memory_id == memory_id))
            projection.state, projection.error_code = "failed", "engine_unavailable"
        assert result(machine, job)["pipeline_state"] == "failed"
        assert result(machine, job)["items"][0]["publication"]["error_code"] == "engine_unavailable"
        deleted = admin.post(
            f"/v1/tenants/{tenant}/memories/{memory_id}/delete",
            json={"expected_version": 1, "reason": "remove"},
        )
        assert deleted.status_code == 202
        assert "Prefers jasmine" not in json.dumps(result(machine, job))


def test_policy_is_rechecked_after_model_call(app):
    with TestClient(app) as admin, TestClient(app) as machine:
        tenant, agent, _, _, message, job = submitted(admin, machine)
        policy(admin, tenant, agent)

        def disable(_):
            policy(admin, tenant, agent, "manual")
            return ChatResult(
                json.dumps({"memories": [{"content": "Tea", "source_message_ids": [message["id"]]}]}), 1, 1
            )

        run_one(app.state.database, app.state.settings, complete_chat=disable)
        assert result(machine, job)["counts"]["review_required"] == 1


@pytest.mark.parametrize("action", ["delete", "disable"])
def test_old_source_cannot_automatically_resurrect_removed_memory(app, action):
    with TestClient(app) as admin, TestClient(app) as machine:
        tenant, agent, _, session, message, job = submitted(admin, machine)
        policy(admin, tenant, agent)
        extract(app, message["id"])
        memory_id = result(machine, job)["items"][0]["memory_id"]
        assert (
            admin.post(
                f"/v1/tenants/{tenant}/memories/{memory_id}/{action}",
                json={"expected_version": 1, "reason": "owner removed"},
            ).status_code
            == 202
        )
        machine.post(
            f"/v1/sessions/{session['id']}/messages",
            json={"message_id": "later", "role": "user", "content": "Thanks"},
        )
        second = machine.post(
            f"/v1/sessions/{session['id']}/commit", json={"idempotency_key": "later"}
        ).json()
        extract(app, message["id"])
        outcome = result(machine, second)
        assert outcome["counts"]["created"] == 0
        assert outcome["items"][0]["reason"] == "source_previously_removed"
        assert outcome["items"][0]["content"] == ""
        with app.state.database.sessions() as db:
            assert db.scalar(select(func.count()).select_from(MemoryRecord)) == 1


def test_personal_owner_opt_in_preserves_full_content_and_write_only_receipt(app):
    with TestClient(app) as admin, TestClient(app) as machine:
        _, agent, _, space, base = setup(admin, machine)
        human, api = paths(base, space, "memories")
        grant(admin, human, agent)
        assert item(machine, api, "manual")["status"] == "pending"
        endpoint = human + "/agent-access/" + agent["id"]
        assert (
            admin.put(endpoint, json={"can_read": True, "can_write": True, "auto_store": True}).status_code
            == 200
        )
        content = "Complete first paragraph.\n\nComplete second paragraph with all details."
        row = item(machine, api, "automatic", content=content)
        assert row["status"] == "active" and row["content"] == content
        assert row["storage"]["outcome"] == "created"
        assert row["indexing"]["state"] == "pending"
        assert machine.get(api + "/entries/" + row["id"]).json()["content"] == content
        enable(admin, human, row, content="Owner's private correction")
        assert (
            admin.put(endpoint, json={"can_read": False, "can_write": True, "auto_store": True}).status_code
            == 200
        )
        replay = item(machine, api, "automatic", content=content)
        assert replay["replayed"] and "content" not in replay
        assert replay["storage"]["outcome"] == "replayed"
        assert (
            admin.put(endpoint, json={"can_read": True, "can_write": False, "auto_store": True}).status_code
            == 422
        )
        skills, _ = paths(base, space, "skills")
        assert (
            admin.put(
                skills + "/agent-access/" + agent["id"],
                json={"can_read": True, "can_write": True, "auto_store": True},
            ).status_code
            == 422
        )
