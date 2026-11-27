# 79: 本機伺服器的連線逾時

**What to build:** `easyread/server.py` 的 `Handler` 沒有設 socket 逾時。客戶端宣告了 body（`Content-Length`）卻不送完、也不關連線，讀 body 的那條 thread 會一直卡住；ticket 77 讓 404 / 400 的回應也會先讀掉 body，同樣受影響。只綁 127.0.0.1、要有 token 才會讀，風險小，但等待要有上限（見 rules/coding.md）。難處是常駐的 presence WebSocket（`wsock.hold`）本來就是長連線，逾時不能套到它。

**Blocked by:** None (can start immediately)

**Status:** done

- [x] 一般請求讀標頭和 body 有逾時〔預設〕30 秒，逾時就關連線
- [x] presence WebSocket 升級之後不受這個逾時影響（或改用心跳），頁面開著不會被斷線
- [x] 測試：宣告 body 卻不送的請求在逾時之後被關掉（用很短的逾時跑），WebSocket 連線超過逾時還在
- [x] 完整 Python 測試全過

**Notes（2026-11-12）：** `Handler.timeout = REQUEST_TIMEOUT`（30 秒，每次讀寫 socket 各自算）。讀 body、寫回應時逾時（對方停住）轉成 `ClientTimeout`：不回應、直接關連線；等鎖逾時這類其他 `TimeoutError` 照舊回 500。presence WebSocket 升級後 `settimeout(None)`。順手修了 `log_message`：標準庫記逾時只帶一個參數，原本會 IndexError。測試 `tests/test_server_timeout.py`（逾時 0.5 秒跑；三個 mutant 都會被抓到）。
- Review：python、security 各 1 輪 PASS。修了 python 的 MEDIUM（等鎖逾時被當成對方逾時、不回應）。
- 沒做（記下來）：逾時是每次讀寫各自算，不是整個請求的總時限，每 29 秒送 1 byte 還是能占住一條 thread（本機風險小；Docker 綁 0.0.0.0 時較明顯）；presence WebSocket 沒有連線數上限、`wsock.hold` 會照對方宣告的長度配置記憶體（原本就有，見 security review MEDIUM）；非 loopback 下大檔下載一次 `sendall` 超過 30 秒會被切斷；聊天串流、notehelp 寫入逾時時沒走「讀者停止」那條路（不會存下部分回答）。
