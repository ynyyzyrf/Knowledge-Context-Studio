# 個人 Context 品質實作計畫

> 執行：本會話按使用者「先寫需求，再繼續執行」指令連續完成，採 executing-plans／test-driven-development。保留現有未提交修改，不自動提交整個工作區。

**Goal:** 已授權個人記憶可語意召回，並有獨立結果和字數預算。
**Architecture:** 既有 provider 背景建立版本化向量，查詢融合詞項與向量排名，產品在回應前重驗授權。原 OpenViking 文件路徑維持。
**Tech Stack:** FastAPI、SQLAlchemy、Alembic、PostgreSQL、既有 ModelService、Node MCP。
**Spec:** [需求文檔](../../requirements/2026-10-02-context-quality.md)

## Global Constraints

- 不替換上游或 Agent Runtime；不覆寫原有未提交工作。
- 人工審核、Tenant／Person／Space／Agent／Subject 邊界不變。
- 網路 I/O 在交易外，返回前政策鎖重验。
- 第一階段不包含常駐偏好／Wiki／正式部署，不把合成模型當品質證據。

## Review Focus

- 背景租約過期及改版／刪除競態：test_personal_index_lifecycle。
- 查詢途中模型改版、權限變動及非有限向量：test_personal_retrieval。
- 長正文／文件先滿／空範圍／limit=1：test_context_budget。
- 模型未配置及失敗：詞項降級、不可洩漏 provider 訊息。
- MCP 跨進程讀回與撤權：test_personal_mcp。

## Task 1：召回與預算

- [x] 先新增純算法及 HTTP 行為測試，運行並確認現有實作失敗。
- [x] 建立 `src/kcs/personal_retrieval.py`：分詞、詞項打分、向量 cosine、RRF 與有界兩組分配。
- [x] 修改 `src/kcs/context_routes.py`：授權候選、問題向量化、最終重驗、模式診斷及兩組預算。
- [x] 跑針對測試。Expected: 改寫／擠壓／生命週期案例通過。

## Task 2：持久向量生命週期

- [x] 先測未審核不索引、改版／刪除中斷、租約、退避及模型指紋變更。
- [x] `NamespaceEntry` 加索引欄位及 Alembic 遷移；`personal_index.py` 實作 `run_one(database, settings, model_factory=None)`，重用既有 provider。
- [x] 在 `personal_context_routes.py` 清除過期向量及提供擁有人索引重試；`worker.py` 接入。
- [x] 跑 worker 與 HTTP 契約。Expected: 索引版本一致、過期結果不復活。

## Task 3：MCP、驗證與交付

- [x] 新增真實 Node stdio→測試 HTTP 的讀取／撤權契約；明示模型替身範圍。
- [x] 運行完整測試、PostgreSQL 隔離 schema 遷移及 lint；可用時獨立真實 Embedding 改寫驗證。
- [x] 更新個人 Context 文檔、MCP 說明、PROGRESS 及證據。
- [x] 獨立審查本次 diff，修正重要發現；保留沒有完成的實際 Agent／部署驗收限制。

## 執行紀錄

- 起始狀態：個人 Context、MCP 與 UI 已有未提交改動。選擇原 checkout 疊加最小修改，不搬移或清理。
- 前置檢查：Task 1 讀取 Task 2 的索引欄位；先寫全部針對失敗測試，再補 schema／索引／檢索，最後做整合。
- Task 1/2：初次 7 項測試失敗，包含既有中文問句無法召回的 HTTP 重現；實作後針對組通過。擴充租約、長文、跨人員、模型切換及 MCP 契約。
- Ruling：Agent 重建索引無此方法，實際 HTTP 契約為 405；原測試誤預期 404，已按既有路由相容性修正。兩者皆不允許操作，未擴張權限。
- Ruling：讀取資料按批串流，每通道保留前 100 個可容納候選；不按近期截斷整體知識，避免大量向量同時載入記憶體。
- Ruling：保留既有未提交工作，未將整個 checkout 自動提交；所有本次修改及證據以工作檔交付。
- Final review：獨立只讀 reviewer 發現長個人記憶可能被文件擠掉、舊模型索引狀態誤報 ready。兩個案例均新增測試確認 RED，再修正為 GREEN；針對組 14 passed。無其餘提出的 minor。
- Final validation：PostgreSQL 全套 96 passed／4 skipped。後續真實模型發現 RRF 同分按 ID 排名不穩，固定案例 RED→GREEN，改成同分優先語意相關度；PostgreSQL 針對＋真實模型 8 passed。最終 SQLite 全套 92 passed／9 skipped。前端 6 passed/build、Ruff、Alembic check、Node syntax 通過。
- 本地套用遷移並以最終程式重啟 API／worker。證據及未驗證範圍：[context-quality-acceptance.md](../../evidence/context-quality-acceptance.md)。
