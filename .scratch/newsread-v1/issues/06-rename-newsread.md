# 06: 改名 NewsRead

**What to build:** 把產品名稱從 PaperRead 改成 NewsRead。Python package 名稱 `easyread` 維持不變。

**Blocked by:** 04（移除研究工作區、文獻搜尋、Zotero 與批次匯入）、05（移除貼紙）

**Status:** ready-for-agent

- [ ] 介面文字、視窗標題、桌面版名稱、README 都改成 NewsRead
- [ ] 桌面版的更新來源和發佈設定改成自己的 repo，或先關掉更新功能；打包版不會從 PaperRead 下載更新
- [ ] 不改 CI workflow（另見 56）
- [ ] i18n 檢查通過
- [ ] 原有測試全過（基準：Python 501 個、前端 233 個），新增的行為有測試
