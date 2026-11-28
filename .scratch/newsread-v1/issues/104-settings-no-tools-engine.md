# 104: 設定頁標示不支援分類的引擎

**What to build:** 只有 Codex 或 Antigravity 時，設定頁標示「可閱讀／翻譯，但不支援分類」，待分類的項目顯示原因，不默默停著。來源：PR #73 SCOPE Q2。（使用者 2026-11-28 決定照建議做）

**Blocked by:** —

**Status:** in-review

- [x] UI 先做 mockup 給使用者確認（2026-11-28 核准）
- [x] 設定頁標示（測試）
- [x] 待分類項目顯示原因（測試）

## 做法

- 後端：`GET /api/ai` 多回 `no_tools`（關不掉工具的 CLI、不能有工具的工作，來自 `NO_TOOLS_UNSUPPORTED` / `NO_TOOLS_TASKS`）。`Engines.triage_block()`：分類找不到引擎、原因有 `no_tools` 時回找到的那幾個 CLI。`POST /api/today` 多回 `pending`、`triage_block`；只有今天有待分類時才去讀 AI 設定，讀不到就當成 `null`，不讓頁面失敗。
- 設定頁：找到的 Codex / Antigravity 那一列加黃色 chip，表格下面一段說明；分類的主要和備用下拉選單裡它們灰掉，標「· 不支援分類」；分類那格寫「不能分類」、要什麼引擎和「填 API key」連結。
- 今日新聞：上方黃色提示（幾則在等、找到哪個 CLI、要什麼引擎）和「到設定的 AI 模型」按鈕；待分類的每則寫「等待 AI 分類：分類要 Claude Code、API key 或本機模型」。
