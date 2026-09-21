import subprocess
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_jobs import submitted

from kcs.jobs import claim, complete
from kcs.models import BackgroundJob, MemoryCandidate


def test_process_exit_after_claim_recovers_without_duplicate_completion(app):
    if app.state.database.engine.dialect.name != "postgresql":
        pytest.skip("Requires shared PostgreSQL schema for separate process")
    with TestClient(app) as admin, TestClient(app) as machine:
        _, _, _, _, _, job = submitted(admin, machine)
        script = (
            "import os; from kcs.config import Settings; from kcs.database import Database; "
            "from kcs.jobs import claim; db=Database(Settings().database_url); "
            "assert claim(db,lease_seconds=60); os._exit(73)"
        )
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, timeout=20, check=False)
        assert result.returncode == 73
        with app.state.database.sessions.begin() as db:
            row = db.get(BackgroundJob, job["id"])
            assert row.state == "running" and row.attempt == 1
            # Advance the persisted lease deadline; do not sleep through a minute.
            row.lease_until = 0
        reclaimed = claim(app.state.database)
        assert reclaimed.id == job["id"]
        assert complete(app.state.database, reclaimed, [], 0, 0)
        assert machine.get(f"/v1/jobs/{job['id']}").json()["state"] == "succeeded"


def test_real_model_worker_process_stages_synthetic_fact(app, request):
    if not request.config.getoption("--live-model"):
        pytest.skip("Real model calls require --live-model")
    if app.state.database.engine.dialect.name != "postgresql":
        pytest.skip("Requires --postgres")
    with TestClient(app) as admin, TestClient(app) as machine:
        _, _, _, _, message, job = submitted(admin, machine)
        result = subprocess.run(
            [sys.executable, "-m", "kcs.worker", "--once"], capture_output=True, timeout=120, check=False
        )
        assert result.returncode == 0, "Worker process failed; inspect sanitized status"
        status = machine.get(f"/v1/jobs/{job['id']}").json()
        assert status["state"] == "succeeded", status["error_code"]
        with app.state.database.sessions() as db:
            candidates = list(db.scalars(select(MemoryCandidate).where(MemoryCandidate.job_id == job["id"])))
            assert candidates, "Expected a durable preference from synthetic source"
            assert all(candidate.status == "candidate" for candidate in candidates)
            assert all(set(candidate.source_message_ids) == {message["id"]} for candidate in candidates)
            assert any(
                "tea" in candidate.content.lower() or "茶" in candidate.content for candidate in candidates
            )
