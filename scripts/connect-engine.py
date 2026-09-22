"""Provision/reuse the private publisher account; keep credentials in local .env."""

import json
from pathlib import Path

import httpx
from dotenv import set_key

from kcs.config import Settings

s = Settings()
url = "http://127.0.0.1:19388"
root = json.loads(Path("runtime/engine.json").read_text())["server"]["root_api_key"]
with httpx.Client(base_url=url, headers={"X-API-Key": root}, trust_env=False, timeout=60) as client:
    if s.engine_url == url and s.engine_api_key.get_secret_value():
        response = client.get(
            "/api/v1/fs/ls",
            params={"uri": "viking://resources"},
            headers={"X-API-Key": s.engine_api_key.get_secret_value()},
        )
        response.raise_for_status()
    else:
        response = client.post(
            "/api/v1/admin/accounts", json={"account_id": "kcs", "admin_user_id": "publisher"}
        )
        if response.status_code not in (200, 201, 409):
            raise RuntimeError(f"Account provisioning failed: HTTP {response.status_code}")
        response = client.post("/api/v1/admin/accounts/kcs/users/publisher/key")
        response.raise_for_status()
        key = response.json()["result"]["user_key"]
        set_key(".env", "KCS_ENGINE_URL", url)
        set_key(".env", "KCS_ENGINE_API_KEY", key)
print("Private publisher account connected.")
