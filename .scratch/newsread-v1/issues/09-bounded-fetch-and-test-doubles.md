# 09: 對外抓取規則與測試替身

**What to build:** 建立所有來源共用的對外抓取規則，以及之後每張 ticket 都會用到的測試替身。

**Blocked by:** None (can start immediately)

**Status:** done（a596eb6，2026-11-11）

**Reviewer:** security-reviewer

- [x] 共用抓取規則：逾時、最大位元組數、最大筆數、重試次數與指數退避、每個來源的每小時上限；每個上限都有一個測試真的碰到
- [x] 錯誤分類（逾時、被擋、付費牆、格式不支援、太大、超過上限），只記錄類別和固定訊息；上游的原文先過 scrubber，測試 key 和帳號會被遮掉
- [x] 失敗和提早結束時，連線都有釋放（測試）
- [x] 測試替身：假的網路回應（fixture）、回固定輸出的假 AI 引擎、HTTP API 測試的共用基底
- [x] CI 不連真實網路
