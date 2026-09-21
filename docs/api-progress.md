# 已實作 API 與邊界

所有人員管理請求使用登入 Cookie；變更請求另需 `X-CSRF-Token`。Agent 使用產品層 Bearer token，身份由 token 決定。

| 路徑 | 功能 | 權限 |
|---|---|---|
| `/v1/auth/login`, `/me`, `/logout` | 登入、帳號資訊、撤銷目前登入 | 人員 |
| `/v1/tenants/{tenant}/members` | 成員列表、新增、停用 | 管理員變更，成員可看列表 |
| `/v1/tenants/{tenant}/agents` | 建立、列表、啟停 Agent | 租戶管理員 |
| `/v1/tenants/{tenant}/agents/{agent}/subjects` | 建立、列表、啟停服務對象 | 租戶管理員 |
| `/v1/tenants/{tenant}/agents/{agent}/credentials` | 簽發、列表、撤銷與輪替 | 租戶管理員；原文只在簽發時返回 |
| `/v1/tenants/{tenant}/spaces` | 建立、列表、讀取空間 | 管理員建立；普通成員按空間授權 |
| `/v1/tenants/{tenant}/spaces/{space}/people/{person}` | 設定人員 viewer/editor 授權 | 租戶管理員 |
| `/v1/tenants/{tenant}/spaces/{space}/agents/{agent}` | 設定 Agent 讀取授權 | 租戶管理員 |
| `/v1/agent/me` | 憑證身份及當前 Subject／空間授權 | Agent |
| `/v1/sessions` | 建立與列出有權查看的會話 | Agent＋憑證 Subject 範圍 |
| `/v1/sessions/{session}/messages` | 加入訊息、按序讀取 | 原會話 Agent＋當前 Subject 授權 |
| `/v1/sessions/{session}/commit` | 提交持久化提取任務，返回 202 | 原會話 Agent＋當前 Subject 授權 |
| `/v1/jobs/{job}`、`/{job}/retry` | 任務狀態與明確重試 | 任務 Agent＋當前 Subject 授權 |
| `/v1/tenants/{tenant}/jobs` | 分頁查看租戶任務 | 租戶管理員 |
| `/v1/tenants/{tenant}/audit` | 近期操作稽核，不含訊息正文／憑證 | 租戶管理員 |

憑證輪替沿用原到期日與服務對象範圍，同一交易撤銷舊憑證。停用 Agent 或租戶會拒絕其憑證；停用 Subject 會立即移出其有效授權。

新空間的 `sync_state=pending` 表示尚未完成引擎同步，不能解讀為已可用的檢索資料。當前尚無正式內容發布或 context 入口。

會話建立需要 `subject_id` 和 `idempotency_key`。訊息需要 `message_id`、`role`（user/assistant）及 `content`；相同識別碼和相同內容會返回已保存物件，衝突返回 409。會話列表支援 offset/limit，訊息支援 after_sequence/limit。

此文件記錄已實作範圍；完整契約以啟動後的 OpenAPI 為準，生產驗收範圍仍依工作區 `docs/production`。
