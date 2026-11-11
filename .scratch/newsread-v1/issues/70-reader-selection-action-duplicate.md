# 70: 閱讀器 `PR.selectionAction` 定義了兩次

**What to build:** `easyread/web/js/reader/anchor.js` 裡 `PR.selectionAction` 被定義兩次（約第 390 行和第 427 行），後面那個蓋掉前面那個。從 PaperRead 帶過來就有，不是 NewsRead 的改動造成的。整理成一個定義，確認選取文字後的標記、筆記、提問（滑鼠按鈕和快捷鍵 `n` / `q`、顏色鍵）行為不變。

**Blocked by:** None (can start immediately)

**Status:** done

- [x] 先寫測試釘住現在實際生效的行為（第二個定義），包括 `main.js` 的快捷鍵和 `anchor.js` 的按鈕兩個入口
- [x] 刪掉沒有作用的那個定義；如果第一個定義有第二個沒有的分支，先確認那個分支是不是該保留，再決定
- [x] 閱讀器相關的 node 測試全過

**Notes（2026-11-12）：** 第一個定義其實是一段壞掉的重複區塊（約 37 行）：選取用的三個 listener 多掛了一份、`showSelbar` 宣告兩次，第一個 `selectionAction` 後半是浮動條的畫面程式，用到沒有定義的 `bar`。它有一個第二個定義沒有的分支 `paper-note`，而浮動條確實有「論文筆記」按鈕，按下去原本會變成一則 kind 是 paper-note 的筆記。保留這個分支、刪掉整段重複。另外在 `insertSources` 加上編輯器還沒掛上時的提示（review MEDIUM）。測試 `tests/test_selection_action.cjs`：1–4 在修改前就過（釘住原本行為），5–6 修改前失敗。
