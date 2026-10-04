"""Native configuration fragments. Never embed product credentials in templates."""

import json


def harness_configs(base_url: str) -> list[dict[str, str]]:
    server = {
        "command": "node",
        "args": ["<MAG_KB_MCP_ROOT>/server.mjs"],
        "env": {"MAG_KB_BASE_URL": base_url, "MAG_KB_TOKEN": "${MAG_KB_TOKEN}"},
    }
    dump = lambda obj: json.dumps(obj, ensure_ascii=False, indent=2)
    return [
        {
            "id": "codex",
            "name": "Codex",
            "path": "~/.codex/config.toml",
            "config": '[mcp_servers.mag-kb]\ncommand = "node"\n'
            'args = ["<MAG_KB_MCP_ROOT>/server.mjs"]\n'
            'env_vars = ["MAG_KB_TOKEN"]\n\n[mcp_servers.mag-kb.env]\n'
            f"MAG_KB_BASE_URL = {json.dumps(base_url, ensure_ascii=False)}\n",
            "note": "合併到既有 TOML，避免重複同名區塊。啟動 Codex 前設定 MAG_KB_TOKEN。",
        },
        {
            "id": "claude-code",
            "name": "Claude Code",
            "path": "<project>/.mcp.json",
            "config": dump({"mcpServers": {"mag-kb": {"type": "stdio", **server}}}),
            "note": "合併 mcpServers；信任專案並允許此 MCP。啟動程序需有 MAG_KB_TOKEN。",
        },
        {
            "id": "openclaw",
            "name": "OpenClaw",
            "path": "~/.openclaw/openclaw.json",
            "config": dump({"mcp": {"servers": {"mag-kb": server}}}),
            "note": "適用支援原生 mcp.servers 的版本；合併到實際 Gateway 配置，"
            "並向其進程提供 MAG_KB_TOKEN。ACP bridge 不支援逐會話 MCP 注入。",
        },
        {
            "id": "hermes",
            "name": "Hermes",
            "path": "~/.hermes/config.yaml",
            # JSON is valid YAML 1.2. Existing YAML must be merged as a mapping, not appended.
            "config": dump({"mcp_servers": {"mag-kb": server}}),
            "note": "此片段為 YAML 相容 JSON；將 mcp_servers 映射合併至既有 YAML，"
            "不要直接追加整段或覆蓋原設定。Hermes 進程需有 MAG_KB_TOKEN。",
        },
    ]
