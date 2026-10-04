"""Real Node stdio -> loopback HTTP contract; no autonomous Agent or live LLM claim."""

import json
import os
import queue
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from fastapi.testclient import TestClient
from test_documents import setup
from test_personal_context import enable, grant, item, paths
from test_publication import Engine


def test_mcp_context_paraphrase_and_revocation(app):
    if not shutil.which("node"):
        pytest.skip("Node is required for MCP stdio acceptance")
    app.state.context_engine_factory = lambda: Engine()
    with TestClient(app) as admin, TestClient(app) as machine:
        _, agent, subject, space, base = setup(admin, machine)
        human, _ = paths(base, space, "memories")
        grant(admin, human, agent)
        row = enable(admin, human, item(admin, human, title="週報偏好", content="週報需附來源連結。"))
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        address = f"http://127.0.0.1:{sock.getsockname()[1]}"
        server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
        thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
        thread.start()
        process = None
        try:
            deadline = time.monotonic() + 10
            while not server.started and time.monotonic() < deadline:
                time.sleep(0.01)
            assert server.started
            process = subprocess.Popen(
                [shutil.which("node"), str(Path("integrations/mag-kb/server.mjs").resolve())],
                env={
                    **os.environ,
                    "MAG_KB_BASE_URL": address,
                    "MAG_KB_TOKEN": machine.headers["Authorization"].removeprefix("Bearer "),
                },
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
            )
            lines = queue.Queue()
            reader = threading.Thread(
                target=lambda: [lines.put(line) for line in process.stdout], daemon=True
            )
            reader.start()

            def rpc(identity, method, params):
                process.stdin.write(
                    json.dumps({"jsonrpc": "2.0", "id": identity, "method": method, "params": params}) + "\n"
                )
                process.stdin.flush()
                response = json.loads(lines.get(timeout=15))
                assert response["id"] == identity and "error" not in response, response
                return response["result"]

            rpc(
                1,
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "contract-test", "version": "1"},
                },
            )
            args = {
                "name": "kb_context",
                "arguments": {
                    "subject_id": subject["id"],
                    "space_ids": [space["id"]],
                    "query": "週報格式有哪些要求？",
                },
            }
            body = json.loads(rpc(2, "tools/call", args)["content"][0]["text"])
            assert body["personal_context"][0]["id"] == row["id"]
            assert body["personal_context"][0]["version"] == row["version"]
            assert body["content_role"] == "untrusted_reference_data"
            grant(admin, human, agent, read=False)
            body = json.loads(rpc(3, "tools/call", args)["content"][0]["text"])
            assert body["personal_context"] == [] and "來源連結" not in body["context"]
            submitted = json.loads(
                rpc(
                    4,
                    "tools/call",
                    {
                        "name": "kb_submit_memory_candidate",
                        "arguments": {
                            "subject_id": subject["id"],
                            "content": "Acknowledged",
                            "idempotency_key": "r" * 128,
                        },
                    },
                )["content"][0]["text"]
            )
            job_id = submitted["job"]["id"]
            response = rpc(5, "tools/call", {"name": "kb_job_result", "arguments": {"job_id": job_id}})
            assert not response.get("isError"), response
            waiting = json.loads(response["content"][0]["text"])
            assert waiting["result"]["pipeline_state"] == "waiting"
            from kcs.jobs import run_one
            from kcs.model_service import ChatResult

            run_one(
                app.state.database,
                app.state.settings,
                complete_chat=lambda _: ChatResult('{"memories":[]}', 1, 1),
            )
            completed = json.loads(
                rpc(6, "tools/call", {"name": "kb_job_result", "arguments": {"job_id": job_id}})["content"][
                    0
                ]["text"]
            )
            assert completed["result"]["reason"] == "no_durable_facts"
        finally:
            if process is not None:
                process.terminate()
                process.communicate(timeout=10)
            server.should_exit = True
            thread.join(timeout=10)
            sock.close()
