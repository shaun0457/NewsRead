# 67: AI 引擎偵測、自帶 key 和每種工作的引擎

**What to build:** 打開 NewsRead 時自動找到這台電腦上已登入的 AI 訂閱（Claude Code、Codex CLI、Antigravity CLI）和本地模型（Ollama）；使用者也能自帶 API key（Anthropic，或填 base URL 的 OpenAI 相容服務），並替每種工作選引擎和模型。其他模組都透過 Engines & Usage 呼叫 AI，不直接呼叫引擎。

**Blocked by:** 01（Mockup A：敘事看板、題材頁和第一個切片的畫面）、10（帳本與索引核心）

**Status:** done

- [x] 啟動時在背景偵測引擎，結果有快取；設定頁可以重新偵測，顯示每個引擎是否已登入、是訂閱還是 API
- [x] 每種工作（分類、翻譯、題材頁 / 概念卡起草、論點變化偵測、問 AI）各自指定引擎和模型，可以指定備用引擎；換引擎或模型會記進 prompt 版本
- [x] API key 只存在本機設定，畫面只顯示末四碼，不出現在 log 和任何 API 回應裡（測試）
- [x] key 失效（AUTH_INVALID）時不重試同一把；有備用引擎就改用並提示，沒有就暫停該工作（測試）
- [x] 沒有任何引擎時，匯入、閱讀、筆記、帳本照常；需要 AI 的工作標「沒有 AI」（測試）
- [x] 每次呼叫都記用量：引擎、模型、token；API 記費用，訂閱不折算金額，Claude Code 有回報時記 5 小時 / 7 天額度和重置時間
- [x] 限流（RATE_LIMITED）時指數退避重試，有次數上限，碰到上限的測試
- [x] 錯誤只記錯誤代碼和固定訊息，上游原文先過 scrubber
- [x] 用假引擎測試；CI 不呼叫真實模型
- [x] 畫面符合已核准的 Mockup A（`settings.html` 的 AI 模型區）
