# 系統架構總覽

[互動架構圖](system-overview.html)｜[Archify 原稿](system-overview.archify.json)

2026-09-22，依產品程式與使用者提供的 Zeabur 截圖整理。這是預期完整架構，不是雲端服務全部驗收完成的宣告。

API 與 worker 都是產品後端；API 接收請求，worker 解析文件及處理背景任務。兩者使用同一份程式碼。前端由 API 服務提供；Hermes 位於使用者本機，平台不執行 Agent。

目前 Zeabur 已建立平台與 PostgreSQL；worker、OpenViking 尚待補齊，Hermes 尚待接入。資料庫保存原文、權限與持久任務；引擎只提供受產品權限控制的索引／檢索。圖示省略回傳及 worker 寫回狀態的線，聚焦主要路徑。

驗證：Archify showcase 9/9，零錯誤／警告；交付雜湊见 system-overview.receipt.json。瀏覽器 1440×900、1600×1000、1920×1080、2048×1320 均無水平／垂直溢出；已人工視覺檢視淺色 1440×900 與深色 2048×1320 截圖，文字與連線無遮擋。互動控制尚未逐項手動驗收。
