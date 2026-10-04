"""Opt-in installed-harness clients -> real loopback KCS; no production calls.

KCS_OPENCLAW_RUNTIME: absolute installed agents/pi-bundle-mcp-runtime.js path.
KCS_HERMES_ROOT: installed Hermes source root with venv/Scripts/python.exe.
KCS_CODEX_EXE: installed Codex executable; no model call.
KCS_CLAUDE_EXE plus --live-model: one model probe capped at $0.25.
These clients are intentionally optional and never installed by the test.
"""

import json
import os
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
from test_personal_context import paths


@pytest.mark.parametrize("harness", ["openclaw", "hermes", "codex", "claude"])
def test_native_client_full_storage(app, tmp_path, harness, request):
    runtime = os.environ.get(
        {
            "openclaw": "KCS_OPENCLAW_RUNTIME",
            "hermes": "KCS_HERMES_ROOT",
            "codex": "KCS_CODEX_EXE",
            "claude": "KCS_CLAUDE_EXE",
        }[harness]
    )
    if not runtime:
        pytest.skip(f"Set the installed {harness} runtime path to opt in")
    if harness == "claude" and not request.config.getoption("--live-model"):
        pytest.skip("Claude model probe requires explicit --live-model")
    if harness == "claude" and Path(runtime).suffix.lower() in {".cmd", ".bat"}:
        pytest.fail("Use the native Claude executable so timeout termination cannot orphan a shell child")
    calls = []

    @app.middleware("http")
    async def record_calls(request, call_next):
        calls.append((request.method, request.url.path))
        return await call_next(request)

    with TestClient(app) as admin, TestClient(app) as machine:
        _, agent, _, space, base = setup(admin, machine)
        human, api = paths(base, space, "memories")
        result = admin.put(
            human + "/agent-access/" + agent["id"],
            json={
                "can_read": True,
                "can_write": True,
                "auto_store": True,
            },
        )
        assert result.status_code == 200
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        address = f"http://127.0.0.1:{sock.getsockname()[1]}"
        server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
        thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
        thread.start()
        bridge = str(Path("integrations/mag-kb/server.mjs").resolve())
        content = "完整第一段：已確認的測試偏好。\n\n第二段保留所有細節，不進行摘要。"
        cfg = {
            "command": shutil.which("node"),
            "args": [bridge],
            "env": {
                "MAG_KB_BASE_URL": address,
                "MAG_KB_TOKEN": machine.headers["Authorization"].removeprefix("Bearer "),
            },
        }
        body = {
            "space_id": space["id"],
            "kind": "memories",
            "external_id": "native-test",
            "title": "Native harness test",
            "content": content,
        }
        # Input contains only a short-lived test DB credential, never a production secret.
        input_file = tmp_path / "input.json"
        input_file.write_text(json.dumps({"cfg": cfg, "body": body}), encoding="utf-8")
        env = {**os.environ, "KCS_PROBE_INPUT": str(input_file), "PYTHONIOENCODING": "utf-8"}
        try:
            deadline = time.monotonic() + 10
            while not server.started and time.monotonic() < deadline:
                time.sleep(0.01)
            assert server.started
            if harness == "openclaw":
                script = tmp_path / "probe.mjs"
                script.write_text(OPENCLAW_PROBE, encoding="utf-8")
                env["KCS_OPENCLAW_MODULE"] = Path(runtime).resolve().as_uri()
                command = [shutil.which("node"), str(script)]
            elif harness == "hermes":
                script = tmp_path / "probe.py"
                script.write_text(HERMES_PROBE, encoding="utf-8")
                env["HERMES_HOME"] = str(tmp_path / "hermes-home")
                env["PYTHONPATH"] = runtime
                command = [str(Path(runtime) / "venv/Scripts/python.exe"), str(script)]
            elif harness == "codex":
                import sys

                script = tmp_path / "probe.py"
                script.write_text(CODEX_PROBE, encoding="utf-8")
                env["KCS_CODEX_EXE"] = runtime
                command = [sys.executable, str(script)]
            else:
                mcp_file = tmp_path / "mcp.json"
                mcp_file.write_text(json.dumps({"mcpServers": {"mag-kb": cfg}}), encoding="utf-8")
                prompt = (
                    "This is an authorized test against an isolated KCS test database. "
                    "Use only mag-kb MCP tools. Read kb_guide and kb_health. "
                    "Call kb_personal_submit twice with exactly the same arguments below, "
                    "then kb_personal_get for the returned entry. Do not shorten content. "
                    "Check equal entry IDs, active status, and exact content. "
                    "Do not access any other space. Return a brief verification result. Arguments: "
                    + json.dumps(body, ensure_ascii=False)
                )
                command = [
                    runtime,
                    "--print",
                    prompt,
                    "--strict-mcp-config",
                    "--mcp-config",
                    str(mcp_file),
                    "--no-session-persistence",
                    "--tools",
                    "",
                    "--allowedTools",
                    "mcp__mag-kb__*",
                    "--settings",
                    '{"disableAllHooks":true}',
                    "--setting-sources",
                    "user",
                    "--max-budget-usd",
                    "0.25",
                    "--effort",
                    "low",
                    "--output-format",
                    "json",
                ]
            calls.clear()
            response = subprocess.run(
                command,
                env=env,
                cwd=tmp_path,
                text=True,
                encoding="utf-8",
                capture_output=True,
                stdin=subprocess.DEVNULL,
                timeout=90 if harness == "claude" else 50,
                check=False,
            )
            assert response.returncode == 0, response.stderr
            if harness != "claude":
                assert '"verified": true' in response.stdout
            else:
                outcome = json.loads(response.stdout)
                assert not outcome.get("is_error"), outcome.get("result", "Model probe failed")
            assert calls.count(("POST", api + "/entries")) == 2
            assert ("GET", "/v1/agent/me") in calls
            assert any(method == "GET" and path.startswith(api + "/entries/") for method, path in calls)
            rows = machine.get(api + "/entries").json()["items"]
            assert len(rows) == 1
            assert machine.get(api + "/entries/" + rows[0]["id"]).json()["content"] == content
        finally:
            input_file.unlink(missing_ok=True)
            (tmp_path / "mcp.json").unlink(missing_ok=True)
            server.should_exit = True
            thread.join(timeout=10)
            sock.close()


