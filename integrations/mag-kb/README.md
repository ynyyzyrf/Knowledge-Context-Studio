# MAG Knowledge Context MCP

Hermes uses this MCP server to access Knowledge Context Studio with a product-scoped Agent credential.

## Configure Hermes

After issuing an access credential in Knowledge Context Studio, paste the generated MCP block into Hermes and replace `<MAG_KB_MCP_ROOT>` with this folder path:

```json
{
  "mcpServers": {
    "mag-kb": {
      "command": "node",
      "args": ["D:/aicoding/個人知識庫/mcp/mag-kb/server.mjs"],
      "env": {
        "MAG_KB_BASE_URL": "http://localhost:8088",
        "MAG_KB_TOKEN": "kcs_xxx"
      }
    }
  }
}
```

Do not put the underlying OpenViking key in Hermes. The token above is the product-layer credential and can be revoked or rotated from the Studio.

## Tools

- `kb_health`: verify the credential and show allowed subjects/spaces.
- `kb_list_subjects`: list service subjects available to this credential.
- `kb_list_spaces`: list knowledge spaces available to this credential.
- `kb_context`: retrieve governed context for a subject and optional spaces.
- `kb_list_memories`: list active memories for a subject.
- `kb_submit_memory_candidate`: append a session message and submit it for extraction as a governed memory candidate.

## Local Check

```powershell
cd D:\aicoding\個人知識庫\mcp\mag-kb
npm run check
```

## Fix Log (2026-09-22)

- **stdio framing**: original `server.mjs` used LSP-style `Content-Length` framing, but the MCP stdio standard (and Hermes' built-in client) is newline-delimited JSON. `writeMessage`/`processBuffer` were rewritten to newline framing; connection now verified with `hermes mcp test`.
- **Deployed-API mismatch**: the deployed Studio (https://kcstudio.zeabur.app) does not expose `/v1/agent/subjects` or `/v1/agent/spaces` (those are tenant-scoped, user-session-only endpoints per `/openapi.json`). `kb_health`, `kb_list_subjects`, and `kb_list_spaces` were reworked to read `subject_ids` / `space_ids` from `/v1/agent/me`, which the agent credential can call.

## 0.2.0 個人 Context

本版本新增 Space + Token 綁定使用者的個人目錄工具：

- `kb_personal_list` / `kb_personal_get`：列表與完整讀取。
- `kb_personal_submit`：提交 memories／skills／peers 候選或建立 sessions。
- `kb_personal_messages` / `kb_personal_append`：讀取／追加會話訊息。

先在各目錄的 Agent 授權頁開啟相應讀取／提交權。resources 的授權不包含這些目錄。重試應重用 external_id；新候選需由人員審核。Skills 是參考內容，不能當成高優先級指令直接執行。舊的 Subject 工具保留相容，不會自動寫入私人目錄。

需要平台已部署 personal-context API 及遷移 7f4198c4b3cb。完整契約見 ../../docs/personal-context.md。這份倉庫內套件不會自動覆蓋工作區外既有 MCP，也不會更改 Hermes 設定。

## 2026-10-02 混合召回

`kb_context` 參數不變。後端升級至遷移 `4c2f8a10d301` 並運行 worker 後，個人資料支援詞項＋向量融合，文件與個人資料分享有保留份額的結果／字數預算。檢查 `personal_context_retrieval`、`personal_retrieval.degraded_reason` 與每筆版本／來源；不要把 keyword 降級稱為語意搜尋。`kb_personal_list?q=` 仍是字面篩選。

跨進程驗證：`uv run pytest -q tests/test_personal_mcp.py`，由 Node MCP stdio 調用真正 loopback HTTP API，讀回後撤權再次確認不可見。此為協議契約測試，不能代表 Hermes 自主選工具或完成實際業務任務。
