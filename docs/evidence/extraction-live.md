# 真實模型與 worker 驗證（2026-09-21）

使用本機已配置的 `metis-coder`，測試資料為合成偏好句子；PostgreSQL 使用專用測試庫的獨立 schema，透過正式 Alembic 遷移建立。沒有使用產品資料或真實個人資訊。

執行：

```powershell
uv run pytest tests/test_jobs_live.py --postgres --live-model -q
uv run pytest tests/test_jobs_live.py::test_real_model_worker_process_stages_synthetic_fact --postgres --live-model -q
```

- 第一次：程序中斷驗證通過；真實提取在 60 秒逾時，任務狀態為 retry、error_code 為 model_timeout。整次結果 1 passed / 1 failed，耗時 64.65 秒。
- 第二次單獨重跑真實提取：1 passed，耗時 5.42 秒。獨立 `python -m kcs.worker --once` 成功產生候選；來源 ID 必須指向提交前的合成訊息，狀態仍為 candidate。
- 中斷案例由獨立子程序取得任務後 `os._exit(73)`，父程序確認 running/attempt=1 已持久化；把測試租約期限提前後，另一個執行者可接手並完成。這不是模型呼叫中途殺程序、主機斷電或完整災難恢復測試。

這些證據證明一筆真實提取可完成，並觀察到一次實際逾時。它們不證明長期穩定性、提取品質指標、向量索引、可召回有效記憶、完整 UI 或生产就緒。

候選只寫入產品 staging table；尚未建立任何引擎發布路徑。外部模型原始錯誤及金鑰不進入任務狀態或本文件。
