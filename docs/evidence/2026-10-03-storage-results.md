# 自動存儲與完整結果驗收

日期：2026-10-03。範圍：[本次規格](../requirements/2026-10-03-storage-results-scope.md)。交付為本地 v1 工作區 diff，未推送 GitHub、未部署 Zeabur、未更改生產授權。

## 已交付

- Agent → 自動存儲：設定服務對象會話提取後的人工／自動存儲。
- 個人長期記憶 → Agent 授權：擁有者可另行開啟完整正文自動存儲。只影響 memories，不擴大讀權或其他目錄權限。
- 任務中心及 job API：逐條內容、來源、記憶 ID、存儲結果、實際發布狀態；零提取明示 no_durable_facts。
- MCP 0.3.0：新增 kb_job_result，提交回傳查詢方式；長度 128 的冪等 key 不再因派生訊息 ID 超長而失敗。
- 刪除／停用過的來源再次提取時不自動復活；相同文字去重；不做語意猜測覆寫。

## 驗證證據

| 驗證 | 結果 |
| --- | --- |
| `python -m pytest -q` | 112 passed, 9 skipped |
| `pytest tests/test_automatic_storage.py tests/test_jobs.py --postgres -q` | 18 passed；本機 PostgreSQL 隔離 schema，包含 Alembic upgrade |
| `pytest tests/test_concurrency.py --postgres -q` | 4 passed；真實 row lock / SKIP LOCKED |
| `npm --prefix web test` | 3 files / 8 passed |
| `npm --prefix web run build` | TypeScript + Vite 通過；既有大 chunk 提示仍存在 |
| `npm --prefix integrations/mag-kb run check` | 通過 |
| Ruff / git diff whitespace | 通過 |

全套測試的 9 項 skip 包含 PostgreSQL 專用測試及需顯式開啟的 live model/engine 測試；其中 PostgreSQL 並行測試另行執行通過。未宣稱真實模型品質、私有引擎線上發布或 30 Agent 容量已驗證。

新增自動存儲測試先觀察缺少介面／欄位失敗，再實作通過。Node MCP 實際透過 stdio → 本機 HTTP 查詢 pending 與零結果，非靜態工具名比對。獨立審查發現舊來源可能恢復已刪記憶，已以 delete/disable 兩個失敗測試重現並修正，最後全套回歸通過。

## 瀏覽器

使用 Playwright CLI 與獨立 SQLite 合成資料啟動本機 8189，沒有連到生產資料。確認登入、Agent 存儲方式修改後顯示人工審核、任務詳情顯示完整候選正文、來源訊息 ID、正式記憶 ID，以及提取完成但索引仍處理中的區分。登入前 /auth/me 401 為預期未登入狀態；頁面操作未新增 JavaScript 錯誤。

## 上線操作

先部署 API / Worker 及遷移 `91a6d3e8c502`，再更新前端和 MCP 套件、重啟使用它的 Agent 宿主。既有 Agent 與個人授權預設保留人工模式；使用者需在對應設定啟用。自動收集仍未實作，Agent 必須提交資料；個人 sessions 不會自動 commit 或提取。
