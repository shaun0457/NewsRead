# 73: 本機伺服器的連線逾時

**What to build:** `easyread/server.py` 的 `Handler` 沒有設 socket 逾時。客戶端宣告了 body（`Content-Length`）卻不送完、也不關連線，讀 body 的那條 thread 會一直卡住；ticket 71 讓 404 / 400 的回應也會先讀掉 body，同樣受影響。只綁 127.0.0.1、要有 token 才會讀，風險小，但等待要有上限（見 rules/coding.md）。難處是常駐的 presence WebSocket（`wsock.hold`）本來就是長連線，逾時不能套到它。

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] 一般請求讀標頭和 body 有逾時〔預設〕30 秒，逾時就關連線
- [ ] presence WebSocket 升級之後不受這個逾時影響（或改用心跳），頁面開著不會被斷線
- [ ] 測試：宣告 body 卻不送的請求在逾時之後被關掉（用很短的逾時跑），WebSocket 連線超過逾時還在
- [ ] 完整 Python 測試全過
