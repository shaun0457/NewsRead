# 12: 文章中英對照

**What to build:** 英文文章可以用中英對照閱讀，劃線、筆記和問 AI 都能用。

**Blocked by:** 11（貼新聞連結匯入並閱讀原文）、67（AI 引擎偵測、自帶 key 和每種工作的引擎）

**Status:** in-progress（12a 翻譯用量、12b 文章問 AI、12c 揭露紀錄已做；概念卡範圍、判斷讀 `blind`、Mockup A 實機比對未做）

- [x] 英文文章翻成中文，可以切換譯文 / 對照兩種模式（沿用閱讀器的 zh / bi 模式，ticket 08 讓段落資料可以用）
- [x] 劃線、邊注、筆記存得住，重新打開後還在（ticket 08）
- [x] 問 AI 時會帶入所在段落的上下文；範圍是這篇全文，不上網查（12b；概念卡還沒有，之後加）
- [x] 回答分「文章怎麼說」（附段落出處，引述不在原文就不顯示）、「一般解釋」（標「AI 解釋」）、「文章沒寫的」；可選白話或精讀（12b）
- [ ] 盲判之前問 AI 會寫一筆揭露紀錄（地點 = 問 AI），之後的判斷 `blind` = false、標「問過 AI」；只看概念卡不寫揭露紀錄（測試）——12c 只做寫入（`exposures` 表、`record_exposure`），判斷讀它留給判斷的 ticket
- [x] 輸入框貼網址時先問要不要匯入，匯入走 Ingest（12b：`PR.openIngest`）
- [x] 對話跟著這篇存下來；回答可以逐句標「正確 / 錯誤 / 編造」，寫 ContextManifest 和 AI 用量（12b）
- [x] 翻譯的用量寫進 AI 用量紀錄（12a：`jobs.LedgerMeter`，每次呼叫一筆，`task` = translate）
- [x] 中文文章不翻譯（ticket 11：`ingest.is_chinese`）
- [ ] 畫面符合已核准的 Mockup A

**Notes（2026-11-12，12a）：** 翻譯還是走舊的 `/api/config` 引擎設定（不是 Engines & Usage 的「翻譯」工作設定），只是用量照每次呼叫記進 `ai_usage`；改走 Engines 留給 12b 一起處理（問 AI 也要改）。翻譯不寫 ContextManifest（不是判斷）。

**Notes（2026-11-12，12b / 12c）：**
- 問 AI 也還是走舊的 `/api/config` 引擎設定，沒改走 Engines 的「問 AI」工作設定；用量照每次呼叫記（`task` = ask，指向 ContextManifest）。
- 「不上網、不用工具」：Claude Code 引擎用 `--tools ""` 一個工具都不給（有附圖時照舊只給 Read），太舊的版本直接失敗；Codex（read-only sandbox 還是能讀檔）和 Antigravity 只有 prompt 的要求，文章裡藏的指示理論上可以叫它們讀本機檔案——待處理。
- 揭露紀錄等第一段回答出來才寫；引擎沒回答就失敗不算揭露。
- 一則回答最多 200,000 字（`server.MAX_ANSWER_CHARS`）。
- 精讀沿用 `answer_style = xray`（只有文章會記住 xray；論文舊的 xray 對話照舊回到一般模式）。
- 拆段在串流結束後才做；串流中照原文顯示。模型沒照格式回答（例如「沒有可以判斷股價的資訊」）就照原文顯示。
- 只做了測試，畫面還沒在瀏覽器裡跟 Mockup A 比對。
