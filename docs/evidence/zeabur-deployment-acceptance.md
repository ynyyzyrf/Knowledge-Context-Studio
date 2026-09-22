# Zeabur 雲端部署驗收

日期：2026-09-22。**四服務部署及受控雲端冒煙驗收通過；尚未完成 Hermes 實際客戶端與生產運維驗收。**

## 部署範圍

- 專案 `Knowledge-Context-Studio`：`6ab1e93fafd7153d77b417e2`。
- production environment：`6ab1e93f36d2a6cac45bdab1`。
- Zeabur 管理的 Tencent Jakarta 8C / 16GB 主機。
- 公開入口 `https://kcstudio.zeabur.app`；產品初始部署 commit `fc43d513e2c34360e577cbb1f01888920ecfe70b`。
- OpenViking 來源 `20ec78a149a0889a85b038627dddc70b46dceae3`，版本 `0.4.19.dev20260921`。

| 服務 | Service ID | 本輪配置 |
| --- | --- | --- |
| knowledge-context-studio | `6ab1e95eafd7153d77b417f3` | web 8088、HTTPS、secure cookie、遷移後 exec 啟動 API |
| postgresql | `6ab1e9b8e4a4a25395d1c975` | 沿用既有 PostgreSQL 18 與資料卷，應用走私網 |
| kcs-worker | `6ab20641e4a4a25395d1d43b` | 同一產品版本，獨立 `python -m kcs.worker` |
| kcs-openviking | `6ab2063dafd7153d77b4251e` | 私有 1933、`engine-data:/data`、獨立 root key、Bot 關閉 |

## 已取得的雲端證據

| 檢查 | 結果 |
| --- | --- |
| 首頁、JS、CSS、`/health/ready` | HTTP 200 |
| 首次管理員初始化與登入 | HTTP 200；實際瀏覽器顯示雲端工作台 |
| 人員 Cookie | Secure、HttpOnly |
| 未授權外部 API | HTTP 401 |
| 缺少 CSRF 的管理寫入 | HTTP 403 |
| Bearer 存取未授權 Subject 的記憶／context | HTTP 404 |
| Agent 身份、會話建立、訊息寫入／讀回 | 通過 |
| 相同 message_id 重送 | 原 message ID 不變，會話只有 1 則訊息 |
| 真實聊天模型抽取 | 任務 succeeded、attempt=1、error_code=null |
| 候選來源追溯 | 1 個候選，source_message_ids 指向剛寫入的原文 |
| 真實向量模型 | 從雲端呼叫成功，1024 維 |
| API 重啟 | 原會話仍可讀，PID 1 為 uvicorn 主程序 |
| 審核記憶後的引擎發布／context 讀回 | 通過，返回核准記憶及 jasmine tea 原文 |
| 文件上傳、worker 解析、索引與 context 讀回 | 通過，Markdown 1 個 chunk，返回 18:00 原文 |
| 引擎重啟後資料仍可讀 | 05:36:02 UTC 新容器啟動後，記憶及文件 context 再次通過 |
| 空間撤權／恢復授權 | 撤權後無文件，恢復後可讀原文 |
| 內容刪除／背景清理 | context 不再返回；文件 source 與 chunk 文字清空，記憶 deleted，背景任務完成，對應引擎內容不存在且向量 count=0 |
| 憑證撤銷 | 原 Bearer 返回 401；合成測試 Agent 已停用 |

合成測試會話：`a9eb7cd9c2b04437a20bb644263b7202`。
抽取任務：`ce5622604359414993acd306f99d1a96`。
文件：`0fbd1d8502aa407091abab8cd465d095`。測試後保留審計、原會話與空間紀錄，
測試文件及記憶已刪除，憑證已撤銷；未刪除其他使用者資料。
證據只描述合成資料；不包含密碼、Bearer token、模型金鑰或資料庫密碼。

## 本輪故障與修正

1. 原平台缺少 `KCS_DATABASE_URL`，且 Zeabur 轉發埠為 8080、API 監聽 8088。
   已解析 PostgreSQL 自身的變數引用，填入驅動相容的私網 URL，修正轉發埠與啟動命令。
2. 引擎首次建置 `6ab2067dd85c15aa90a087cf` 在 CMake 生成階段失敗：缺少
   `third_party/leveldb-1.23/helpers/memenv/memenv.cc`。
   該檔案存在於固定來源與本機準備目錄；雲端散檔建置未取得完整來源。
   目前證據定位到來源傳遞／建置邊界，尚未確認具體由 CLI 或服務端哪一層過濾造成。
   修正為單一來源 tar 加完整 SHA-256 manifest。已核對雲端收到的 tar 內確實包含該檔，
   並以相同 tar 在本機 Linux 執行 CMake，設定／生成皆成功。
3. 第一次封裝目錄上傳 `6ab20b86c71834649e111835` 被自動判成 static。
   已設定 `ZBPACK_DOCKERFILE_PATH=Dockerfile` 與 `zbpack.json`，
   最新部署 `6ab20c5cc71834649e111881` 已確認 planType=docker，
   05:31:51 UTC 建置及映像上傳成功，05:33:19 UTC 啟動，私有原生向量索引檢查通過。
   不以服務頁的 RUNNING 代替最新部署成功：建置期間可能仍顯示舊容器。

`deploy/zeabur/prepare-engine.py` 從固定 Git commit 產生來源封裝、2,072 個來源檔案雜湊與 Docker 配置。
配方的來源 manifest 與本次部署逐項相同；原生建置限制 2 個並行工作，四個基礎映像 digest 已固定。

## 判定邊界

本輪是受控 HTTP 測試客戶端與實際瀏覽器驗證，尚未讓本機 Hermes 真正發出請求。
即使完整冒煙通過，正式生產仍需獨立完成容量、監控告警、備份恢復與安全驗收。
聊天供應商目前使用既有 HTTP gateway；正式環境的鏈路保護仍需確認。