OPENCLAW_PROBE = r"""
import fs from 'node:fs';
const {createSessionMcpRuntime} = await import(process.env.KCS_OPENCLAW_MODULE);
const {cfg, body} = JSON.parse(fs.readFileSync(process.env.KCS_PROBE_INPUT, 'utf8'));
const runtime = createSessionMcpRuntime({sessionId:'kcs-storage-test',workspaceDir:process.cwd(),
  cfg:{plugins:{enabled:false},mcp:{servers:{'mag-kb':cfg}}}});
const call = async (tool, args={}) => {
 const result=await runtime.callTool('mag-kb',tool,args);
 if(result.isError) throw Error('MCP tool failed');
 return JSON.parse(result.content[0].text);
};
try {
 const catalog=await runtime.getCatalog();
 if(!catalog.tools.some(t=>t.toolName==='kb_guide')) throw Error('Missing guide');
 await call('kb_health');
 const first=await call('kb_personal_submit',body);
 const retry=await call('kb_personal_submit',body);
 const read=await call('kb_personal_get',{space_id:body.space_id,kind:body.kind,entry_id:first.id});
 if(first.id!==retry.id || read.content!==body.content || first.status!=='active') throw Error('Storage mismatch');
 console.log('{"verified": true}');
} finally {await runtime.dispose();}
"""

HERMES_PROBE = r"""
import asyncio, json, os
from pathlib import Path
from tools.mcp_tool import _connect_server
data=json.loads(Path(os.environ['KCS_PROBE_INPUT']).read_text(encoding='utf-8'))
async def main():
 server=await _connect_server('mag-kb',data['cfg'])
 async def call(tool, args={}):
  result=await server.session.call_tool(tool,arguments=args)
  assert not result.isError
  return json.loads(result.content[0].text)
 try:
  assert any(t.name=='kb_guide' for t in server._tools)
  await call('kb_health')
  body=data['body']
  first=await call('kb_personal_submit',body)
  retry=await call('kb_personal_submit',body)
  read=await call('kb_personal_get',{'space_id':body['space_id'],'kind':body['kind'],'entry_id':first['id']})
  assert first['id']==retry['id'] and read['content']==body['content'] and first['status']=='active'
  print('{"verified": true}')
 finally:
  await server.shutdown()
asyncio.run(main())
"""

CODEX_PROBE = r"""
import json, os, pathlib, subprocess, queue, threading
data=json.loads(pathlib.Path(os.environ['KCS_PROBE_INPUT']).read_text(encoding='utf-8'))
def toml(v):
 if isinstance(v,dict): return '{'+','.join(json.dumps(k)+'='+toml(x) for k,x in v.items())+'}'
 return json.dumps(v)
p=subprocess.Popen([os.environ['KCS_CODEX_EXE'],'app-server','--stdio','-c',
 'mcp_servers='+toml({'mag-kb':data['cfg']})],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
 stderr=subprocess.DEVNULL,text=True,encoding='utf-8')
q=queue.Queue()
threading.Thread(target=lambda:[q.put(json.loads(l)) for l in p.stdout],daemon=True).start()
seq=0
def rpc(method,params):
 global seq
 seq+=1
 p.stdin.write(json.dumps({'id':seq,'method':method,'params':params})+'\n');p.stdin.flush()
 while True:
  row=q.get(timeout=25)
  if row.get('id')==seq:
   assert 'error' not in row, row.get('error')
   return row['result']
try:
 rpc('initialize',{'clientInfo':{'name':'kcs-storage-probe','version':'1'},'capabilities':{'experimentalApi':True}})
 thread=rpc('thread/start',{'cwd':str(pathlib.Path(os.environ['KCS_PROBE_INPUT']).parent),
  'ephemeral':True,'config':{'mcp_servers':{'mag-kb':data['cfg']}}})['thread']['id']
 rpc('mcpServerStatus/list',{'threadId':thread})
 def call(tool,args={}):
  result=rpc('mcpServer/tool/call',{'threadId':thread,'server':'mag-kb','tool':tool,'arguments':args})
  assert not result.get('isError')
  return json.loads(result['content'][0]['text'])
 call('kb_health')
 body=data['body']; first=call('kb_personal_submit',body); retry=call('kb_personal_submit',body)
 read=call('kb_personal_get',{'space_id':body['space_id'],'kind':body['kind'],'entry_id':first['id']})
 assert first['id']==retry['id'] and read['content']==body['content'] and first['status']=='active'
 print('{"verified": true}')
finally:
 p.terminate();p.wait(timeout=10)
"""
