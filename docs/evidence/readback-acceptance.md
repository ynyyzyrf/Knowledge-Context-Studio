# 記憶讀回驗收 · 2026-09-22

## 結果與範圍

本機 `http://localhost:8088` 的外部 Agent 記憶閉環已接通：提交訊息 → 真實模型提取 → 人工審核 → 背景发布 → 真實向量查找 → 返回帶版本／來源的參考內容。平台不執行 Agent；尚未驗收某個第三方 Agent 框架自行取用並生成回答。

- 真實 `BAAI/bge-m3` 向量為 1024 維；聊天使用已配置服務。
- 私有 OpenViking 固定來源 20ec78a149a0889a85b038627dddc70b46dceae3，native builder image 固定 SHA，只監聽主機 loopback 19388。
- 完整 PostgreSQL 契約套件：51 passed、2 skipped；後續索引存在性與發布／隔離針對測試：8 passed。2 個依賴棄用警告。JUnit 保留在忽略的 runtime/readback-suite.xml 與 readback-boundaries.xml。
- 真實引擎／真實向量的發布、改版、搜尋與刪除測試：1 passed，7.49 秒，runtime/live-readback-final.xml。候選 staging 明示使用確定性 fixture，此測試不代表抽取品質驗收。
- native HTTP/storage/queue + 明示離線模型 fixture：1 passed，3.93 秒，runtime/native-context/native-context.xml。
- 前端 5 tests passed；TypeScript/Vite build passed；約 1.22 MB 主 bundle 大小警告保留。Ruff 通過，Alembic 無 schema drift。

## 真實 HTTP 與瀏覽器

獨立驗收團隊建立外部 Agent／Subject／一天期限憑證，使用 HTTP 提交「我的長期飲品偏好是茉莉花茶，請記住這個偏好。」背景真實模型抽取成功；工作台候選為「長期飲品偏好是茉莉花茶」，在瀏覽器明確審核。

最新前端「API 接入測試」驗證憑證後，GET 有效記憶顯示 v1、記憶 ID 與来源訊息 ID。輸入「這位使用者平常喜歡喝什麼？」後，真實語意搜尋返回該記憶，並顯示給外部 Agent 的參考文字及 request_id `cf5e7ba2e82642c88e937e5177e6492a`。這是不同問句的實際搜尋結果，非畫面占位內容。

驗收完成後，透過治理 API 排入測試記憶刪除、撤銷測試憑證，停用隔離帳號與團隊，登出瀏覽器；沒有改動使用者內部團隊。驗收腳本保存的明文臨時密碼／憑證已移除。

## 本次修正的根因

1. 舊 upsert 在新版刪除完成後晚到，可能留下舊正文。現在任何舊 upsert 完成路徑都持久化精確版本清理；有效 lease 期間刪除等待寫入；清理錯誤持續退避重試，每 60 秒重新核對，過期 lease 無法提交成功。產品讀取立即排除舊版本。
2. 首次以 builder 的原始碼工作目錄啟動，遮蔽已安裝 native extension，留下只有 collection metadata、没有 index 的部分初始化。改用 `/data` 工作目錄與 Python `-I`，停機後從已有 collection 建立缺失的 default index，保留原資料。現在启动檢查實際 count，發布也要求 URI 有向量记录，不能僅憑 HTTP 健康／vector_status 判定成功。
3. 引擎刪除的 `wait=true` 等待父目錄語意摘要更新，會受聊天服務重試影響而拖慢整個清理。改用同步文件／向量刪除並核對正文不存在、URI 向量 count=0；父摘要刷新獨立進行。只允許目前精確文件版本作為產品搜尋來源。
4. 新增獨立向量服務後，舊單元測試繼承本機 `.env`。測試配置改為 `_env_file=None`，隔離真實設定。

## 尚未完成

知識空間文件匯入／检索、可攜生產映像與正式部署、完整備份恢復／災難演練、效能與模型品質 SLO、實際第三方 Agent 整合驗收。記憶清理為最終一致；本次不宣稱備份及父目錄衍生摘要永久抹除。
