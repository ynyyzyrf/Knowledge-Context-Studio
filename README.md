# Knowledge Context Studio

內部團隊 V1.0，正在開發。帳號、Agent、空間授權及會話 API 已實作；完整 UI、工作任務、引擎接入及正式驗收尚未完成。

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

PostgreSQL 測試只使用 `kcs_test` 資料庫，結束後清理本次產生的 schema，不清空產品資料庫。

完整工作範圍和進度見 [implementation.md](docs/implementation.md)。
