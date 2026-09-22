# Zeabur 部署與更新

本次使用既有 `Knowledge-Context-Studio` 專案，部署在 Zeabur 管理的騰訊雲 Jakarta 主機。
公開入口：https://kcstudio.zeabur.app 。最終驗證狀態以 `PROGRESS.md` 和部署證據文件為準。

## 四個服務

| 服務 | 用途 | 啟動方式 | 持久資料 |
| --- | --- | --- | --- |
| knowledge-context-studio | 管理前端與產品 API | `alembic upgrade head && exec uvicorn kcs.app:create_app --factory --host 0.0.0.0 --port 8088` | PostgreSQL |
| postgresql | 帳號、授權、會話、記憶與文件真源 | 沿用原有 PostgreSQL 18 服務 | 沿用原有資料卷 |
| kcs-worker | 記憶抽取、發布、文件解析／索引與刪除 | `/app/.venv/bin/python -m kcs.worker` | PostgreSQL 持久任務 |
| kcs-openviking | 私有上下文引擎與向量索引 | `python -I /usr/local/bin/kcs-engine-start.py` | `engine-data` 掛載 `/data` |

API 和 worker 使用相同產品倉庫的 `v1` 分支，分別執行不同程序。只有 API 綁定公開 HTTPS 網域。
OpenViking 不綁公開網域；Hermes 等外部 Agent 使用平台 Bearer 憑證呼叫 API。
PostgreSQL 原有對外 TCP 轉發保留；應用程式實際連線走專案內網。

## 環境變數

API 與 worker 共用以下設定，秘密值只在 Zeabur 環境變數與本機被 Git 忽略的受限設定目錄中。

| 變數 | 設定 |
| --- | --- |
| `KCS_DATABASE_URL` | `postgresql+psycopg://<user>:<URL-encoded-password>@postgresql:5432/zeabur` |
| `KCS_PUBLIC_ORIGIN` | `https://kcstudio.zeabur.app` |
| `KCS_SECURE_COOKIES` | `true` |
| `KCS_MODEL_BASE_URL` | 現有聊天服務的 `/v1` API 地址 |
| `KCS_MODEL_HTTP_ALLOWED_ORIGIN` | 聊天服務使用 HTTP 時，精確填寫允許的 origin |
| `KCS_MODEL_API_KEY` | 聊天服務金鑰 |
| `KCS_CHAT_MODEL` | `metis-coder` |
| `KCS_EMBEDDING_BASE_URL` | `https://api.siliconflow.cn/v1` |
| `KCS_EMBEDDING_API_KEY` | 向量服務專用金鑰 |
| `KCS_EMBEDDING_MODEL` | `BAAI/bge-m3`，1024 維 |
| `KCS_ENGINE_URL` | 實際私有 DNS origin，預期 `http://kcs-openviking:1933`；須讀回確認 |
| `KCS_ENGINE_HTTP_ALLOWED_ORIGIN` | 與 `KCS_ENGINE_URL` 完全一致 |
| `KCS_ENGINE_API_KEY` | 引擎 `kcs/publisher` 帳號的普通 user key |

API 的 `web` 轉發埠為 **8088**，不能保留 Zeabur 預設的 8080。
引擎使用 `OPENVIKING_CONF_CONTENT` JSON；包含 `/data` 本地儲存、1024 維模型、
`server.auth_mode=api_key`、`server.with_bot=false` 及獨立 root key。
root key 只供引擎首次建立 publisher 帳號，不作為平台的 `KCS_ENGINE_API_KEY`。
引擎另設 `ZBPACK_DOCKERFILE_PATH=Dockerfile`，明確指定 Docker 建置；上傳目錄亦帶有
`zbpack.json` 的相同設定，避免純來源封裝目錄被自動判成靜態網站。

不要直接把 CLI 列出的 `${POSTGRES_USER}` 等未解析字串拼進 URL。
須解析 PostgreSQL 自身的變數引用；URL 中的密碼需編碼。
`zeabur variable env` 會覆蓋服務變數，且可能回顯秘密；先保留現有值，輸出寫入受限本機檔案。

## 固定版本引擎重新部署

來源固定在 `20ec78a149a0889a85b038627dddc70b46dceae3`。
這是原生 C++／Rust 引擎，需要完整編譯；不要換成浮動的 `latest` 來省略版本驗證。
本次採用 CLI 原始碼上傳建置，不依賴本機 Docker tag 或未公開的 registry 映像。
來源以單一 tar 封裝傳輸；Docker 的 source 階段會核對全部 2,072 個檔案的 SHA-256。
首次散檔上傳在雲端缺少 LevelDB 的 `helpers/memenv/memenv.cc`，因此不能省略完整性檢查。

從產品目錄執行，`--source` 指向含該 commit 的 OpenViking checkout，輸出必須是空目錄：

```powershell
python deploy/zeabur/prepare-engine.py --source ../validation/worktrees/openviking-g0 --output runtime/zeabur-engine-upload
Set-Location runtime/zeabur-engine-upload
zeabur deploy --project-id 6ab1e93fafd7153d77b417e2 --environment-id 6ab1e93f36d2a6cac45bdab1 --service-id 6ab2063dafd7153d77b4251e --json -i=false
```

必須帶既有 `--service-id`，避免新增第二套引擎。保留原有 `/data` 卷及 root key；
更換 embedding 模型／維度涉及重建索引，不應只替換環境變數。
此次配方限制 native 編譯並行數為 2，使用來源中的鎖檔；倉庫配方已將四個基礎映像固定為本次雲端建置實際解析的 digest。

## 更新與驗證

1. 檢查 `v1` 的實際 commit；API／worker 必須部署同一版本。
2. 先做 PostgreSQL 與引擎資料備份，再執行資料遷移；有破壞性遷移時另行制定回滾方案。
3. 更新 API 和 worker 設定後，逐一重啟。重啟程序不等於重建映像。
4. 檢查首頁、管理員登入、`/health/ready`、引擎向量索引，以及 worker 的真實任務完成狀態。
5. 按 [雲端冒煙流程](cloud-smoke.md) 驗證原文寫入、候選抽取、審核發布、上下文讀回、文件匯入及撤權。

`/health/ready` 只檢查資料庫，不代表模型、worker 或引擎就緒。
冒煙測試通過也不等於已完成正式容量、監控告警、備份恢復與 Hermes 客戶端驗收。
