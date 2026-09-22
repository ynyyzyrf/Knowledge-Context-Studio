# 使用者 Context namespace

每個 Knowledge Space 的目錄固定為：

```text
root
├── user
│   └── default
│       ├── memories
│       ├── peers
│       ├── privacy
│       ├── resources
│       │   └── 自訂子目錄
│       ├── sessions
│       └── skills
└── resources
```

`default` 是目前經驗證的使用者在該 Space 的預設上下文別名，與 Subject/Peer 無關。前端固定顯示 default；後端從登入 Cookie 解析 Person ID，不接受客戶端指定私人資料擁有者。相同目錄名稱在不同人／Space 之間互相獨立。

## 目前可用

- 一般上傳預設 `user/default/resources/`，可建立與選擇巢狀目錄。
- 明確選擇「共享知識」才存入 Space 的根 `resources/`；共享上傳仍需要空間編輯權限。
- 具有空間閱讀權的使用者可管理自己的私人文件。其他人包含其他團隊管理員，不能透過文件 ID 查看、刪除或重試你的私人文件。
- 文件列表、Space 文件計數、目錄、預覽及人員搜尋只包含「自己的私人資料＋此 Space 的共享資料」。
- 同 Space、同擁有者／共享範圍、同目錄、同 checksum 及解析類別才去重。
- 自訂目錄是產品中保存的邏輯路徑，不拼接成主機路徑或引擎路徑。禁止 `..`、反斜線、URI、百分號編碼等路徑輸入。

## Agent 私人讀取

新簽發的 Agent Token 綁定簽發操作的登入使用者。現有簽發入口限團隊管理員；一般成員自行簽發私人 Token 的入口尚未提供。不能輸入另一個 Person ID。啟用私人資料讀取需要同時滿足：

1. Token、Agent、團隊有效。
2. Token 綁定的使用者仍啟用，仍具有該 Space 的人員存取權。
3. Agent 具有該 Space 的有效 ACL。
4. 使用者在私人 resources 閱讀區，明確授予該 Agent 此 Space 的私人資源讀取權。

以上任一條件不成立，不返回私人文件。引擎呼叫後、返回正文前重新驗證權限。索引查詢限制在 Space＋Person 根目錄，命中還需核對產品資料庫擁有者、文件狀態、精確片段 URI。

Agent 可用原有 `POST /v1/context` 讀取已授權文件；`documents` 回傳 `scope` 與 `resource_path`。也可只查私人文件：

```http
POST /v1/spaces/{space_id}/user/default/resources/search
Authorization: Bearer <token>
Content-Type: application/json

{"query":"需要查詢的內容","limit":8,"max_chars":12000}
```

此接口不接受 `user/{other_user}` 或 `privacy` 替代路徑；未授權私人 namespace 返回 404。回傳內容為不可信參考資料，不能作為系統指令。

## 遷移與尚未接入的目錄

遷移 `da912601af82` 保留現有文件為共享文件，不自動移動、變更既有索引或認領他人資料。既有 Token 的使用者綁定為空，不能讀取私人文件；輪替也不會自動綁定，需登入後重新簽發。綁定了使用者的 Token 只有該使用者能輪替，避免其他管理員取得另一人的私人身份；管理員仍可撤銷。

`memories`、`peers`、`privacy`、`sessions`、`skills` 目前只建立固定目錄與語義，尚未接入個人資料寫入／讀回，界面明確標示未接入。privacy 不接受文件上傳、不參與普通知識檢索，也尚未提供秘密保存功能。

現有記憶／會話是 Agent＋Subject 模型，保留於既有記憶治理／會話 API，不會假裝成登入使用者的私人記憶，也不會按 Agent 的 Space 授權複製到每個 Space。後續接入個人 memories／sessions 必須新增 Person＋Space 歸屬與完整生命周期驗證。

`POST /v1/context` 明確傳 `space_ids` 時只查指定 Space 的文件，不混入沒有 Space 歸屬的舊 Subject 記憶；空陣列返回空結果。省略 `space_ids` 才保留舊 Subject 記憶檢索及所有已授權 Space 文件（仍有最多 10 個 Space 上限）。

本輪僅本機修改；不代表雲端已發布或整個個人 Context 系統完成。
