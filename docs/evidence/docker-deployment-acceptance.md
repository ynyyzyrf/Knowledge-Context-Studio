# Docker 部署配置驗證 — 2026-09-22

環境：本機 Docker Desktop 的 Linux amd64 容器。使用獨立 `kcs-cloud` Compose 專案、資料庫及引擎卷，不修改原有 localhost:8088 的開發服務。這不是騰訊雲實機验收。

## 已驗證

- 多階段 Docker build 成功：Node 正式前端建置、Python 3.13／uv frozen 依賴安裝，執行身份為 UID/GID 10001。Node、Python、uv 基礎映像固定 digest。
- `compose.deploy.yaml config --quiet`、`bash -n deploy/start.sh`、Ruff 及 diff 格式檢查通過。Shell 檔案使用 LF。
- 新增精確私網 HTTP 引擎例外：默认拒絕 `http://engine:1933`，顯式設定後接受；不同主機、埠及帶路徑地址仍拒絕。引擎／模型設定針對測試共 11 passed。
- 初始化獨立雲端設定；Compose 實際啟動 PostgreSQL，從空庫套用所有正式 migration，啟動私有 native 引擎。真實模型維度探測為 1024，publisher 簽發與實際向量 index 檢查成功。
- API 正式前端可提供服務，資料庫健康檢查通過；worker 運行。只有 `127.0.0.1:18088` 映射到主機，PostgreSQL／engine 未映射主機埠。
- 透過真正 HTTP 登入合成帳號、建立有限範圍外部身份、上傳 Markdown。容器 worker 使用 Linux 隔離解析器完成索引，真實 context 檢索返回 18:00 與文件來源。
- 外部 Bearer 呼叫者建立會話、寫入訊息、查回原文；同一 message_id 重送後仍只有一則訊息。
- 刪除文件後外部 context 立即為空；背景清理完成、產品原始資料清空、精確片段向量數為零。驗收人員／租戶停用、憑證撤銷。
- `scripts/export-deploy.ps1 -SkipBuild` 成功匯出三個映像與 SHA-256 校驗檔。設定、資料卷不在匯出範圍。驗收後 `docker compose down` 停止測試容器，保留測試卷。

## 限制

Windows 主機上逐項執行了與 `deploy/start.sh` 相同的 Compose 啟動步驟；Bash 腳本只做語法驗證，尚未在騰訊雲 Linux shell 整段執行。Linux 主機上的檔案所有權／SSH／網域、CPU 架構與容器資源須在目標機確認。

本輪沒有把映像包載入第二台機器，也未完成 HTTPS、公網、Hermes 工具接入、真實記憶抽取／審核全流程或備份還原。本機容器驗證不代表生產上線驗收完成。引擎目前仍需離線匯入固定映像，尚未發布 registry。
