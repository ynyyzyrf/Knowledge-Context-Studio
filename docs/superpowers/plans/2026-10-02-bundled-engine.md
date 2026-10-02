# 內建引擎實作計畫

按已確認的統一交付方案執行，需求見 ../../requirements/2026-10-02-bundled-engine.md。

1. 擴充既有 prepare-engine：無本地 checkout 時自動下載固定 commit，核對 SHA256；統一來源檔案 manifest，保留本地來源模式與 license。
2. 新增 compose.product.yaml 與跨平台 product.py：init/build/up/status/stop/admin，獨立 runtime、project、資料卷；沿用產品 Dockerfile 與 publisher provisioning。
3. 產品配置器讀取單一 settings.env，驗證模型並產生內部配置；重跑保存憑證，embedding 變更阻擋。
4. 提供停寫冷備份及空環境恢復、版本標記與操作說明。
5. 測試來源完整性、初始化覆寫拒絕、模型變更拒絕、內部憑證穩定及命令失敗傳播；在隔離 Docker project 實跑安裝、資料操作、重啟與恢復。

Review focus：未核對來源不得建置；既有配置不覆寫；根憑證不進 API；遷移失敗不啟動寫入者；恢復不能覆蓋現有卷。
