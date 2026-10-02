# 個人 Context：memories、sessions、skills、peers

每份資料的所有權固定為 Tenant + Knowledge Space + Person；`default` 從人員 Cookie 或 Agent Token 綁定的 Person 解析。請求不能指定 Person ID。既有 Agent + Subject 會話／記憶保留原資料與接口，不搬移或自動認領。

## 在介面使用

進入空間 → 文件概覽 → user/default → 選擇目錄。各目錄支援關鍵字篩選、底部分頁、建立、閱讀、版本、停用與刪除。

- sessions：建立會話、分頁閱讀／新增訊息；訊息可提交為候選記憶。
- memories：新資料待審核；點進資料 → 編輯／審核 → 已啟用，才可供 Agent 讀取。保留來源訊息與版本。來源會話被刪後顯示不可用，不還原已刪正文。
- skills：保存內容及版本，啟用後可供 Agent 讀取；平台不執行 Skill。
- peers：保存使用者對服務對象、應用或工作區的上下文；它不決定 default 身份。
- privacy：仍不提供密鑰保存或檢索。不要把密鑰填入上述目錄。

每個目錄的「Agent 授權」分別控制讀取／提交。新權限預設全部關閉，原私人 resources grant 不會擴張。所有權限還要求有效 Token、綁定 Person、有效團隊／人員／Space 存取權和 Agent Space ACL。Agent 只能提交候選，不能審核、修改或刪除記憶／Skill／peers；只能追加自己建立的活動會話。

## HTTP 契約

人員基礎路徑：`/v1/tenants/{tenant_id}/spaces/{space_id}/user/default/{kind}`，Cookie + CSRF。

Agent 基礎路徑：`/v1/spaces/{space_id}/user/default/{kind}`，Bearer Token。kind 僅允許 memories、sessions、skills、peers。

| 方法與子路徑 | 用途 |
| --- | --- |
| GET `/entries?offset=0&limit=20&q=` | 列表及 total；q 對標題／說明做字面關鍵字比對，Agent 僅見 active |
| POST `/entries` | 建立；external_id 必填，相同提交重送回同一 ID，內容不一致 409 |
| GET `/entries/{id}` | 完整內容；人員另得最近 50 個版本，Agent 僅見啟用的當前版本 |
| PUT `/entries/{id}` | 僅人員：title、content、status、version；過期 version 返回 409 |
| POST `/entries/{id}/delete` | 僅人員：version；清空正文、歷史版本正文和會話訊息，保留審計／墓碑 |
| GET `/entries/{id}/sources` | 僅人員：記憶所引用且仍可讀的本人物件來源 |
| GET `/entries/{id}/messages?offset=0&limit=20` | sessions 訊息分頁 |
| POST `/entries/{id}/messages` | sessions 追加訊息；external_id、role、content，相同重送去重 |
| GET `/agent-access` | 僅人員：此目錄的 Agent 讀寫權限 |
| PUT `/agent-access/{agent_id}` | 僅人員：can_read、can_write |

建立會話：

```json
{"external_id":"hermes-run-001","title":"週報規劃","content":"本次任務背景"}
```

追加訊息：

```json
{"external_id":"hermes-run-001-message-1","role":"user","content":"希望週報附上來源連結。"}
```

提交候選記憶（source_message_ids 使用上述接口返回的訊息 ID，可省略表示直接提交）：

```json
{"external_id":"hermes-run-001-memory-1","title":"週報偏好","content":"週報需附來源連結。","source_message_ids":[]}
```

建立後 sessions 為 active；其他目錄為 pending。Agent 引用訊息需要 sessions 讀取權，來源亦必須屬於同一 Person／Space。版本歷史最多 100 次、每目錄最多 1,000 筆未刪資料、每會話最多 1,000 則訊息；正文 40,000 字元、每則訊息 16,000 字元。

## 既有 context 與 Hermes

`POST /v1/context` 保留既有 subject_id 與文件／舊記憶契約。`personal_context` 依指定／授權 Space + Token Person + 各目錄讀取 grant，召回已啟用 memories／skills／peers。文件／舊記憶與個人資料分配獨立候選名額；兩者都有命中時，個人資料先保留約三分之一名額／字數，再共享餘量。三分之一是軟預算：至少一筆可完整容納的個人命中可突破此比例；limit=1 時個人命中優先。不截斷正文；含標頭與分隔符的 context 不超過 max_chars。

個人資料使用既有 Embedding provider 及 PostgreSQL 版本化向量，未寫入 OpenViking；原文件／Subject 記憶引擎不變。背景 worker 自動為已啟用資料補索引，正文按 2,000 字元分段，最長正文亦包含尾段。模型指紋包含 endpoint、模型名稱與演算法版本，不含金鑰。修改、停用及刪除清除向量和租約；晚到結果不能重新啟用舊版本。

查詢詞項支援英文單詞／數字與中文雙字詞，與 cosine 語意排名經 RRF 融合。語意門檻目前為 0.45，仍需以業務驗收集校準。授權資料分批讀取，每通道只保留前 100 個可容納候選，不以「最新 100 筆」取代相關性。所有網路呼叫之後再重新查驗授權及當前版本。

回應的 `personal_context_retrieval` 為 `keyword` 或 `hybrid`；`personal_retrieval` 提供 `degraded_reason`、`readable_count`、`indexed_count`，只統計當前有權讀取的資料。無模型／索引待建立／provider 失敗時降級到詞項匹配。新舊配置不混用向量。`kb_personal_list?q=` 仍是列表字面篩選，混合檢索使用 `kb_context`。

條目 `indexing` 提供 pending／running／ready／retry／failed／inactive 及固定錯誤代碼。worker 租約為模型 timeout＋30 秒，失敗退避 10／20／40 秒，最多自動三次。擁有人可在詳情點「重試索引」，或 `POST .../entries/{id}/reindex` 傳 `{ "version": 當前版本 }`；不變更正文版本，Agent 沒有此接口。需運行 worker，只有 API 不會建立索引。模型變更自動補建；使用新模型前舊向量不參與。

空 `space_ids` 不返回個人資料；sessions 必須用明確接口讀取，不混入普通知識回答。會話不自動抽取記憶，可由外部 Agent 提交候選或由人員在介面選取訊息。常駐偏好、事實衝突治理與跨文件 Wiki 見[分階段需求](requirements/2026-10-02-context-quality.md)。

Git 倉庫內 `integrations/mag-kb` 提供 Hermes MCP 0.2.0；個人工具為 `kb_personal_list`、`kb_personal_get`、`kb_personal_submit`、`kb_personal_messages`、`kb_personal_append`。舊工具仍採原 Subject 模型。切換 Hermes command args 至這份 server.mjs 後，保持原 MAG_KB_BASE_URL／MAG_KB_TOKEN 環境變數。雲端 API 必須先部署本版本與遷移 `4c2f8a10d301`；本機舊 `mcp/mag-kb` 未自動覆蓋，Hermes 設定也未自動切換。

## 部署與驗證邊界

需要先執行 `alembic upgrade head` 再啟動 API 及 worker。個人目錄基礎遷移新增四張表；本次 `4c2f8a10d301` 在 namespace_entries 新增向量及租約欄位，不移動現有文件／記憶。降版移除派生向量，正文不受影響。所有寫入及授權變動沿用租戶政策鎖，所有者修改帶版本檢查；讀回重新驗證當前授權，刪除及停用立即排除。備份／交易日誌的物理抹除不在 API 刪除承諾內。

本輪先在本機驗證，不等於已發布雲端或 Hermes 自主接入已驗收。
