# 71: `test_research_removed` 在 Windows 上不穩定

**What to build:** `tests/test_research_removed.py` 的 POST 路由測試在乾淨的 HEAD 上大約 12 次失敗 4 次（`ConnectionAbortedError` / WinError 10053）。原因：被移除的路由回 404 時沒有讀掉請求的 body，Windows 上客戶端還在送資料時連線就被關掉。跟 ticket 67 修 redirect 測試的情況相同（假 server 先讀完 `Content-Length` 再回應就穩定了）。

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] 確認是伺服器端的問題還是只有測試：如果正式伺服器回 404 / 4xx 時也沒讀 body，在伺服器端修（讀掉 body，有上限；超過上限就直接關連線並回 413），因為真的客戶端也會遇到
- [ ] 加一個測試：送有 body 的 POST 到不存在的路由，連續跑 20 次都拿到 404，不會連線中斷
- [ ] 讀 body 的上限有測試打到
- [ ] 完整 Python 測試連跑 5 次都過
