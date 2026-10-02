# 安裝完整產品（內建 OpenViking）

一個產品倉庫、一份使用者配置、一個生命週期入口。OpenViking 是隨產品建置、啟動的私有元件，使用者不需要安裝另一份 OpenViking。內部仍採 API、worker、PostgreSQL、引擎四個容器，便於隔離資料與故障。

## 首次安裝

先安裝 Python 3.12+ 與包含 Compose V2 的 Docker。從產品倉庫根目錄執行，Windows、Linux 均使用相同指令：

```sh
python scripts/product.py init
```

只編輯 `runtime/product/settings.env`：產品網址、聊天模型和向量模型服務。OpenAI 相容端點填 API 基底，例如 `https://provider.example/v1`。聊天與向量可使用不同供應商。API key 保留在本機私密配置，勿提交 Git。HTTPS 產品網址必須同時設 `KCS_SECURE_COOKIES=true`。遠端 HTTP 模型端點須設定精確的 allowed origin，延續現有產品校驗。

```sh
python scripts/product.py build
python scripts/product.py up
python scripts/product.py admin --email your-email@example.com
```

管理員密碼由終端隱藏輸入。預設開啟 http://localhost:18088。首次原生引擎建置需要網路及較長時間；無須 Node、Rust、C++ 編譯器或 OpenViking checkout，這些都在鎖定的 Docker 建置環境內處理。

`build` 自動下載 OpenViking commit `20ec78a149a0889a85b038627dddc70b46dceae3`，先核對完整來源 archive SHA256，再產生逐檔 manifest 並於映像中驗證。完整來源封裝、來源版本及 manifest 留在 ignored `runtime/product-builds/engine-*/`，可隨交付保存；映像包含上游 LICENSE。首次安裝不是離線安装。

`up` 自動建立引擎 root/publisher 憑證、探測向量維度、遷移 PostgreSQL，待原生向量索引就緒後啟動 API 和 worker。API 只取得 publisher key，引擎和資料庫都不對主機公開端口。產品帳號、空間權限和治理仍由 KCS 管理。

## 啟停與升級

```sh
python scripts/product.py status
python scripts/product.py stop
python scripts/product.py up
```

停止不刪資料卷。重跑 `init` 拒絕覆寫；重跑 `up` 保留內部憑證及資料。設定缺失、模型不可用、遷移失敗或引擎未就緒時不啟動產品寫入者。更換 embedding 模型或端點會被阻擋，須另行做索引遷移；不能把不同向量空間混在既有索引。

更新前先完成下方備份，再取得新產品版本，執行 `build`、`up`。切換版本會有停機窗口。資料庫已遷移後，不可只改回舊映像當作完整回退。

不同安裝使用不同 `--project` 與 `--runtime`，每次操作都帶相同參數。`--port` 變更也須同步 settings.env 的產品網址。預設 project 為 `kcs-product`，與既有 `kcs-v1` 開發和 `kcs-cloud` 部署分開。不要用新入口接管原有 project 名稱。

## 一致性冷備份與隔離恢復

```sh
python scripts/product.py backup --backup runtime/backups/before-upgrade
python scripts/product.py up
```

備份先停止 API、worker、引擎，再取得 PostgreSQL dump、引擎完整資料卷、配置及雜湊 manifest。備份完成後保持停止，執行 `up` 恢復服務。失敗備份沒有完整 manifest，不可當作可恢復備份。備份內有模型金鑰、資料庫密碼及引擎憑證；只保存在受限路徑或加密備份儲存。

```sh
python scripts/product.py restore --backup runtime/backups/before-upgrade --project kcs-recovery --runtime runtime/recovery
```

恢復只接受空 runtime 與從未使用的新 project（不得有現存容器或資料卷），核對檔案雜湊，使用備份記錄的本機 immutable image ID。跨主機需先轉移對應映像（`docker save` / `docker load`）；此命令不會以其他版本代替缺失映像。恢復後資料庫、API、worker、引擎均保持停止。

`runtime/recovery/restored-images.json` 鎖住恢復版本；此環境不能直接 `build` 覆寫。驗證時先調整 settings.env 的隔離網址，再以同一 `--project`、`--runtime` 和不同 `--port` 執行 `up`。

**這是隔離恢復工具，不是生產切換許可。** 恢復較舊備份後，須核對並重放備份之後的撤銷／刪除政策，才可對原使用者開放。尚未實作自動增量政策回放。既有 Zeabur／本機開發資料不會被此流程自動移動；切換既有環境前需取兩個資料庫／引擎卷的一致性備份，再演練還原與權限驗收。

## 可重跑的交付驗證

`scripts/verify-product.py` 僅用於空的、可丟棄安裝，會建立合成管理員、Agent、空間與文件，並使用真實向量模型（有費用）。透過 tools 容器執行 `seed`，重啟後執行 `read`，最後 `cleanup`。測試狀態只在 runtime，含測試憑證，不納入 Git。

此驗證走真實產品 HTTP、PostgreSQL、worker、原生引擎和模型；不代表外部 Agent 自主操作或完整生產驗收。
