# 個人 Context 品質第一階段驗收

日期：2026-10-02。範圍：[需求 FR-01～05／AC-01～08](../requirements/2026-10-02-context-quality.md)。

## 已執行證據

| 檢查 | 命令／方法 | 結果與邊界 |
|---|---|---|
| 原問題重現 | 初始 personal_retrieval／personal_index 測試 | 7 failed；包含中文改寫 HTTP 得到空 personal_context，先 RED 再實作 |
| 針對安全與預算 | personal_retrieval、personal_index、personal_mcp | 14 passed（審查修正後、排序同分修正前）；涵蓋改版／刪除晚到、租約恢復、跨人員、模型更換、撤權、長文、配額及 MCP |
| PostgreSQL 全套 | `uv run pytest -q --postgres --tb=short` | 96 passed、4 skipped；獨立 kcs_test schema 逐個跑全部 Alembic 遷移；未啟用 live-model |
| 最終本機全套 | `uv run pytest -q --tb=short` | 92 passed、9 skipped；包含最終同分排序修正；SQLite 測試替身不替代 PostgreSQL 結果 |
| 真實模型＋PostgreSQL | `uv run pytest -q tests/test_personal_retrieval.py tests/test_personal_live.py --live-model --postgres --tb=short` | 8 passed；含排序同分修正及三筆合成記憶改寫 top-1 |
| 前端 | `npm run build`；`npm test -- --run` | TypeScript／Vite 通過，6 tests passed；既有大 bundle 警告 |
| 靜態及遷移 | `uv run ruff check src tests migrations/versions/4c2f8a10d301_personal_embeddings.py`；`uv run alembic check`；`node --check integrations/mag-kb/server.mjs` | 通過，No new upgrade operations detected |
| 本地啟動 | `scripts/start.ps1 -Restart -SkipBuild` | 本地升級至 4c2f8a10d301，資料庫／API／前端 ready、worker 運行；只是可用性檢查，不冒充業務 E2E |
| 瀏覽器 | Codex browser 開啟 http://localhost:8088 | 登入頁載入；未測登入後新索引介面 |

完整測試輸出在本地 ignored `runtime/context-quality-postgres-final.log`。沒有輸出模型密鑰或憑證。

## 真實模型品質案例與修正

合成資料：週報附來源、出差避開夜間航班、花生過敏；每筆使用不同問法查詢，limit=1。向量供應商是真實設定，產品 API／資料庫是真實程式；OpenViking 文件檢索為測試替身，測試僅主張個人召回路徑。

第一次 SQLite 模型測試通過，之後 PostgreSQL 真實模型測試有一次 top-1 失敗。定位到 RRF 兩通道相反排名時總分相同，最後按隨機 ID 排序，可能讓「安排午餐」選到「出差安排」。固定 ID 的最小案例重現 RED。修正：相同通道分數共用排名，融合分數相同時先比語意相關度，再比詞項相關度，最後才用 ID 保持穩定。其後 PostgreSQL＋真實模型組 8 passed。

這是三個合成情境，不能推論 30 題真實業務品質達標，也沒有建立費用、延遲或負載基準。

## 獨立審查

只讀 reviewer 找到兩項 P2：長個人記憶超出三分之一軟預算會被擠掉；舊模型向量的 UI 狀態誤報 ready。兩項先增加失敗測試，再修正。沒有遺留 reviewer 提出的 minor。

## 限制與交付狀態

- 本地代碼、遷移、API／worker 已更新；沒有 Git 提交／推送或雲端發布。原有未提交修改保留。
- Node MCP 測試是真正 stdio→loopback HTTP，不包含 Hermes 自主選工具／任務完成。
- 新索引為應用內受授權範圍的 cosine 排名，按批讀取，每通道保留前 100 個可容納候選；大規模吞吐與語意門檻 0.45 仍需業務量測。
- provider 失敗或無可用向量降級為詞項檢索；完整文件引擎故障仍依既有 Context API 回傳 503。
- 常駐偏好、候選抑制／到期整理、跨文件 Wiki 留在後續需求階段。
- TestClient 依賴有兩個既有 deprecation warnings；未為本次任務升級依賴。
