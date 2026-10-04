# Agent 記憶分類與 MCP 接入：競品調研

調研日期：2026-10-03。範圍：官方文件與官方倉庫閱讀，未部署競品、未作模型品質或效能對比。GitHub main 和線上文件會持續變更；不代表 KCS 目前使用的 OpenViking 引擎版本已具備相同功能。本文是設計建議，沒有修改產品程式或生產設定。

## 結論

針對 KCS「外部 Agent 不知道內容要放哪個目錄」的問題，建議採用：意圖明確的少量 MCP 入口、服務端分類政策、憑證決定所有權、可查詢的分類結果。目錄保留給人員瀏覽，Agent 不必自行拼接所有實體路徑。

規則仍有價值，但需區分三件事：

1. 哪些內容值得提交：由工具說明／接入指南引導，沒有宿主事件接入時仍依賴 Agent 調用。
2. 提交後歸到哪裡：由平台政策處理，Agent 可提供用途提示。
3. 誰能讀、是否共享：由授權決定，不能由語意分類模型推斷。

本次建議符合 MAG 已確認的範圍：先優化提交後的存儲與結果，不做自動收集。

## 官方實作模式

### OpenViking：按意圖提交，由服務端歸檔記憶

官方 MCP 接入 Skill 分開 remember、add_resource：前者接收帶角色的訊息，由服務端提取與歸檔；後者匯入文件或網址。該 Skill 明確說明此接入沒有 lifecycle hooks，不能自動捕獲或回憶。這直接支持「工具接通不等於自動收集」的界線。[官方接入 Skill](https://github.com/volcengine/OpenViking/blob/main/agent-plugins/skills/openviking-memory/SKILL.md)

Resource、Memory、Skill 是不同上下文類型；應用寫入 session 並 commit，觸發背景記憶處理。目錄仍存在，但不必由 Agent 選擇每個記憶子目錄。[上下文類型](https://github.com/volcengine/OpenViking/blob/main/docs/en/concepts/02-context-types.md)

對 KCS 的啟發：維持人員看得見的目錄；以「記住」「存原文」「保存方法」表達提交目的。不能直接假設新上游插件與本地引擎 API 兼容。

### Mem0：同一提交能力區分提取與原樣保存

add 接收訊息和 user/agent/run 等範圍識別；infer 決定提取結構化記憶還是保存原內容。原樣保存可能產生重複，混合模式亦需小心。此模式把「完整正文」與「提取後的記憶」分開，避免以摘要替代原文。[Add Memory](https://docs.mem0.ai/core-concepts/memory-operations/add)

版本注意：本次讀到的 Add 文件描述 additive storage，不會由 add 覆寫或刪除既有記憶；較早概覽仍描述持續更新與衝突處理。因此不將「每次 add 自動完成增刪改」視為所有版本的共同保證。導入前須固定版本並驗證。[較早概覽](https://docs.mem0.ai/features/contextual-add)

對 KCS 的啟發：顯式區分提取模式與原文模式，並返回實際處理結果；不要在介面上把二者都稱作「記憶已保存」。

### Letta：用用途描述教 Agent 如何讀寫

V1 SDK 文件中的 memory blocks 包含 label、description 和正文；description 是 Agent 判斷如何讀寫的重要依據，內容可由記憶工具更新。這裡比較的是官方仍保留的 V1 SDK 記憶設計，而非宣稱它代表所有新版 Letta API。[Memory blocks](https://docs.letta.com/v1-sdk/memory/memory-blocks)

對 KCS 的啟發：目錄規則應包含用途、正例、反例與修改策略，不能只有 memories/peers 等英文名稱。Letta 把記憶放入受控 Agent 上下文的方式，也不能直接推廣成任意第三方 MCP 客戶端都會遵守。

### Zep／Graphiti：來源資料與推導結果分開

Zep 的 episode 是輸入的訊息、文字或 JSON；原始內容與抽取出的實體、關係及摘要一同保留，可回讀原文。[Zep Episodes](https://help.getzep.com/v3/episodes)

Graphiti 是相關的開源時序圖框架，接收 episodes 後增量更新圖；不應把 Graphiti 與 Zep 雲端全部功能、權限契約視為同一產品。[Graphiti 概覽](https://help.getzep.com/graphiti/getting-started/welcome)

對 KCS 的啟發：一次提交可以有多個派生結果。完整報告保存在原文資源，偏好和決策作記憶，二者靠來源 ID 關聯；不要為分類方便而丟失原文。

### WeKnora：知識文件與長期記憶各自治理

當前官方 main 已列出 document/FAQ/wiki 知識庫和長期記憶能力，不能再僅把它當作文件 RAG。[官方概覽](https://github.com/Tencent/WeKnora)

長期記憶 API 提供 explicit_only/auto 寫入模式、提取指令、空間與個人開關，以及 active/pending/superseded/archived 狀態；條目帶來源和過期資訊，pending 不參與提示詞，另有確認、拒絕及整理結果。[長期記憶 API](https://github.com/Tencent/WeKnora/blob/main/website-docs/04-api/02-api-memory.md)

對 KCS 的啟發：自動處理與治理介面可以共存；來源不足或衝突需可檢查。WeKnora 的內置 Agent 記憶流程不構成外部任意 Agent 只接 MCP 即可全自動的證據。

## 建議的 KCS 接入契約（尚未實作）

先提供下列清楚區分用途的入口，而不是一個讓模型在任意路徑寫文件的工具：

| 建議入口 | Agent 提供 | 平台責任 |
| --- | --- | --- |
| 接入指南 | 目標空間 | 返回已授權目錄、用途、例子、政策版本 |
| 記住內容 | 原始陳述／事實、來源、可選用途提示 | 提取、分類、去重、審核或存儲、索引 |
| 保存完整資料 | 正文／文件、標題、明確私人或共享範圍 | 保存原文、建立來源 ID、排隊解析索引 |
| 保存可重用方法 | 方法內容及來源 | 驗證格式，作為 Skill 資料保存；不自動授予執行權 |
| 查詢結果 | 提交 ID | 返回分類、目標、原因、內容引用、存儲與索引結果 |

可以共用一個後端 ingestion service，但 MCP 不必壓成一個模糊的萬能工具。先使用確定性政策；只有內容本身需要判斷時才調用分類模型，避免每次已知類型的文件上傳都增加模型成本。

分類建議：memories 保存跨會話有價值的事實／偏好；peers 保存有明確對象的上下文；sessions 保存提交的過程紀錄；skills 保存可重複方法；resources 保存完整來源資料。privacy 目前未開放，不列為可写入口。

權限規則：所有權來自 Token；分類結果不能擴大 scope；寫入共享 resources 必須有明確共享意圖與寫權；不確定或無權時返回待確認／拒絕，不能偷偷改存共享。Agent 只能給分類提示，不能設定系統政策。

## 一個實際例子

Agent 提交「本次部署完整報告，並記錄之後使用 Zeabur 的決定」。期望結果：

- 報告正文 → 私人 resources，完整可回讀。
- 明確確認的部署偏好 → memories，來源指向報告／原始陳述。
- 只有在確實整理出可重用步驟時，才產生 Skill 候選。
- 回執列出每個產物和處理理由；若只有保存原文成功，不宣稱記憶和 Skill 也已建立。

上例是 KCS 建議行為，不是宣稱任一競品都會自動產生這三種內容。

## 下一步驗收集合

在實作新分類前，固定至少以下案例作比較，不僅靠工具描述看起來完整：

1. 使用者長期偏好 → memories。
2. 客戶背景 → peers；同名不同對象不合併。
3. 一次性工作流水 → sessions，不大量轉為長期記憶。
4. 可重用部署 SOP → skills 候選。
5. 多段原始報告 → resources，逐字回讀，不被摘要替代。
6. 混合報告與偏好 → 原文和派生記憶有可追蹤關聯。
7. 未明確共享 → 保持私人；無共享權 → 拒絕。
8. 分類不確定 → 明示待確認，不任意放入 memories。
9. 重試 → 同一收據、不重複派生；已刪來源重放不復活。
10. 未提交內容 → 沒有任何收集或存儲，符合本次範圍。

先評估分類正確率、全文保真、越權次數、重試重複率、分類延遲和模型成本。此輪未產生上述指標的實測值。
