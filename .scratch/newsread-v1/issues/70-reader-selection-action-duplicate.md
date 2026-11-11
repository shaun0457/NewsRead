# 70: 閱讀器 `PR.selectionAction` 定義了兩次

**What to build:** `easyread/web/js/reader/anchor.js` 裡 `PR.selectionAction` 被定義兩次（約第 390 行和第 427 行），後面那個蓋掉前面那個。從 PaperRead 帶過來就有，不是 NewsRead 的改動造成的。整理成一個定義，確認選取文字後的標記、筆記、提問（滑鼠按鈕和快捷鍵 `n` / `q`、顏色鍵）行為不變。

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] 先寫測試釘住現在實際生效的行為（第二個定義），包括 `main.js` 的快捷鍵和 `anchor.js` 的按鈕兩個入口
- [ ] 刪掉沒有作用的那個定義；如果第一個定義有第二個沒有的分支，先確認那個分支是不是該保留，再決定
- [ ] 閱讀器相關的 node 測試全過
