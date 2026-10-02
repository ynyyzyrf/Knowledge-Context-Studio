"""Opt-in real-model delivery smoke for an EMPTY disposable product installation."""

import argparse
import json
import secrets
import time
from pathlib import Path

import httpx

from kcs.bootstrap import bootstrap_admin
from kcs.config import Settings
from kcs.database import Database


def wait_document(admin, path):
    for _ in range(90):
        response = admin.get(path)
        response.raise_for_status()
        document = response.json()
        if document["state"] == "succeeded":
            return
        if document["state"] == "failed":
            raise RuntimeError("Document processing failed")
        time.sleep(2)
    raise RuntimeError("Document processing timed out")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["seed", "read", "cleanup"])
    args = parser.parse_args()
    settings = Settings()
    state_path = Path("runtime/product-smoke.json")
    if args.phase == "seed":
        if state_path.exists():
            raise ValueError("Smoke state exists; refusing to seed twice")
        state = {"email": "delivery@example.test", "password": secrets.token_urlsafe(32)}
        bootstrap_admin(Database(settings.database_url), email=state["email"],
                        password=state["password"], tenant_name="Delivery acceptance")
    else:
        state = json.loads(state_path.read_text())
    with httpx.Client(base_url="http://api:8088", timeout=90, trust_env=False,
                      headers={"Origin": settings.public_origin}) as admin:
        login = admin.post("/v1/auth/login", json={"email": state["email"], "password": state["password"]})
        login.raise_for_status()
        admin.headers["X-CSRF-Token"] = login.json()["csrf_token"]
        tenant = login.json()["memberships"][0]["tenant_id"]
        base = f"/v1/tenants/{tenant}"

        def create(path, data):
            response = admin.post(path, json=data)
            response.raise_for_status()
            return response.json()

        if args.phase == "seed":
            agent = create(base + "/agents", {"name": "Delivery smoke"})
            subject = create(base + f"/agents/{agent['id']}/subjects", {"name": "Synthetic subject"})
            credential = create(base + f"/agents/{agent['id']}/credentials",
                                {"subject_ids": [subject["id"]], "expires_in_days": 1})
            space = create(base + "/spaces", {"name": "Delivery smoke"})
            space_path = base + f"/spaces/{space['id']}"
            admin.put(space_path + f"/agents/{agent['id']}", json={"active": True}).raise_for_status()
            uploaded = admin.post(space_path + "/documents", params={"filename": "delivery.md", "scope": "shared"},
                                  content=b"Delivery acceptance: Amber support closes at 18:00 every weekday.",
                                  headers={"Content-Type": "application/octet-stream"})
            uploaded.raise_for_status()
            state.update(token=credential["token"], subject=subject["id"], agent=agent["id"],
                         document=uploaded.json()["id"], space_path=space_path)
            state_path.write_text(json.dumps(state))
            state_path.chmod(0o600)
        path = state["space_path"] + "/documents/" + state["document"]
        with httpx.Client(base_url="http://api:8088", timeout=90, trust_env=False,
                          headers={"Authorization": "Bearer " + state["token"]}) as machine:
            query = {"subject_id": state["subject"], "query": "When does Amber support close?"}
            if args.phase == "cleanup":
                admin.delete(path).raise_for_status()
                response = machine.post("/v1/context", json=query)
                response.raise_for_status()
                assert not response.json()["documents"], "Deleted document is still visible"
                wait_document(admin, path)
            else:
                wait_document(admin, path)
                response = machine.post("/v1/context", json=query)
                response.raise_for_status()
                result = response.json()
                assert any(row["id"] == state["document"] for row in result["documents"])
                assert "18:00" in result["context"]
                # Revoke and restore space access, checking both negative and positive behavior.
                grant = state["space_path"] + f"/agents/{state['agent']}"
                admin.put(grant, json={"active": False}).raise_for_status()
                revoked = machine.post("/v1/context", json=query)
                revoked.raise_for_status()
                assert not revoked.json()["documents"]
                admin.put(grant, json={"active": True}).raise_for_status()
                restored = machine.post("/v1/context", json=query)
                restored.raise_for_status()
                assert "18:00" in restored.json()["context"]
    print(f"PRODUCT_SMOKE_{args.phase.upper()}_PASS: real HTTP, PostgreSQL, worker, native engine and embedding model")


if __name__ == "__main__":
    main()
