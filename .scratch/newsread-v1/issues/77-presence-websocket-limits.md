# 77: presence WebSocket 的上限

**What to build:** `GET /api/presence` 只檢查 Origin（沒有 token），升級之後沒有逾時（ticket 73 刻意排除）。現在沒有連線數上限，`wsock.hold` 也照對方宣告的訊框長度（最多 2^63）去讀、會先配置那麼多記憶體。本機風險小；Docker 綁 0.0.0.0 時，任何允許的 Host 都能占住 thread 和記憶體。（ticket 73 security review MEDIUM）

**Blocked by:** None (can start immediately)

**Status:** needs-triage

- [ ] 同時的 presence 連線有上限（例如 16），超過就拒絕
- [ ] 訊框長度有上限（控制訊框 125 bytes，其他幾 KB），超過就關連線
- [ ] 考慮頁面送心跳、伺服器有閒置逾時（例如 120 秒），對方消失（筆電睡眠）時 presence 會離開
- [ ] 一般請求讀標頭有總時限（不只每次讀各自 30 秒）
- [ ] 每個上限都有測試打到
