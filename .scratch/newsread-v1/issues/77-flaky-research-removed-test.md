# 77: `test_research_removed` 在 Windows 上不穩定

**What to build:** `tests/test_research_removed.py` 的 POST 路由測試在乾淨的 HEAD 上大約 12 次失敗 4 次（`ConnectionAbortedError` / WinError 10053）。原因：被移除的路由回 404 時沒有讀掉請求的 body，Windows 上客戶端還在送資料時連線就被關掉。跟 ticket 67 修 redirect 測試的情況相同（假 server 先讀完 `Content-Length` 再回應就穩定了）。

**Blocked by:** None (can start immediately)

**Status:** done

- [x] 確認是伺服器端的問題還是只有測試：如果正式伺服器回 404 / 4xx 時也沒讀 body，在伺服器端修（讀掉 body，有上限；超過上限就直接關連線並回 413），因為真的客戶端也會遇到
- [x] 加一個測試：送有 body 的 POST 到不存在的路由，連續跑 20 次都拿到 404，不會連線中斷
- [x] 讀 body 的上限有測試打到
- [x] 完整 Python 測試連跑 5 次都過

**Notes（2026-11-12）：** 是伺服器端的問題：路由沒讀 body 就回 404 / 400，Windows 上連線被中止；伺服器用 HTTP/1.1 保持連線，留下的 body 還會被當成下一個請求。修法在 `Handler.send_response`：POST 的路由沒讀 body 時先讀掉（最多 `DRAIN_MAX`，分段讀）。長度超過上限、對不上、用 `Transfer-Encoding` 送、`Content-Length` 重複或看不懂時，**照原本的狀態碼回應（例如 404）再關連線**，沒有改回 413：路由不存在時回 404 比較對，對方收得到回應就好。測試 `tests/test_server_drain.py`。沒做：Handler 沒有 socket 逾時（原本就這樣，宣告了 body 卻不送會卡住一條 thread）；要改得一併處理常駐的 presence WebSocket，另開 ticket。
