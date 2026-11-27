# 81: PDF 可選文字快取：同大小、同一時間刻度內的改動認不出來

**What to build:** `easyread/selectable_text.py` 用「路徑 + 檔案大小 + mtime_ns」判斷快取有沒有過期。來源 PDF 在同一個時間刻度內被改成同樣大小的內容時，快取不會更新。`tests/test_selectable_text.py::test_changed_source_invalidates_cache` 因此偶爾失敗（2026-11-12 完整測試 1 次；單獨重跑 6 次都過）。

**Blocked by:** None (can start immediately)

**Status:** needs-triage

- [ ] 決定快取身分要不要加內容雜湊（或至少前後幾 KB 的雜湊），成本要有上限
- [ ] 測試不靠時間刻度碰運氣（例如明確設定 mtime），能穩定重現舊行為的失敗
