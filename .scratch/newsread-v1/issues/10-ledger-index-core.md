# 10: 帳本與索引核心

**What to build:** 建立 SQLite 索引、Story、只能新增的帳本、逐次的 AI 用量紀錄和 prompt 版本號。AI 從第一筆分類開始就要寫進這裡。

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] SQLite 索引（WAL 模式），放在資料目錄下
- [ ] Story：每則資料預設自成一個 Story
- [ ] 帳本只能新增：更新和刪除被 trigger 擋下（測試）
- [ ] 每筆紀錄存內容雜湊，被竄改時偵測得到（測試）
- [ ] 修正是新增一筆並帶 `supersedes` 指向原紀錄，原紀錄保留（測試）
- [ ] AI 用量逐次紀錄：日期、來源、任務類型、模型、token、費用（訂閱制記為「不明」）
- [ ] prompt 版本號登記：每個 AI 任務有目前的版本號
- [ ] 執行中可以安全備份（測試）
- [ ] 有一個唯讀 API 可以列出帳本紀錄，供之後的 ticket 驗收
- [ ] ContextManifest：每次 AI 呼叫記下送進去的 Item、論點與題材頁版本、概念卡、MarketContext 日期和 prompt 版本（存 ID 和雜湊，不存全文）；帳本裡的 AI 紀錄都指向一份 manifest（測試）
- [ ] manifest 裡的 Item 都早於該次判斷時間（測試）
