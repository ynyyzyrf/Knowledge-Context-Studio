# Docker 統一部署（騰訊雲試運行）

這套 Compose 管理前端／API、worker、PostgreSQL 和私有 OpenViking。前端由 API 同源提供；外部 Hermes 只連平台，無需直連引擎。

當前引擎映像已固定為 Linux **x86_64／amd64**。伺服器需已安裝 Docker Engine 與 Compose v2（支援 `up --wait`）；ARM 伺服器不能直接套用本輪驗證。以下預設 SSH 隧道試運行，平台只綁定 `127.0.0.1:18088`，不需要對公網開放 18088、5432 或 1933。

引擎目前是本機驗證過的 native 映像，尚未發布 registry。因此先用下列方式匯出，不能只 clone 後直接 pull 引擎。試運行請預留引擎 4 GiB 上限之外的 API、worker、資料庫及系統資源；實際容量仍需負載量測。

## 1. 在目前 Windows 開發機打包

在 `studio` 目錄執行：

```powershell
.\scripts\export-deploy.ps1
# 已成功建置同一版 Docker 映像時可加 -SkipBuild
```

輸出 `runtime/deploy/kcs-images.tar` 與 `.sha256`，包括平台、固定引擎與 PostgreSQL 映像。排除本機 `.env`、runtime、資料卷、Git 目錄及 node_modules；不傳真實資料庫。

把這兩個檔案傳到雲端，例如（替換你的 SSH 使用者與 IP）：

```powershell
scp runtime/deploy/kcs-images.tar runtime/deploy/kcs-images.tar.sha256 USER@SERVER_IP:~/
```

## 2. 在 Linux 伺服器準備程式與映像

```bash
git clone --branch v1 https://github.com/ynyyzyrf/Knowledge-Context-Studio.git
cd Knowledge-Context-Studio
(cd ~ && sha256sum -c kcs-images.tar.sha256)
docker load -i ~/kcs-images.tar
# 後續初始化、編輯與 Compose 操作使用管理員 shell，讀取受限的設定目錄：
sudo -s
export KCS_POSTGRES_IMAGE=kcs-postgres:16-validated
```

離線匯入以標籤保存 PostgreSQL，所以使用 `KCS_POSTGRES_IMAGE` 選擇匯入的固定映像。若雲端能拉取 Docker Hub，亦可不設此變數，使用 Compose 中固定的 digest。

`export` 設定只適用目前 shell。後續執行命令前需再次設定，或寫入專用、非秘密的 shell 環境設定；不要覆蓋平台 runtime/.env。

## 3. 初始化雲端設定

首次執行，空 runtime 目錄會建立獨立資料庫密碼；已有設定時腳本拒絕覆寫。

```bash
mkdir -p deploy/runtime
docker run --rm --user 0:0 \
  -v "$PWD/deploy/runtime:/app/runtime" \
  kcs-platform:local python deploy/init.py
sudo nano deploy/runtime/.env
```

填入你自己的真實模型設定：

```dotenv
KCS_MODEL_BASE_URL=https://your-chat-provider/v1
KCS_MODEL_API_KEY=填聊天服務金鑰
KCS_CHAT_MODEL=填聊天模型
KCS_EMBEDDING_BASE_URL=https://your-embedding-provider/v1
KCS_EMBEDDING_API_KEY=填向量服務金鑰
KCS_EMBEDDING_MODEL=填向量模型
```

若沿用你已選擇的 HTTP 模型供應商，還需把對應 `KCS_MODEL_HTTP_ALLOWED_ORIGIN`／`KCS_EMBEDDING_HTTP_ALLOWED_ORIGIN` 設成該服務的精確 `http://主機:埠`；不要加入 `/v1`。預設不接受遠端明文模型地址。

保留生成的資料庫密碼、`http://engine:1933` 和精確的私網 HTTP 例外；這個例外只供可信 Docker 網路，不能用來把引擎暴露到公網。`KCS_ENGINE_API_KEY` 由啟動腳本簽發，無須手填。

設定目錄屬於容器 UID 10001、權限 700，檔案 600；編輯時保留所有者與權限。應用容器以該非 root 身份運行。不要提交 `deploy/runtime/`，也不要把原本開發機的 `.env` 覆蓋過來。

## 4. 統一啟動及開通管理員

```bash
bash deploy/start.sh
docker compose -f compose.deploy.yaml run --rm tools \
  python -m kcs.manage bootstrap --email YOUR_EMAIL --team '內部團隊'
```

bootstrap 互動輸入至少 16 字元的管理員密碼；只可對全新資料庫初始化一次。

啟動腳本會依序等待資料庫、暫停舊 API／worker、套用 migration、首次生成引擎模型設定、啟動引擎、連接獨立 publisher 身份、確認真實向量 index，再啟動 API／worker。首次模型配置會實際呼叫向量服務，可能產生供應商費用。中途出錯會停止，不宣稱啟動成功。

API 健康檢查驗證資料庫；worker 是否真的完成任務仍須執行下方冒煙。`restart: unless-stopped` 負責程序退出後重啟，不代表故障恢復驗收已完成。

## 5. 從本機開啟與接入 Hermes

在你的電腦開一個終端，保持 SSH 隧道運行：

```bash
ssh -N -L 18088:127.0.0.1:18088 USER@SERVER_IP
```

瀏覽器進入 `http://localhost:18088`。管理員登入，建立 Agent、Subject、空間授權及有限期憑證。Hermes 的平台地址也設為 `http://localhost:18088`，使用平台 Agent token；不是模型 API key。

若 Hermes 運行在 WSL 或另一個容器，`localhost` 屬於那個環境，需把隧道開在 Hermes 可存取的位置。本文件尚未替 Hermes 安裝工具或 hook；仍須配置它主動呼叫平台 API。

驗收 [雲端冒煙流程](cloud-smoke.md)：身份 → 建會話 → 寫訊息 → 查回原文 → commit → 任務成功 → 人工審核 → 发布 → context 讀回，最後核對撤權。首頁可開不等於 Agent 資料已正確進入。

## 日常操作與更新

```bash
docker compose -f compose.deploy.yaml ps
docker compose -f compose.deploy.yaml logs --tail 100 api worker engine
docker compose -f compose.deploy.yaml run --rm tools python scripts/check-engine.py
# 停機，保留資料卷：
docker compose -f compose.deploy.yaml down
```

更新前先備份；同步新程式與同版映像（離線重新 export/load，或伺服器 `docker build -t kcs-platform:local .`），再執行 `bash deploy/start.sh`。有資料的環境禁止重新執行初始化來換密碼；不要用 `down -v`，它會刪除資料卷。

PostgreSQL、engine 各用獨立 named volume；這是持久化配置，不是已驗收的備份方案。正式對外使用前還要完成 HTTPS、目標環境負載與備份／政策重放恢復驗收。需要網域公開存取時，讓 HTTPS 反向代理轉發本機 18088，設定實際 `KCS_PUBLIC_ORIGIN=https://你的網域`、`KCS_SECURE_COOKIES=true` 後重建 API／worker；不要直接把預設 HTTP 入口開到公網。
