"""Successful HTTP responses must observe committed policy, including on real TCP clients."""

from fastapi.testclient import TestClient
from test_agents_spaces import admin_login, create, setup_agent

from kcs.models import AgentSpaceGrant


def test_grant_is_committed_before_response_headers(app):
    observed = []
    target = []

    async def wrapped(scope, receive, send):
        async def observe(message):
            if target and scope.get("path") == target[0] and message["type"] == "http.response.start":
                with app.state.database.sessions() as db:
                    grant = db.get(AgentSpaceGrant, target[1])
                    observed.append((message["status"], grant.active))
            await send(message)

        await app(scope, receive, observe)

    with TestClient(wrapped) as admin:
        tenant = admin_login(admin)
        agent, _, _ = setup_agent(admin, tenant)
        space = create(admin, f"/v1/tenants/{tenant}/spaces", {"name": "Commit barrier"})
        path = f"/v1/tenants/{tenant}/spaces/{space['id']}/agents/{agent['id']}"
        assert admin.put(path, json={"active": False}).status_code == 200
        target.extend([path, (tenant, space["id"], agent["id"])])
        assert admin.put(path, json={"active": True}).status_code == 200
        assert admin.put(path, json={"active": False}).status_code == 200
    assert observed == [(200, True), (200, False)]
