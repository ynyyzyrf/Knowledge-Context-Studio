# 工作台 UI 設計與驗證

2026-09-22，本機改版，未推送／發布雲端。

## 設計依據

採用使用者提供的 [Taste Skill：redesign-existing-projects](https://github.com/Leonxlnx/taste-skill/blob/main/skills/redesign-skill/SKILL.md)，先檢查現有介面，再沿用既有 React、Ant Design 與 CSS 逐項改進。產品定位為內部團隊日常使用的知識工作台。

主要問題：文字過小、輔助文字對比不足、導航缺少圖示與層級、表單與表格密度不一致、原生上傳框、空間首頁只有說明文字、不同電腦字體不一致。

## 共用規範

- 保留綠色品牌 `#256b5e`；淺灰綠畫布、白色內容面板、清楚的選中狀態。
- 字體使用本機隨包部署的 Manrope Variable 與 Noto Sans TC Variable，`font-display: swap`；不依賴外部字體 CDN。授權文件保留在 `web/public/assets/`。
- 控制項圓角 8px、面板 12px；主操作清楚，次要操作使用文字或低強度樣式。
- 桌面保留空間導航／目錄／閱讀三欄；小螢幕垂直排列，表格在自身容器內橫向滾動。
- 補上骨架載入、鍵盤 focus、跳至內容連結、按壓回饋與 reduced-motion 規則。
- 真實數據直接來自既有 API；未接入目錄仍保留原有提示，不新增假數據或假操作。

Ant Design 的共用 token 在 `web/src/main.tsx`，產品視覺樣式在 `web/src/ui-polish.css`；既有基礎結構保留於 `style.css`。後續元件遵循同一套字體、間距與表面層級。

## 本輪交付

- 全站導航圖示、標題層級、麵包屑與空間卡片。
- Space 首頁的真實文件／Agent 數量及私人／共享資料入口。
- 文件目錄、閱讀卡片、資料詳情、授權說明的視覺整理。
- 上傳區支援單一文件點選／拖曳、選中文件資訊、移除／更換及既有上傳流程。
- 成員、Agent、審計與治理頁套用共用表格、表單、頁籤與空狀態。
- 登入頁與自託管 favicon。

## 驗證範圍

- `npm run build` 成功；`npm test` 6 passed；`git diff --check` 通過。
- 本機真實瀏覽器檢查空間列表、Agent、成員、審計、記憶治理、Space 文件概覽在 1440／1024／390px 無整頁橫向溢出。
- 登入頁在 1440／390px、上傳頁在 390px 驗證無整頁橫向溢出。
- 私人資料快捷入口能開啟實際目錄與授權區。
- 新上傳控制項實際選取 `ui-smoke.txt` → 提交 → 存入 `user/default/resources` → worker 索引成功。驗證文件已刪除，保留既有資料。
- favicon 由 `/assets/favicon.svg` 正確提供；未登入時 `/v1/auth/me` 的 401 為正常登入流程。
- 截圖保存在工作區 `output/playwright/taste-*.png`。

限制：本輪未重新驗證每個治理操作的完整資料生命週期，也沒有執行雲端 UI 驗收。Vite 仍有既有大型 JS bundle 提示，應另行進行路由分包與載入效能优化；UI 改版不代表生產驗收完成。
