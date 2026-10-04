import json
import os
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

from kcs.harness_configs import harness_configs


def test_native_configs_roundtrip_and_no_secret():
    url = 'https://example.com/中文?q="test"'
    configs = {item["id"]: item for item in harness_configs(url)}
    assert set(configs) == {"codex", "claude-code", "openclaw", "hermes"}
    codex = tomllib.loads(configs["codex"]["config"])["mcp_servers"]["mag-kb"]
    assert codex["env"]["MAG_KB_BASE_URL"] == url
    assert codex["env_vars"] == ["MAG_KB_TOKEN"]
    for name, keys in [
        ("claude-code", ["mcpServers"]),
        ("openclaw", ["mcp", "servers"]),
        ("hermes", ["mcp_servers"]),
    ]:
        # JSON is a YAML 1.2 subset: Hermes receives valid native YAML without a new serializer.
        obj = json.loads(configs[name]["config"])
        for key in keys:
            obj = obj[key]
        server = obj["mag-kb"]
        assert server["env"]["MAG_KB_BASE_URL"] == url
        assert server["env"]["MAG_KB_TOKEN"] == "${MAG_KB_TOKEN}"
        assert server["args"] == ["<MAG_KB_MCP_ROOT>/server.mjs"]
    assert all("kcs_" not in item["config"] for item in configs.values())


def test_guide_available_via_stdio_without_credentials():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required")
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "kb_guide"}},
    ]
    env = {k: v for k, v in os.environ.items() if not k.startswith("MAG_KB_")}
    result = subprocess.run(
        [node, str(Path("integrations/mag-kb/server.mjs").resolve())],
        input="".join(json.dumps(m) + "\n" for m in messages),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    replies = {row["id"]: row["result"] for row in map(json.loads, result.stdout.splitlines())}
    assert "kb_guide" in replies[1]["instructions"]
    assert any(tool["name"] == "kb_guide" for tool in replies[2]["tools"])
    guide = replies[3]["content"][0]["text"]
    assert "kb_job_result" in guide and "user_context" in guide
    assert "privacy" in guide and "resources" in guide
