# 雲端試運行與外部 Agent 冒煙驗收

狀態：2026-09-22 已透過 Zeabur 部署平台與 worker，沿用既有 PostgreSQL。固定版本 OpenViking 已部署成功；外部 API 原文寫入、去重、真實模型抽取、記憶與文件索引讀回、引擎重啟持久性、撤權及清理均通過。完整證據見 [雲端部署驗收](evidence/zeabur-deployment-acceptance.md)。這是 HTTP 測試客戶端驗證，尚非本地 Hermes 接入。雲端設定見 [Zeabur 部署指南](zeabur-deployment.md)；自管 Docker 操作見 [Docker 統一部署指南](docker-deployment.md)。

## 部署前需完成

原本 `scripts/start.ps1`、`compose.yaml` 與 `compose.engine.yaml` 是本機開發配置。新增的 `compose.deploy.yaml`、Dockerfile 與 `deploy/start.sh` 提供容器統一部署；固定 native 引擎仍須先匯出／匯入，尚未發布 registry。

取得伺服器作業系統／CPU 架構、Docker 狀態、網域和部署通道後，需依目標環境補齊：

1. 固定版本引擎映像的建置／分發，並確認架構相容。不可把本機 image ID 當作可從 registry 拉取的遠端映像。
2. 前端建置、API 和 worker 的持續運行方式，以及資料庫遷移與管理員初始化。
3. 公開入口與 `KCS_PUBLIC_ORIGIN` 一致；使用 HTTPS 時設 `KCS_SECURE_COOKIES=true`。資料庫與引擎維持私有。
4. 容器部署時明確處理服務地址：私有 HTTP 引擎須同時設定精確的 `KCS_ENGINE_HTTP_ALLOWED_ORIGIN`，不得只填寫 `KCS_ENGINE_URL`。
5. 在雲端獨立設定聊天／向量服務，驗證可達性與實際向量索引；不直接複製本機帳號、Cookie、金鑰及驗收資料。
6. 使用獨立試運行資料與持久卷；確認重啟後資料仍存在。完整災難恢復與正式上線驗收另行完成。

## 第一輪：確認 Agent 資料確實進來

平台不執行 Agent，也不會只憑憑證自動抓取外部對話。外部 Agent 或其接入程式需要主動發出下列請求。

先由管理員登記測試 Agent、Subject，簽發只涵蓋該 Subject 的有限期憑證。外部呼叫只帶產品 Bearer token，不使用人員 Cookie，也不使用模型供應商金鑰。

| 步驟 | API | 通過標準 |
| --- | --- | --- |
| 身份 | `GET /v1/agent/me` | Agent、租戶和 Subject 範圍符合預期 |
| 建會話 | `POST /v1/sessions` | 傳 `subject_id`、`idempotency_key`，取得 `id` |
| 寫訊息 | `POST /v1/sessions/{id}/messages` | 傳 `message_id`、`role`（user／assistant）、`content`，成功寫入合成測試事實 |
| 核對原文 | `GET /v1/sessions/{id}/messages` | 返回的原文、會話及 Subject 正確；相同 message_id 重送不新增第二則 |
| 提交抽取 | `POST /v1/sessions/{id}/commit` | 傳 `idempotency_key`，取得持久化任務 ID；202 只代表已接收 |
| 查詢結果 | `GET /v1/jobs/{id}` | 最終 succeeded；失敗保留 error_code 和 request_id 排查，不以程序存活代替成功 |

這一輪區分「原始資料寫入成功」與「模型處理成功」。不要只檢查首頁或 `/health/ready`：目前 ready 只檢查資料庫，不能證明 worker、引擎或模型正常。

## 第二輪：確認資料真的能使用

1. 工作台查看候選、原始訊息來源，人工審核合成事實。
2. 等待背景發布完成；用 `GET /v1/subjects/{subject_id}/memories` 確認有效記憶。
3. 外部 Agent 呼叫 `POST /v1/context`（`subject_id`、`query`），以不同問句讀回合成事實及來源；再讓 Agent 使用參考內容回答。
4. 上傳一份合成知識文件，授權測試 Agent 存取該空間，確認讀回文件片段；撤銷空間授權後不再返回該文件。
5. 撤銷測試憑證，再次請求必須拒絕。未授權 Subject 不得返回資料。

每步記錄時間、版本、狀態碼、實體／任務 ID 與 request_id；證據不含憑證或私人原文。測試完成後撤銷測試憑證，依約定清理合成資料。

完整流程通過可判定「該雲端環境的指定 Agent 冒煙通過」，不能據此宣稱生產容量、模型品質或災難恢復已達標。
