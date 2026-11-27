# 66: Windows 安裝版與系統匣

**What to build:** 像 PaperRead 一樣，使用者下載 Windows 安裝檔就能用。關掉視窗會縮到系統匣，抓取和 Telegram 繼續跑；從系統匣按「結束」才停。

**Blocked by:** 06（改名 NewsRead）、07（常駐與排程器）

**Status:** ready-for-agent

- [ ] 沿用 PaperRead 的 Electron 打包，產出 Windows 安裝檔；安裝後可以從開始選單打開
  （打包設定沿用 package.json 的 nsis，沒改；這次沒有實際打包：要先 `npm install`，`build:backend` 要 PyInstaller，
  這台機器沒裝而且記憶體小。要驗證：`pip install pyinstaller` → `npm install` → `npm run dist`，裝好後從開始選單打開）
- [x] 關掉視窗後縮到系統匣，server、排程仍在跑（tests/test_desktop.cjs）。Telegram polling 還沒做（08），做了之後跑在同一個後端裡
- [x] 系統匣選單有「打開」和「結束」；結束時先讓頁面存檔，再走 /api/shutdown（每一步 8 秒上限，逾時就 taskkill），
  後端的排程在 `launch._stop` 的 STOP_TIMEOUT 內停掉（07 的測試）
- [x] 設定頁的「開機自動啟動」對安裝版有效：Electron 的登入項目，帶 `--hidden` 直接縮在系統匣；開發中的 electron.exe、
  macOS / Linux 不提供開關。原始碼版仍然用 `easyread autostart`
- [x] 同時打開第二個時，聚焦到已經在跑的那個（藏在系統匣的也會打開），不會跑出兩個 server。
  start.cmd 的服務已經在跑時（後端以代碼 3 結束），只接手 `http://127.0.0.1:埠號`，而且要先打 `/api/version`
  （3 秒、4096 字上限）確認是活著的 NewsRead；結束桌面版時不關它。讀不到位址、確認不了就報錯
- [x] 設定頁顯示版本（`/api/version`）；更新來源 06 已經先關掉
- [x] 只驗證 Windows；macOS / Linux 沿用上游的行為（沒有系統匣，關掉最後一個視窗就結束），不驗證
- [x] release workflow 屬於單向門（見 56），這張只在本機打包，不改 CI

**留下來的：**
- 接手的服務之後自己停掉了，桌面版不會發現，要重開桌面版。
- `/api/version` 只擋得住舊位址和撞埠；同一個使用者權限的程式刻意假裝成 NewsRead 擋不住（不在威脅模型內）。
- Electron 當掉、只有 NewsRead.exe 被強制結束時，它開的打包後端會留著；下次打開桌面版會接手它，但結束時不會關它
  （看不出是不是自己開的）。要停用 `easyread stop` 或工作管理員。
- Windows 關機、登出時 Electron 不發 before-quit：頁面最後幾秒沒存的東西可能遺失，後端被系統直接結束（帳本是 SQLite 交易，不會寫一半）。
  沒在實機驗證；之後可以接 `session-end` 做有上限的存檔。
- 藏在系統匣開機啟動時，視窗上次是最大化的話，第一次打開不會恢復最大化。

**07 留下來的：** 後端已經有單一執行個體鎖（`easyread/instance.py`）。Electron 用 `serve --port 0` 啟動自己的後端，
已經有 start.cmd 的服務在跑時會被鎖擋下、以代碼 3 結束（stdout 印「NewsRead 已經在執行：URL」）；這張要改成接手那個服務或提示使用者。
原始碼版的開機自動啟動在 `easyread/autostart.py`（HKCU Run，CLI `easyread autostart`）；安裝版改用 Electron 的開機項目，設定頁開關也在這張。
