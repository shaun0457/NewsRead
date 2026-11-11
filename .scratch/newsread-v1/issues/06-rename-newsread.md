# 06: 改名 NewsRead

**What to build:** 把產品名稱從 PaperRead 改成 NewsRead。Python package 名稱 `easyread` 維持不變。

**Blocked by:** 04（移除研究工作區、文獻搜尋、Zotero 與批次匯入）、05（移除貼紙）

**Status:** done

- [x] 介面文字、視窗標題、桌面版名稱、README 都改成 NewsRead
- [x] 桌面版的更新來源和發佈設定改成自己的 repo，或先關掉更新功能；打包版不會從 PaperRead 下載更新
- [x] 不改 CI workflow（另見 56）
- [x] i18n 檢查通過
- [x] 原有測試全過（基準：Python 501 個、前端 233 個），新增的行為有測試

**Notes（2026-11-12）：** 介面文字、視窗標題、log / 啟動訊息、User-Agent、模型提示、README / CONTRIBUTING / docs/api.md 都改成 NewsRead；i18n 的鍵（中文原文）和 en.json / zh-TW.json 一起改。桌面版：`productName` NewsRead、`appId` 改成 `io.github.shaun0457.newsread`（安裝程式不會蓋掉 PaperRead）、`publish: null`；更新來源預設是空的（`easyread/updates.py`、`electron/main.cjs`），打包版不會從 PaperRead 下載更新，設 `EASYREAD_UPDATE_REPOSITORY` 才會檢查。測試 `tests/test_rename.py`、`tests/test_tab_title_strip.cjs`。
- 沒改（開 ticket 74）：資料目錄 `~/PaperRead`、Electron userData、雲端同步的 `PaperRead` 子資料夾、深層連結 `easyread://` / `paperread://`、Docker 的 `/data/PaperRead`。兩個都裝的電腦會共用資料和單一執行個體鎖。
- 也沒改：CI workflow（`grep -q "PaperRead"` 現在靠 i18n 裡的資料夾名稱字串才過，ticket 74 要一起改）、`docs/index.html` / `docs/en` / `docs/demo`（PaperRead 原本的網站和線上展示）、CHANGELOG（歷史紀錄）、`package.json` 的 author。
- Review：python、typescript、code-reviewer 各 1 輪 PASS。修了：分頁標題去掉產品名的 regex 加 ``（不然「Newsreader」開頭的字會被切掉）、`updates.py` 的 `.strip()` 被我誤併進註解。另開 ticket 75（PDF 可選文字快取同大小改動認不出，測試偶爾失敗）、76（有測試真的呼叫本機 Claude Code CLI）。
