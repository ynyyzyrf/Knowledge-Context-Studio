# Knowledge Context Studio

內部團隊 V1.0，正在開發。管理前端已對接帳號、外部 Agent、空間授權、會話提取任務和記憶治理 API。Agent 在外部運行；平台不內置 Agent 執行器。文件匯入、引擎發布、檢索與正式生產驗收尚未完成。

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
- `KCS_EMBEDDING_MODEL`：向量模型名稱。

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
