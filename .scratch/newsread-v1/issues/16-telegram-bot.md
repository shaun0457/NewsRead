# 16: Telegram bot

**What to build:** 手機上透過 Telegram bot 匯入連結、查今日重點。

**Blocked by:** 07（常駐與排程器）、14（AI 分類寫進帳本）

**Status:** ready-for-agent

**Reviewer:** security-reviewer

- [ ] 設定 bot token；token 不寫進 log，也不出現在任何 API 回應裡
- [ ] 桌機上顯示一次性的配對碼，有時效；傳給 bot 之後才把 chat id 加進白名單
- [ ] 不在白名單的訊息直接丟掉，只記錄次數（測試）
- [ ] 轉傳連結給 bot 就完成匯入，bot 回覆結果或失敗原因
- [ ] `/today` 回覆今日重點
- [ ] long polling 斷線重連有次數上限和退避；停止時 polling 會結束（測試）
- [ ] 用假的 Telegram API 測試
- [ ] 畫面符合已核准的 Mockup A
