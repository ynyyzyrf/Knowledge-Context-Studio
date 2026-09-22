# Knowledge Context Studio

**最新進度：[專案進度總覽](PROGRESS.md)**（已完成、待驗收、下一步與證據）。

內部團隊 V1.0，正在開發。管理前端、文件匯入、記憶治理、引擎發布與授權檢索已有本機驗收。Agent 在外部運行；平台不內置 Agent 執行器。第三方 Agent 自主取用及正式生產驗收尚未完成。

## 啟動工作台

完成下方首次設定後，在此目錄執行：

```powershell
./scripts/start.ps1
# 程式更新後重新建置並重啟 API、worker
./scripts/start.ps1 -Restart
```

開啟 [管理工作台](http://localhost:8088/)，接口文件保留於 [Swagger](http://localhost:8088/docs)。腳本安裝鎖定依賴、建置前端、啟動資料庫、執行遷移並在背景啟動 API 和提取 worker；只綁定本機。日誌在 `runtime/`。`-SkipBuild` 僅在前端產物已更新時使用。這是本機啟動方式，尚未提供生產程序監督與災難恢復部署。

本機已建立的管理員帳號是 `admin@studio.local`；首次密碼保存在受限本機檔案 `runtime/initial-admin.txt`，不納入版本控制。新環境請使用下方 bootstrap 指令自行指定管理員，啟動脚本不會覆寫既有帳號。

工作台提供空間與授權、外部 Agent 與服務對象、有限範圍憑證、團隊成員、任務中心、記憶候選審核／來源／版本及操作紀錄。管理功能只對團隊管理員顯示。API 接入測試使用產品 Agent 憑證，手動建立會話、錄入外部訊息並提交真實模型提取；不產生 Agent 回答。憑證只保留於前端記憶體，刷新、切換團隊或登出後需重新接入。

審核後顯示「待發布」；引擎發布尚未接通，不能當作已可檢索。任務失敗會顯示錯誤與追蹤編號，需明確重試。

## 前端開發

```powershell
cd web
npm ci
npm test
npm run build
```

若使用 Vite 開發伺服器，先在啟動後端的終端設定 `$env:KCS_PUBLIC_ORIGIN='http://localhost:5173'`，再從 `web/` 執行 `npm run dev`。`/v1` 由 Vite 代理至 8088。回到同源建置模式時，移除此環境變數並重啟後端，恢復預設 `http://localhost:8088`。不得放寬 Origin 校驗來繞過開發設定。

## 本機設定

在此目錄執行：

```powershell
uv sync --frozen
uv run python -m kcs.manage init-config
docker compose up -d --wait postgres
uv run alembic upgrade head
uv run python -m kcs.manage bootstrap --email your-email@example.com
```

`init-config` 僅首次執行，拒絕覆寫既有設定。管理員密碼透過隱藏輸入提供。資料庫只綁定本機 55488 埠，資料保存在獨立 Docker volume。

編輯本機 `.env`，填入既有 OpenAI 相容服務：

- `KCS_MODEL_BASE_URL`：API 根路徑，例如 `https://your-provider.example/v1`。
- `KCS_MODEL_API_KEY`：API 金鑰。
- `KCS_CHAT_MODEL`：聊天模型名稱。
- `KCS_EMBEDDING_BASE_URL`：可選，向量模型 API 根路徑；留空時沿用 `KCS_MODEL_BASE_URL`。
- `KCS_EMBEDDING_API_KEY`：可選，向量模型 API 金鑰；留空且未配置 `KCS_EMBEDDING_BASE_URL` 時沿用 `KCS_MODEL_API_KEY`。
- `KCS_EMBEDDING_MODEL`：向量模型名稱。

聊天與向量可以使用不同供應商，例如聊天走內部 metis 網關、向量走 SiliconFlow：

```dotenv
KCS_MODEL_BASE_URL=http://zsgw.sjdistributor.com:40000/v1
KCS_MODEL_HTTP_ALLOWED_ORIGIN=http://zsgw.sjdistributor.com:40000
KCS_MODEL_API_KEY=sk-...
KCS_CHAT_MODEL=metis-coder

KCS_EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1
KCS_EMBEDDING_API_KEY=sk-...
KCS_EMBEDDING_MODEL=BAAI/bge-m3
```

SiliconFlow 的 Embeddings API 使用 OpenAI 相容路徑。若聊天和向量都使用同一個 SiliconFlow key，也可直接配置為：

```dotenv
KCS_MODEL_BASE_URL=https://api.siliconflow.cn/v1
KCS_MODEL_API_KEY=sk-...
KCS_CHAT_MODEL=your-chat-model
KCS_EMBEDDING_MODEL=BAAI/bge-m3
```

`KCS_MODEL_BASE_URL` 和 `KCS_EMBEDDING_BASE_URL` 必須停在 `/v1`，程式會自行請求 `/chat/completions` 或 `/embeddings`；不要填成完整的 `/v1/embeddings`。SiliconFlow 目前列出的 embedding 模型包含 `BAAI/bge-large-zh-v1.5`、`BAAI/bge-large-en-v1.5`、`netease-youdao/bce-embedding-base_v1`、`BAAI/bge-m3`、`Pro/BAAI/bge-m3`。中文／多語知識庫優先使用 `BAAI/bge-m3`；若使用 Pro 模型，請確認帳號權限和費用。

`KCS_CHAT_MODEL` 仍需按聊天模型供應商另行配置；`check-models` 會同時真實呼叫聊天與向量模型。若只想先驗證聊天，使用 `check-chat`。

`.env` 與 `runtime/` 不納入 Git，請限制本機檔案存取權限。外部模型 URL 預設必須使用 HTTPS；本機服務允許 HTTP。對使用者明確指定的 HTTP 服務，可在 `KCS_MODEL_HTTP_ALLOWED_ORIGIN` 填入精確的 `http://主機:埠`，例外不適用其他主機或埠。HTTP 傳輸不加密。程式不跟隨模型 API 重新導向。

```powershell
uv run python -m kcs.manage check-models
# 僅驗證聊天服務（尚未配置向量模型時）
uv run python -m kcs.manage check-chat
```

此命令會真實呼叫一次聊天及向量模型，可能產生供應商費用。缺少設定會明確失敗，不會回退到模擬資料。輸出不包含金鑰、供應商錯誤原文或回傳內容。此檢查只是連線與格式驗證，完整檢索品質驗收仍需實際資料。

## 驗證

```powershell
uv run pytest -q
# 專用測試庫只需建立一次；各測試使用獨立 schema，套用正式遷移後才開始測試。
docker compose exec -T postgres createdb -U kcs kcs_test
uv run pytest --postgres -q
uv run alembic check
```

背景提取 worker：

```powershell
uv run python -m kcs.worker
# 處理至多一個當前可執行任務後退出
uv run python -m kcs.worker --once
```

Agent 透過 `POST /v1/sessions/{id}/commit` 提交 `{ "idempotency_key": "..." }`，返回 202 和任務資料。`GET /v1/jobs/{id}` 查詢實際結果；worker 程序正常退出不等於任務成功。任務使用 pending/running/retry/succeeded/failed 狀態，暫時模型錯誤最多自動嘗試三次，失敗可透過 `/v1/jobs/{id}/retry` 明確重試。

目前每次提取最多 1,000 則訊息且合計 100,000 字元，超限明確失敗；不會悄悄截斷。結果只保存為待審候選，尚未發布到檢索。憑證撤銷、過期或 Subject 停用會阻止尚未完成的任務保存結果；輪替後可用新憑證明確重試。

真實模型測試需明確加入 `--live-model`，預設測試不發出模型請求；實際呼叫可能產生費用。

PostgreSQL 測試只使用 `kcs_test` 資料庫，結束後清理本次產生的 schema，不清空產品資料庫。

完整工作範圍和進度見 [implementation.md](docs/implementation.md)。

## 記憶發布與外部讀回

候選審核後由背景 worker 發布；正文與向量索引驗證成功後才標示有效。外部 Agent 使用 `GET /v1/subjects/{id}/memories` 及 `POST /v1/context` 讀取授權記憶。工作台「API 接入測試」提供有效記憶與語意檢索驗證，不執行 Agent。

私有引擎配置、Python 接入範例、錯誤與刪除語意見 [外部 Agent 讀回指南](docs/external-agent-readback.md)。完整生產部署與災難恢復驗收仍待完成。

## 文件匯入

工作台「知識空間 → 開啟空間 → 文件匯入」支援 Markdown、UTF-8 文字與文字型 PDF。檔案由持久化背景任務解析、分段並建立真正的向量索引；成功後，獲授權的外部 Agent 可透過 `/v1/context` 讀回原文與來源。支援狀態查詢、解析預覽、失敗重試、刪除及背景清理。

上限、API、權限及不支援格式見 [文件匯入指南](docs/document-import.md)；測試與瀏覽器證據見 [匯入驗收](docs/evidence/document-import-acceptance.md)。平台不執行 Agent。
