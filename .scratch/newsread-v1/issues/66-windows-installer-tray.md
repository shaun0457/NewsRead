# 66: Windows 安裝版與系統匣

**What to build:** 像 PaperRead 一樣，使用者下載 Windows 安裝檔就能用。關掉視窗會縮到系統匣，抓取和 Telegram 繼續跑；從系統匣按「結束」才停。

**Blocked by:** 06（改名 NewsRead）、07（常駐與排程器）

**Status:** ready-for-agent

- [ ] 沿用 PaperRead 的 Electron 打包，產出 Windows 安裝檔；安裝後可以從開始選單打開
- [ ] 關掉視窗後縮到系統匣，server、排程和 Telegram polling 仍在跑（測試）
- [ ] 系統匣選單有「打開」和「結束」；結束時 polling、排程和背景執行緒在時限內停掉（測試）
- [ ] 設定頁的「開機自動啟動」對安裝版有效
- [ ] 同時打開第二個時，聚焦到已經在跑的那個，不會跑出兩個 server
- [ ] 設定頁顯示版本；更新來源指向自己的 repo，或先關掉更新（見 06）
- [ ] 只驗證 Windows；macOS / Linux 沿用上游的打包設定，不驗證
- [ ] release workflow 屬於單向門（見 56），這張只在本機打包，不改 CI
