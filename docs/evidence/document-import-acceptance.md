# 文件匯入驗收 — 2026-09-22

範圍：本機產品 PostgreSQL、FastAPI、React UI、持久化 worker、固定版本原生 OpenViking 及已配置的真實 BAAI/bge-m3。使用獨立驗收租戶與合成文件，沒有修改使用者模型設定，沒有內置 Agent。

## 自動驗證

- 全套 PostgreSQL 契約測試：**59 passed, 3 skipped**，73.34 秒。見 `document-full-suite.xml`；skip 為需 opt-in 的真實模型測試。此輪之後另加三個文件邊界測試，以下針對套件已包含。
- 最終文件 PostgreSQL 套件：**10 passed**，16.17 秒。見 `document-boundaries.xml`。涵蓋格式與大小、授權、跨空間候選過濾、搜尋途中撤權、删除途中晚到索引、過期租約、PDF 頁碼、PDF／文字去重區分、實際子程序硬記憶體上限、三次暫時失敗耗盡、手動重試及刪除重試不因次數終止。
- 真實文件往返：**1 passed**，10.12 秒。見 `live-documents.xml`。Markdown／文字／PDF 全部經真正解析和 native 向量索引，查詢返回 PDF 與 Markdown 內容，刪除後查詢為空。這輪早於加入 OS 記憶體上限；之後 PDF 解析與硬上限另有針對測試，瀏覽器上傳亦使用最終解析程序。
- 前端 **6 tests passed**，TypeScript／Vite 正式建置通過。仍有主 bundle 大小提示（约 1.23 MB，gzip 386 KB）。
- `ruff check src tests scripts migrations/versions/1db99657541c_durable_document_ingestion.py` 通過。擴展到所有歷史 migration 會遇到既有 import/type-annotation lint；沒有批量改寫歷史遷移。
- Migration 已套用；`alembic check` 無 schema drift；`git diff --check` 通過。

## 真實瀏覽器與執行中服務

1. 正式建置後以 `scripts/start.ps1 -Restart -SkipBuild` 啟動最新版 API／worker；資料庫、前端與實際私有向量 index 就緒。
2. 在隔離驗收租戶的空間，經檔案選擇器上傳 `import-acceptance.md`。列表先顯示處理中，之後已完成、1 個片段。
3. 点擊檔名，預覽 v1、SHA-256 與中文原文：「客服時間是平日 09:00 至 18:00。緊急需求請撥分機 6318。」
4. 桌面版 API 接入測試驗證有限範圍 Agent 憑證，選擇 Subject，以不同問句「琥珀專案最晚可以聯絡客服到幾點？」執行檢索。
5. 瀏覽器顯示來源檔名、v1、片段 1、完整原文及帶 document ID 的參考內容，含 18:00。追蹤 ID `58536bcf664f4f408279a7b321bf8c1c`。
6. 以產品 HTTP API 刪除合成文件，外部 context 立即為空；背景清理完成並核對精確正文／向量消失。驗收租戶與人員停用，憑證撤銷，瀏覽器登出，恢復原 viewport。

瀏覽器覆蓋上傳、狀態、解析預覽及讀回成功路徑；刪除、失敗及重試有 API／worker 測試，未逐項作瀏覽器點擊驗收。窄側欄曾發生自動化定位延遲／導航錯位，桌面尺寸驗收順利；不把本次結果當作完整響應式 UX 驗收。

## 審查與限制

獨立只讀審查發現 checksum 去重需區分解析格式，以及 Windows 解析程序記憶體未硬限制；兩項已修正並通過回歸，複查未發現新的 P1/P2。

Windows 限制依照 [Microsoft Job Object 結構](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_extended_limit_information) 實作；實際子程序分配超限記憶體觸發 `MemoryError`。解析逾時／記憶體限制不等於完整作業系統沙箱。

尚未驗收第三方 Agent 自主工具調用、生產部署、負載、檢索品質指標及備份恢复；不宣稱整個系統已可正式上生產。DOCX、OCR、遠端 URL 及大型批次匯入不在此輪格式範圍。
