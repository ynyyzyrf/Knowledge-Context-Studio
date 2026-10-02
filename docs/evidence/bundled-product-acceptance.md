# 內建引擎交付驗收

日期：2026-10-02。對應 [需求](../requirements/2026-10-02-bundled-engine.md)、[操作指南](../bundled-product.md)。

## 已取得證據

| 項目 | 結果 |
| --- | --- |
| 自動來源取得 | 未傳 --source，從固定 GitHub commit 下載，archive SHA256 `62a5346c445e17333f5307e1e2df5bdfdad0e9fcc19c46843d60ac664f956006` 通過；2,072 個檔案再與固定本機 Git archive（core.autocrlf=false）逐一比對一致 |
| 完整建置 | `python scripts/product.py build` exit 0；包含產品前端／後端與 Rust/C++ 原生引擎，沒有使用本機 OpenViking checkout 作建置輸入 |
| 新引擎映像 | `sha256:1dabc194be99e06ede038bd064581a00b8c50cb7e2d24b37ec243272c6b063af`；容器實際 image ID 相同 |
| 最終產品映像 | `sha256:ece9eeff0461324b66b9772929c301b9d480984ebbc90ecb4bf9ac00c3316441`；包含交易回應時序修正 |
| 空環境啟動 | `kcs-product-final` 新 project／資料卷；自動生成內部配置與 publisher key；真實模型探測 1024 維；全部 Alembic 遷移到 4c2f8a10d301；API 18090 就緒，引擎 1933 無 host port binding |
| 真實資料流程 | HTTP 合成文件上傳 → 真實 worker 解析／原生索引 → Agent 憑證查詢返回 18:00 原文；撤權後文件不可見，恢復授權後可見 |
| 重啟 | 重建 API／worker／引擎後上述讀回通過；.env、engine.json、postgres.env SHA256 前後相同，內部憑證未重置 |
| 冷備份 | 停 API／worker 後停引擎；PostgreSQL dump、engine.tar、私密配置、各檔雜湊及實際 immutable image ID 一起保存；備份不含公開示例憑證 |
| 隔離恢復 | 新 `kcs-product-recovery` project／新卷；使用備份記錄的三種 image ID 還原，保持停止；調整隔離網址後在 18091 啟動，登入、文件與來源讀回、撤權／恢復、刪除後無結果及背景清理完成 |
| PostgreSQL 全套 | `uv run pytest -q --postgres --tb=short`：108 passed、4 skipped，271.73 秒；未開啟 pytest --live-model。上述 Docker smoke 另外使用真模型，不混算案例數 |
| 部署單元＋交易回歸 | 11 passed；包含初始化覆寫拒絕、來源校驗失敗、模型變更拒絕、配置／憑證穩定、遷移失敗停止後續操作、備份損壞與非空恢復拒絕、回應前交易提交 |
| 靜態檢查 | Ruff 通過；git diff --check 通過（Windows LF/CRLF 提示） |

## 驗證中發現與修正

1. 第一次以既有同版本引擎映像預檢啟動及 seed 成功。其後使用自動建置的新映像與全新資料卷，首次 seed 在「恢復授權後立即讀回」失敗，並未忽略此失敗。
2. 連續六次真實 HTTP 診斷有五次出現第一次恢復讀回為空、第二次成功。ASGI send 邊界回歸測試再現：200 response headers 發出時，另一個資料庫連線仍讀到舊授權。
3. 根因是 get_db 的 yielding dependency 使用 request scope，交易在回應後才提交。統一改為 `Depends(get_db, scope="function")`，在成功回應送出前完成提交；FastAPI 最低版本與既有 lock 的 0.141.1 對齊，沒有升級鎖定套件版本。回歸先 RED 再 GREEN，真實讀回與恢復測試其後通過。
4. 根使用者執行內部 publisher 配置時，dotenv 原子寫入會改變檔案擁有者；現在保存 0600 與產品 UID 10001，使非 root API 可讀，API 仍不取得引擎 root key。
5. 生命週期停止順序為先 API／worker、再引擎、最後資料庫；回歸測試先確認舊同時停止方式失敗，再修正。

## 證據位置與邊界

詳細輸出保存在 ignored runtime：`bundled-build.log`、`bundled-platform-final.log`、`bundled-up-final.log`、`bundled-final-seed.log`（保留原失敗）、`bundled-final-restart.log`、`bundled-backup.log`、`bundled-restore.log`、`bundled-recovery-up.log`、`bundled-recovery-smoke.log`、`bundled-postgres-tests.log`。私密備份與測試憑證未納入 Git。

驗收為 Windows 主機上的 Docker Linux amd64 與合成資料；未在另一台實體乾淨主機驗證，也未測 arm64、离線首次建置或第三方 Agent 自主工具使用。恢復沿用本機 immutable 映像，跨主機仍須轉移映像。這是統一交付與隔離恢復驗收，尚未實作備份後撤權／刪除政策的自動回放，不代表生產災難恢復通過。

所有新驗證 project 已停止，資料與備份保留。原 localhost:8088 開發環境、既有雲端服務及既有資料未遷移。此輪尚未提交／推送或部署到雲端。
