# 29: 用量頁

**What to build:** 使用者可以看到訂閱額度用了多少、各引擎的 token、API key 的花費，並依工作和來源分開看。

**Blocked by:** 14（AI 分類寫進帳本）、67（AI 引擎偵測、自帶 key 和每種工作的引擎）

**Status:** in-review（程式做完、review 過；依個別媒體分要等 #19 接上並在 `ai_usage` 記資料 ID，需另開 ticket；Mockup 視覺待使用者確認）

- [x] Claude Code 的 5 小時 / 7 天額度使用率和重置時間，附上次更新時間，並註明是整個帳號的用量（2026-11-15。`tests/test_usage_page.cjs`：the Claude card shows both windows…、the 5-hour bar turns red…；`tests/test_usage_report.py`：test_quota_is_shown_even_before_any_call_is_recorded、test_garbled_quota_file_does_not_fail_the_page）
- [x] Codex CLI 等只回報 token 的引擎，顯示 token 數並寫明看不到額度（2026-11-15。`test_usage_page.cjs`：Codex shows tokens only…；`test_usage_report.py`：test_day_only_counts_today_in_taipei_time。Antigravity 有呼叫才顯示一格）
- [x] API key 本月花費和月上限；訂閱不折算成金額（2026-11-15。`test_usage_page.cjs`：the API card shows this month's spend…；`test_usage_report.py`：test_api_spend_matches_what_the_guard_counts、test_month_groups_by_task_engine_and_model）
- [ ] 依工作（引擎、模型、次數、token、花費）和依來源（資料數、token、掛到論點的比例）分開看，可以切每天 / 每月（2026-11-15。依工作、每天 / 每月都做完：`test_usage_report.py` TotalsTest、CapsTest.test_task_rows_stop_at_the_cap，`test_usage_page.cjs` the task table…、switching the period…。**依來源只做到「呼叫 AI 的功能入口」**：`ai_usage.source` 是 `triage` / `newsread`，沒有記每次呼叫用的是哪一則資料，所以不能依個別媒體分；資料數和掛到論點的比例只有分類算得出來（`TriageLinkTest`、the source table…）。要依媒體分，需要來源（#19 等）接上、並在 `ai_usage` 加上資料 ID，另開 ticket）
- [x] 最近 14 天的每日 token（2026-11-15。`test_usage_report.py`：test_daily_is_fourteen_days_filled_with_zero_and_cut_at_taipei_midnight；`test_usage_page.cjs`：the daily chart has 14 bars…）
- [x] 事件清單：額度保護、限流、上限通知，只記錯誤代碼和固定說明（2026-11-15。額度保護和上限本來就有事件（#68）；限流是這張新增的 `RATE_LIMITED` 事件：`test_usage_report.py` RateLimitEventTest；畫面最多 20 筆：`test_usage_page.cjs` events are escaped…and stop at the cap）
- [x] 每頁右上角顯示 Claude 5 小時額度，點了到用量頁（2026-11-15。沿用 #68 的輪詢，沒有另開：`test_quota_guard_ui.cjs` the header shows…both go to the usage page、the quota badge is hidden…、every page with a header loads the indicator；今日新聞和題材頁原本沒載入這個指示，一併補上）
- [x] 空狀態（還沒用過 AI）、載入中（2026-11-15。`test_usage_page.cjs`：states: loading, empty…；`test_usage_report.py`：EmptyAndErrorTest）
- [ ] 畫面符合已核准的 Mockup A（`usage.html`）（2026-11-15。版面照 Mockup；差異：(1) 額度保護橫幅沒有「這次改用 API key 跑完」按鈕和「目前排隊 N 則」，因為還沒有對應的 API；(2) 每日長條圖底下沒有「11/6 特別多：…」的說明；(3) 來源表是功能入口，不是媒體（見上）；(4) 多了每月 / 每天切換和重新整理按鈕；沒有在瀏覽器裡實際看過，只有假 DOM 的測試；結構照 Mockup，視覺待使用者確認）
