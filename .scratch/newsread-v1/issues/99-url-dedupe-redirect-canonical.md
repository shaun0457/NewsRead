# 99: 網址去重看轉址後和 canonical 網址

**What to build:** 判斷重複時，也比對轉址後的網址和可信的 canonical 網址；不一律刪 www、AMP 字串，避免把不同文章併在一起。來源：PR #70 SCOPE Q2。（使用者 2026-11-28 決定照建議做）

**Blocked by:** —

**Status:** done（PR #112，2026-11-28）

- [x] 短網址轉址到已匯入的網址：判為重複（測試）
- [x] canonical 指到已匯入的網址、同網域：判為重複（測試）
- [x] canonical 指到別的網域：不採用（測試）
- [x] 轉址次數有上限，碰到上限的測試


做的時候定的：「同網域」是主機名稱最後兩段相同（`com.tw`、`co.uk` 這種看三段），沒有用 Public Suffix List；canonical 是首頁的不採用（有些網站每篇都寫首頁）。新的一則用可信的 canonical（沒有就用轉址後的網址）當 ID。原本 ticket 11 的 AMP 規則（`amp.` 主機、`/amp`、`?amp=1`）照舊，沒有加刪 www。轉址上限沿用 `fetch.Limits.max_redirects`（5 次）。
