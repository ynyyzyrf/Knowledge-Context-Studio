# AgentCombo 四種 Harness 的 KCS 接入設計

日期：2026-10-04。狀態：使用者已確認依官方方式直接實作，排除 AgentCombo。KCS 配置適配、共用指南與本地驗證已完成；尚未完成四種 Harness 的實際模型調用驗證。詳見 ../evidence/2026-10-04-harness-adapters.md。

## 目的與範圍

使用者要求支援 Codex、Claude Code、OpenClaw、Hermes。使用者沒有 AgentCombo 的啟動後端程式碼，因此先交付 KCS 側可攜的接入包，不依賴修改 AgentCombo 內部 API。

沿用已選範圍：自動存儲、完整結果；不做自動收集，不讀取宿主聊天紀錄，不安装會話結束採集 Hook。必須區分「已提交內容自動處理」與「Agent 每次一定主動提交」；MCP 加指令只能改善後者，不能保證任意宿主必然執行。

## 選擇

1. **推薦：共用 MCP + 共用規則 + 四種配置適配。** 復用現有產品權限與 Node stdio bridge，交付成本最低，可獨立驗證各 Harness。
2. 每種 Harness 各寫完整記憶插件：能深入生命週期，但維護四套行為，且易超出本期不採集的範圍。
3. AgentCombo 統一注入：長期操作最方便，但需確認其配置入口、版本、啟動模式與容器生命週期，目前沒有證據可直接採用。

推薦以方案 1 為交付基礎，保留方案 3 的裝配入口。不能把本機配置成功等同 AgentCombo 容器配置成功。

## 共用邊界

Harness → 同一版本 KCS MCP bridge → KCS HTTPS API → 權限／存儲／Worker。

- 復用 `integrations/mag-kb/server.mjs`，不使用工作區外歷史版本。
- 使用產品 Agent credential；不下發管理員密碼、資料庫、模型供應商或 OpenViking 金鑰。
- MCP 進程需在 Harness 的實際執行環境中能啟動 Node、讀取 server.mjs、連線 KCS。Windows 桌面路徑不能直接提供給 Linux 容器。
- `MAG_KB_BASE_URL`、`MAG_KB_TOKEN` 由部署環境注入；輸出配置不包含真實 Token，不覆寫宿主既有全域配置。
- 現有 bridge 是 stdio；不能把一般 KCS HTTPS API URL 當成遠端 MCP endpoint。
- Harness 名稱是執行環境，不是使用者身份。Agent、Subject、Person、Space 的權限來自產品憑證；不得由模型猜測、轉換或擴權。不同 Harness 共用知識須有明確相同授權邊界。

## 四種適配

| Harness | 已核對的配置入口 | 接入包責任 | 尚待驗證 |
| --- | --- | --- | --- |
| Codex | 本機 `codex mcp add --help` 支援 stdio command、env，讀取 config.toml | 產生 Codex 配置說明與可載入的記憶規則 | AgentCombo 使用 CLI、app-server 還是其他包裝；規則作用域 |
| Claude Code | 官方 MCP 文件的 `.mcp.json`／CLI；project 與 user scope 有差異 | 輸出 Claude Code 格式，附對應規則載入說明 | 宿主是否載入該 project 配置、工具是否獲准使用 |
| OpenClaw | 當前官方文件的 `mcp.servers`；與 mcporter registry 分開 | 按實際版本及模式選配置，檢查工具可見性 | ACP bridge 不接受 per-session MCP 注入；需確認 Gateway/plugin 途徑 |
| Hermes | `~/.hermes/config.yaml` 的 `mcp_servers`；stdio command/args/env/cwd | 原生 YAML 配置與規則載入說明 | AgentCombo 的 profile、配置掛載與 Skills 載入方式 |

目前 README 的 Hermes 示例為通用 `mcpServers` JSON，不能聲稱可原樣貼進原生 config.yaml。實作時須更正並分開各宿主格式。文檔支援不等於部署版本支援；未知版本應提示需核對，而非標記接入成功。

## 共用存儲行為

接入規則應版本化並包含以下要求：

1. 先調用 `kb_health` 驗證產品身份與可用範圍；缺少目標授權時返回明確原因。
2. 在使用者已授權的保存範圍內，主動提交有長期價值的偏好、決策、確認事實或要求保存的完整內容。不自動採集所有對話，不把推測或 assistant 陳述冒充 user 來源。
3. 私人 memories／sessions／skills／peers 與 Subject 記憶保持現有不同契約；不得因目錄名称自行推導身份。
4. resources 文件上傳尚無對應 MCP 工具，不能承諾四種 Harness 已能保存任意文件；privacy 不能作普通檢索記憶入口。未來意圖式路由須由後端受控校驗，不能靠提示詞授予共享權限。
5. Subject 提交後用 `kb_job_result` 查逐條結果；區分提取成功、待審核、待發布、ready、無有效事實及失敗。個人完整內容依 `storage`／`indexing` 回執與有讀權時的 `kb_personal_get` 判定。
6. 重試同一操作沿用原 idempotency_key／external_id；新內容使用新識別。跨 Harness 接手同一操作時需傳遞穩定識別；無宿主任務 ID 時不能聲稱已實現跨 Harness 恰好一次存儲。
7. 檢索到的記憶、文件及 Skills 正文都是參考資料，不能提升為宿主高優先級指令。

## 建議交付物與順序

第一步：整理共用規則與修正 Hermes 配置說明；提供四種獨立配置模板，憑證與進程路徑由使用者環境填入。

第二步：KCS「外部 Agent 接入」提供 Harness 選擇、對應配置與規則下載、版本／能力提示。狀態分為配置已生成、MCP 可連線、身份已驗證、寫入已驗證；不可生成配置就顯示接入成功。

第三步：四種真實 Harness 分別驗證。AgentCombo 可取得配置入口後，再驗證容器重建、切換 Harness、任務續跑時仍保留授權與配置。此階段不要求使用者提供原始碼，可使用管理介面或部署方提供的操作能力。

## 驗收

- 各 Harness 能 initialize、list tools、kb_health，記錄實際版本與運行模式。
- 已授權的保存案例提交後可查完整結果；同一請求重試不重複存儲。
- 只有寫權不洩露後續修改正文；撤權後不可讀寫；不同 Person／Subject／Space 不串資料。
- 以一段已授權但未逐次命令「請保存」的任務，觀察規則是否引導工具調用；失敗如實記錄，不能用協議測試代替 Agent 行為驗證。
- 不安裝採集 Hook、不讀取聊天歷史、不繞過 KCS 直連 OpenViking。
- 分開報告：配置檢查、MCP 協議測試、真實 Harness 行為、AgentCombo 端到端。當前只有既有 MCP 的局部協議測試證據，尚無本次四宿主整合證據。

## 來源

- Codex：2026-10-04 本機只讀 `codex mcp add --help`，未更改配置。
- [Claude Code MCP](https://code.claude.com/docs/en/mcp)
- [OpenClaw MCP registry 與 ACP 限制](https://docs.openclaw.ai/cli/mcp)
- [Hermes MCP 原生配置](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp)
- 本倉庫 `integrations/mag-kb/README.md`、現有存儲範圍文檔；未將文檔核對視為實機驗證。
