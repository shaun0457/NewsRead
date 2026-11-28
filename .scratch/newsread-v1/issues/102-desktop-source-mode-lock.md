# 102: 原始碼模式桌面後端的單一實例鎖

**What to build:** 原始碼模式的桌面後端（`serve --port 0`）碰到 start.cmd 常駐的單一實例鎖時，改走 #73 的「接手服務」，不以代碼 3 退出；補驗收。來源：PR #72 SCOPE Q1。（使用者 2026-11-28 決定照建議做）

**Blocked by:** 73（接手服務）

**Status:** done（PR #117，2026-11-28）

- [x] start.cmd 常駐時開桌面版：接手現有服務、不退出（測試）
- [x] 實機跑一次並記錄結果

## 實機紀錄（2026-11-28，Windows 11，原始碼模式）

#73（ticket 66）之後程式已經走接手的路：`serve --port 0` 不先問 `running_server`，碰到鎖就印出位址、以代碼 3 結束，桌面版讀到位址、確認 `/api/version` 後接手。這張只補驗收，沒有改程式。

用暫時的 `EASYREAD_HOME`（不碰真正的文獻庫）：

1. 先跑一個常駐服務 `python -m easyread serve --port 0`（start.cmd 開的那種，占住鎖）：`http://127.0.0.1:54935`
2. 再跑桌面版原始碼模式的後端指令 `python -m easyread serve --port 0`：代碼 3，輸出「NewsRead 已經在執行：http://127.0.0.1:54935，不再啟動第二個。…」
3. 桌面版的 `electron/tray.cjs` `runningUrl` 讀這段輸出：`http://127.0.0.1:54935`
4. `python -m easyread stop` 停掉第一個服務

沒跑的：Electron 視窗本身（實機的 `npx electron .`）。接手之後的視窗、系統匣行為由 `tests/test_desktop.cjs` 涵蓋，第 2 步的那一行原樣放進測試。
