from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from kcs.models import Membership


def test_two_workers_cannot_claim_same_job(app):
    if app.state.database.engine.dialect.name != "postgresql":
        pytest.skip("Requires PostgreSQL SKIP LOCKED")
    from test_jobs import submitted

    from kcs.jobs import claim

    with TestClient(app) as admin, TestClient(app) as machine:
        _, _, _, _, _, job = submitted(admin, machine)
        barrier = Barrier(2)

        def take():
            barrier.wait(timeout=10)
            return claim(app.state.database)

        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = pool.submit(take), pool.submit(take)
            claimed = [lease for lease in (a.result(timeout=20), b.result(timeout=20)) if lease is not None]
        assert len(claimed) == 1 and claimed[0].id == job["id"]


def test_duplicate_concurrent_messages_have_one_stored_row(app):
    if app.state.database.engine.dialect.name != "postgresql":
        pytest.skip("Requires PostgreSQL row locks")
    from test_agents_spaces import admin_login, create, setup_agent

    with TestClient(app) as admin, TestClient(app) as first, TestClient(app) as second:
        tenant = admin_login(admin)
        _, subject, credential = setup_agent(admin, tenant)
        first.headers["Authorization"] = second.headers["Authorization"] = "Bearer " + credential["token"]
        session = create(first, "/v1/sessions", {"subject_id": subject["id"], "idempotency_key": "session"})
        endpoint = f"/v1/sessions/{session['id']}/messages"
        barrier = Barrier(2)

        def append(client):
            barrier.wait(timeout=10)
            response = client.post(
                endpoint, json={"message_id": "same", "role": "user", "content": "same text"}
            )
            assert response.status_code == 201
            return response.json()["id"]

        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = pool.submit(append, first), pool.submit(append, second)
            assert a.result(timeout=20) == b.result(timeout=20)
        assert len(first.get(endpoint).json()["items"]) == 1


def test_concurrent_rotation_issues_only_one_replacement(app):
    if app.state.database.engine.dialect.name != "postgresql":
        pytest.skip("Requires PostgreSQL row locks")
    from test_agents_spaces import admin_login, setup_agent

    with TestClient(app) as first, TestClient(app) as second:
        tenant = admin_login(first)
        admin_login(second)
        agent, _, credential = setup_agent(first, tenant)
        barrier = Barrier(2)
        endpoint = f"/v1/tenants/{tenant}/agents/{agent['id']}/credentials/{credential['id']}/rotate"

        def rotate(client):
            barrier.wait(timeout=10)
            return client.post(endpoint, json={}).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = pool.submit(rotate, first), pool.submit(rotate, second)
            assert sorted([a.result(timeout=20), b.result(timeout=20)]) == [201, 409]


def test_two_admins_cannot_disable_each_other_concurrently(app):
    if app.state.database.engine.dialect.name != "postgresql":
        pytest.skip("Requires real PostgreSQL row locks")
    with TestClient(app) as first, TestClient(app) as second:
        a = first.post(
            "/v1/auth/login", json={"email": "admin@example.test", "password": "correct-horse-battery-123"}
        ).json()
        tenant = a["memberships"][0]["tenant_id"]
        created = first.post(
            f"/v1/tenants/{tenant}/members",
            headers={"X-CSRF-Token": a["csrf_token"]},
            json={
                "email": "second@example.test",
                "password": "second-admin-password",
                "role": "tenant_admin",
            },
        )
        assert created.status_code == 201
        b = second.post(
            "/v1/auth/login", json={"email": "second@example.test", "password": "second-admin-password"}
        ).json()
        barrier = Barrier(2)

        def disable(client, csrf, target):
            barrier.wait(timeout=10)
            return client.patch(
                f"/v1/tenants/{tenant}/members/{target}",
                headers={"X-CSRF-Token": csrf},
                json={"active": False},
            ).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            x = pool.submit(disable, first, a["csrf_token"], b["person"]["id"])
            y = pool.submit(disable, second, b["csrf_token"], a["person"]["id"])
            assert sorted([x.result(timeout=20), y.result(timeout=20)]) == [200, 404]
        with app.state.database.sessions() as db:
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(Membership)
                    .where(
                        Membership.tenant_id == tenant,
                        Membership.active.is_(True),
                        Membership.role == "tenant_admin",
                    )
                )
                == 1
            )
