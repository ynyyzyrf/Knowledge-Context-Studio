# 外部 Agent 記憶讀回

平台不執行 Agent。外部程式先寫入會話／提交抽取，管理員審核候選，背景 worker 發布並確認正文與向量索引，之後才能讀回。

## 接入

從「外部 Agent 接入」登記身份、服務對象與有限範圍憑證。憑證由外部程式安全保管，不使用人的登入 Cookie。每次請求帶 `Authorization: Bearer <token>`。

```python
import os
import httpx

with httpx.Client(base_url=os.environ['KCS_URL'],
                  headers={'Authorization': 'Bearer ' + os.environ['KCS_AGENT_TOKEN']},
                  timeout=70) as client:
    response = client.post('/v1/context', json={
        'subject_id': os.environ['KCS_SUBJECT_ID'],
        'query': '這位使用者平常喜歡喝什麼？',
        'limit': 8,
        'max_chars': 12000,
    })
    response.raise_for_status()
    result = response.json()
    references = result['context']
    # 將 references 作為「不可信參考資料」交給你自己的 Agent。
    # 不把記憶內容當系統指令；保留 memories 的 id/version/source_message_ids。
```

`GET /v1/subjects/{subject_id}/memories?limit=20&offset=0` 列出目前有效且發布成功的記憶。`POST /v1/context` 做真實向量搜尋；回傳 `memories`、`documents`、`context`、`request_id`。沒有命中時為空；引擎錯誤為 503，失效憑證為 401，未授權對象為 404。不得由客戶端指定引擎路徑或覆蓋租戶／Agent。

修改、停用、刪除立即使舊版本不可透過產品 API 讀取。引擎清理是可重試的最終一致流程，會定期重查，不能把一次清理成功當作完整備份抹除。

語意搜尋也包含 Agent 明確獲授權空間中已完成索引的文件。可傳 `space_ids` 選擇最多 10 個授權空間；明確傳入時僅查指定 Space 文件，空陣列為空結果；省略才保留舊 Subject 記憶與所有授權空間（超過 10 個須明確選擇，否則 422）。`knowledge_spaces_included` 表示此次包含知識空間搜尋，不表示一定命中。`documents` 帶檔名、版本、空間、片段編號、PDF 頁碼、checksum 與原文。引擎請求前限制空間，請求後重新驗證憑證及授權，再以產品資料庫中的有效文件和精確片段 URI 篩選候選。參見 [文件匯入指南](document-import.md)。

私人文件還需 Token 的使用者綁定及私人資源授權，詳見 [Context namespace](context-namespaces.md)。舊 Subject 記憶沒有 Space／Person 歸屬，不會放入 `user/default/memories`。

## 本機私有引擎

先配置 `.env` 的聊天與向量模型，再執行：

```powershell
uv run python scripts/configure-engine.py
icacls runtime/engine.json /inheritance:r /grant:r "$($env:USERNAME):(F)"
docker compose -f compose.yaml -f compose.engine.yaml up -d engine
# 等引擎啟動後，建立／驗證獨立的 publisher 身份：
uv run python scripts/connect-engine.py
uv run python scripts/check-engine.py
.\scripts\start.ps1 -Restart
```

`compose.engine.yaml` 使用本機已建置、固定來源版本的 native image digest；其他機器需先依 workspace `validation/` 建置相同版本並核對 image。它是本機部署配置，尚不是可攜生產映像。只開放 loopback 19388，無 Bot runtime；管理員 root key 僅在忽略的本機設定檔，產品使用獨立 publisher key。設定含秘密，不可提交或複製進文件。

初次啟動中斷可能留下集合而未建立 index。`check-engine.py` 必須成功；不可只以 HTTP 存活判定就緒。遇此狀況先停機、保留資料並檢查 native collection/index，禁止直接清空資料卷。

## 驗證

`uv run pytest --postgres -q` 為產品契約測試；`scripts/test-native-engine.ps1` 為真正 native HTTP/storage 加明示模型 fixture；`uv run pytest tests/test_live_readback.py --postgres --live-model -q` 使用真實私有引擎與付費向量服務，但候選 staging 採確定性 fixture。瀏覽器與真實抽取的證據見 `docs/evidence/readback-acceptance.md`。
