# 四種 Harness 接入 KCS

適用 MCP 套件 0.4.0。這是 KCS 官方格式適配包，不涉及 AgentCombo 的內部程式碼，也不安裝自動採集功能。

## 共用準備

1. 在 KCS 建立／選擇 Agent、服務對象與空間，授予所需權限，簽發產品憑證。個人目錄需獨立授權；自動存儲還需啟用對應策略。
2. 將本目錄整份部署到 Harness 所在機器或容器，包含 `server.mjs` 與 `instructions.mjs`，確保 Node >=18 可用。不要只複製 server.mjs。
3. 將 KCS 產品憑證配置為 Harness 啟動進程的 `MAG_KB_TOKEN`。桌面程式與背景服務不一定繼承目前終端的環境變數；需在真正啟動它的環境設定。不要將金鑰写入 Git 或聊天提示詞。
4. 在 KCS 簽發憑證的視窗選對應 Harness，複製配置片段，將 `<MAG_KB_MCP_ROOT>` 替換成目標機器上的絕對路徑。配置中的服務地址應為 KCS 的可達 HTTPS 地址。這不是遠端 MCP URL：目前透過本地 stdio bridge 調用產品 API。
5. 依下面規則合併原配置，保留既有其他服務；重啟 Harness。工具權限按宿主要求授予，不要為接入而全域放開所有工具。

| Harness | 原生位置 | 合併方式 | 驗證入口 |
| --- | --- | --- | --- |
| Codex | `~/.codex/config.toml` | `mcp_servers.mag-kb`；Token 用 env_vars 傳入 | `codex mcp get mag-kb` 檢查配置，再在會話調用 KCS 工具 |
| Claude Code | 專案 `.mcp.json` | `mcpServers.mag-kb`；信任專案並批准此 MCP | 會話 `/mcp`，再調用 KCS 工具 |
| OpenClaw | 實際 Gateway 的 `~/.openclaw/openclaw.json` 或指定配置 | `mcp.servers.mag-kb`；Token 提供給 Gateway | 先查 `openclaw mcp --help`；支援時執行 `openclaw mcp status`／`probe`，再由 Agent 調用 |
| Hermes | 所用 profile 的 `~/.hermes/config.yaml` | `mcp_servers.mag-kb`；UI 提供 YAML 相容 JSON 映射，需合併而非直接追加整段 | `hermes mcp --help` 核對版本支持的測試命令，再由 Agent 調用 |

配置檔可能因 profile／自訂環境而不同，以上是預設位置。只有配置可讀，不表示 MCP 連線或存儲成功。

尚未部署新版 KCS 視窗時，可直接使用套件內的 [Codex](templates/codex.toml)、[Claude Code](templates/claude-code.json)、[OpenClaw](templates/openclaw.json)、[Hermes](templates/hermes.yaml) 模板。替換示例服務地址和進程路徑；模板不包含真實憑證。

## 規則載入與主動存儲

服務 initialize 返回共用 instructions；`kb_guide` 提供完整指南，不需要憑證即可讀取。宿主不一定將 initialize.instructions 呈現給模型，因此首次接入需要確認 Agent 能看到並調用 `kb_guide`。

希望持續使用時，可在自己已信任的宿主／專案指令中加入簡短的 KCS 使用約定：啟動後讀取 KCS 指南、驗證身份；在已授權的範圍內主動提交確認的長期事實或要求完整保存的內容，並查回結果。Codex 可用專案 AGENTS.md，Claude Code 可用 CLAUDE.md；OpenClaw 和 Hermes 可使用其工作區指令設定。不要覆蓋現有指令，亦不要把檢索取得的 Skills 正文直接升級為指令。

指南說明 memories、sessions、skills、peers 的現有工具路由。Subject 提取不保留完整任務正文；個人 memories 提交可保留完整內容，但不能將任意文件誤存為個人記憶。resources 上傳與 privacy 存儲沒有在此次新增。超出大小限制應明確報告，不截斷內容。

這是由 Agent 遵循規則主動提交；沒有背景讀取聊天紀錄或會話結束 Hook。未提交內容不會憑空入庫，不能保證每種模型每次都選對工具。

## 驗證次序

1. `kb_guide`：確認新套件與規則可讀。
2. `kb_health`：確認實際產品身份、授權對象和空間，不使用猜測的 ID。
3. 在已授權測試範圍提交一筆明確測試內容，保存冪等識別。
4. Subject 走 `kb_job_result`；個人提交看 storage/indexing，具讀權時用 `kb_personal_get`。區分待審核、已存但待索引、完成、無有效事實及失敗。
5. 同一識別重試，確認沒有重複創建。撤權後確認不可讀寫。

先驗證人工觸發調用，再用已授權但沒有逐次要求保存的任務驗證主動選工具。記錄真實版本與結果；協議測試不能替代自主行為驗證。

## OpenClaw 兼容邊界

當前官方文件支持原生 `mcp.servers`。舊版可能沒有此入口，不要把未知 key 強行塞入配置；應升級到支持的版本或按該版本官方途徑接入。此套件不自動升級宿主。`openclaw mcp serve` 是把 OpenClaw 暴露為 MCP server，不是接入 KCS。ACP bridge 不接受逐會話 MCP 注入；需使用其支持的 Gateway／插件配置方式。

## 官方依據

- [Codex 配置參考](https://developers.openai.com/codex/config-reference/)
- [Claude Code MCP](https://code.claude.com/docs/en/mcp)
- [OpenClaw MCP](https://docs.openclaw.ai/cli/mcp)／[擴充配置](https://docs.openclaw.ai/gateway/config-extensions)
- [Hermes MCP](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp)

核對日期：2026-10-04。官方文檔更新不代表本機版本已支持所有入口。
