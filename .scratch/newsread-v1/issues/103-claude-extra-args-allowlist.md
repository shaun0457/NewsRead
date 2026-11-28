# 103: Claude Code 的 extra_args 改成允許清單

**What to build:** 關工具模式時，使用者設的 Claude Code `extra_args` 只留允許清單內的（例如連線、proxy 相關），其他拒絕並提示；會加工具或 hooks 的參數一律不收。來源：PR #73 SCOPE Q1。（使用者 2026-11-28 決定照建議做）

**Blocked by:** —

**Status:** done（PR #114，2026-11-28）

- [x] 允許清單內的參數照傳（測試）
- [x] 會開工具、hooks 的參數被拒並提示（測試）
- [x] 不認得的參數被拒（測試）


做的時候定的：允許清單是 `--fallback-model <模型>`，和寫成 JSON、只設連線環境變數（`HTTP_PROXY`、`HTTPS_PROXY`、`NO_PROXY`、`ALL_PROXY`、`NODE_EXTRA_CA_CERTS`、`ANTHROPIC_BASE_URL`）的 `--settings`。`--settings` 寫檔案路徑的不收（讀不到內容，可能帶 hooks）。提示：log 只記參數名（值可能帶帳號密碼），設定頁 Claude Code 卡片列出不帶哪些。有工具的一般呼叫照舊帶全部額外參數。
