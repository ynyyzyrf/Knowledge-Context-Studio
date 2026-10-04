# 四種 Harness 配置適配驗證

範圍：KCS 側適配 Codex、Claude Code、OpenClaw、Hermes 官方配置。按使用者後續指示，AgentCombo 不在此次驗收範圍。

## 實作

- 憑證簽發／輪換返回四種 secret-free 配置片段，保留舊 mcpServer/env 欄位相容性。
- 憑證視窗提供四種 Harness 標籤及合併、環境變數、路徑說明。舊 API 回應仍可顯示原配置。
- MCP 0.4.0 新增 initialize.instructions 與不需憑證的 kb_guide，四種宿主共用同一份規則。
- 套件內附四種可複製模板及安裝指南。Hermes 模板為 YAML 可解析的 JSON 映射，使用原生 mcp_servers。
- 沒有加入自動收集、改動全域 Harness 配置、發布或部署。保留之前尚未提交的存儲改動。

## 已有證據

- 新增配置／guide 測試先因缺少模組失敗，實作後通過。
- 配置測試使用特殊字元／Unicode 地址，驗證 JSON 與 TOML 解析、env reference、四種鍵名。
- 真實 Node stdio 進程在無產品憑證時完成 initialize、tools/list、kb_guide；指南與工具清單可用。
- 定向後端測試：test_harness_configs、test_agents_spaces、test_personal_mcp，共 13 passed。包含既有真實 loopback HTTP 檢索及撤權測試。
- 前端 8 tests passed；TypeScript／Vite production build passed。既有大 bundle 提示仍存在。
- 定向 Ruff passed；MCP JavaScript 語法檢查通過。
- 獨立只讀審查未發現阻斷問題，指出 native harness loading、UI browser 和簽發／輪換回應測試的缺口；已補簽發／輪換四種配置與不含原始 token 的断言。

## 本機只讀版本核對

- Codex CLI 0.144.3；mcp add help 支援 stdio/env。
- Claude Code 2.1.186。
- OpenClaw 2026.5.7：mcp help 提供 list、serve、set、show、unset，沒有目前官方文件中的 status/probe。只讀 help 顯示既有 plugin warning 與 Windows /bin/sh fallback warning；未改配置或修復宿主。
- Hermes 0.20.0：讀取已安裝程式確認遞迴解析環境引用。

## 限制

以上不是四種 Harness 真實模型回合、主動選工具或生產寫入的證據。未執行瀏覽器中的新標籤操作。未宣稱任意 Agent 一定主動保存；此版通過指南引導已授權內容提交，再由現有 KCS 策略處理。正式安裝後需在每個宿主驗證 kb_health、授權測試寫入、完整結果與重試。

## 後續：原生客戶端驗證

使用者要求繼續後，增加 `tests/test_native_harness_storage.py`，使用已安裝的宿主客戶端及隔離 SQLite／loopback HTTP KCS，未寫入生產。

| Harness | 實際執行入口 | 已驗證 |
| --- | --- | --- |
| Codex 0.144.3 | app-server 的 ephemeral thread、MCP status 和 tool call | 13 個 KCS 工具、指南、身份、完整中文記憶入庫、讀回與相同請求重試 |
| OpenClaw 2026.5.7 | 已安裝套件的 createSessionMcpRuntime | 13 個工具、指南、身份、完整中文記憶入庫、讀回與重試 |
| Hermes 0.20.0 | 隔離 HERMES_HOME 的 CLI mcp test；已安裝套件的 MCP client | 原生配置載入、工具發現、身份、完整中文記憶入庫、讀回與重試 |
| Claude Code 2.1.186 | 隔離 CLAUDE_CONFIG_DIR 下註冊測試 MCP，再執行 mcp get | 原生客戶端顯示 Connected；模型存儲回合另見下方結果 |

三種無模型原生客戶端存儲測試：**3 passed**。增加 HTTP 請求觀察斷言後再次通過：確實調用身份接口、提交兩次、讀取單條內容，資料库僅有一條且正文完全一致。普通回歸測試 **13 passed、4 skipped**；四項 opt-in 宿主測試在未指定安裝位置時跳過。Ruff／diff whitespace 檢查通過。

這些測試直接調用 native MCP client，不代表 Codex、OpenClaw、Hermes 模型在無逐次保存指令時一定主動調用。Codex app-server 仍能看到本機插件注入的其他工具，只調用了測試 mag-kb；未修改全域配置。OpenClaw／Hermes 內部 API 僅供此版本驗收，不是新增產品依賴。

可重跑方式：提供環境變數 KCS_OPENCLAW_RUNTIME（已安裝 runtime 模組絕對路徑）、KCS_HERMES_ROOT（源碼與 venv 位置）、KCS_CODEX_EXE（原生執行檔），執行 `uv run pytest -q tests/test_native_harness_storage.py -k 'not claude'`。Claude 模型測試需要 KCS_CLAUDE_EXE 原生執行檔及 `--live-model`，單次設置 0.25 美元上限，且僅准許測試 KCS MCP 工具。

Claude 首次測試因 90 秒超時失敗；Windows .cmd 包裝造成子進程清理問題，已停止該測試子進程並禁止此測試使用 .cmd/.bat。後續測試亦明確關閉標準輸入，避免等待外部管線 EOF。模型測試結果不得從 Connected 推導。

最終模型測試：改用原生執行檔並關閉 stdin 後仍於 90 秒超時，**Claude 模型存儲驗證未通過**，不能歸因為已修復的 stdin／啟動包裝問題，也不能直接斷定是 MCP 失敗。只讀 auth status 顯示有登入資訊，但不代表模型 API 可用。測試进程已退出，沒有為了測試覆寫日常配置。

隔離基線：Claude 使用空 MCP 配置、禁用內建工具，只要求回答 OK，25 秒仍超時。診斷日誌包含 API error／Connection error；只保留布林診斷結果，原始日誌已刪除。由此可判斷當前模型連線本身也有問題，尚不能推定具體是供應商、代理、網路或憑證原因。需恢復該模型連線後再做 Claude 寫入驗收。

## GitHub 交付前回歸

2026-10-04：完整後端測試 114 passed、13 skipped；前端 8 passed，TypeScript／Vite build、Ruff、兩個 MCP JavaScript 模組語法檢查均通過。跳過項目包含需額外環境或顯式啟用的 PostgreSQL、原生宿主和 live model 測試；先前的三宿主原生驗收及 Claude 連線限制仍如上所述。新版 API／Worker 上線需先執行 Alembic 遷移；GitHub 推送不等於生產部署驗收。
