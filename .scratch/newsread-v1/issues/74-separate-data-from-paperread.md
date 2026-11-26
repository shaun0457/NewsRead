# 74: 資料目錄和深層連結和 PaperRead 分開

**What to build:** ticket 06 只改了產品名稱。下面這些還沿用 PaperRead 的名字，和 PaperRead 裝在同一台電腦時會共用同一份資料：安裝版的資料目錄 `~/PaperRead`（`easyread/config.py`）、桌面版的 userData `PaperRead`（`electron/main.cjs`）、雲端同步資料夾底下的 `PaperRead` 子資料夾（`easyread/cloudlib_detect.py`）、深層連結 `easyread://` / `paperread://`（`electron/deep-link.cjs`）、Docker 的 `/data/PaperRead`。改成 NewsRead 自己的，並決定已經在用舊位置的人怎麼搬（不能把 PaperRead 本身的資料當成 NewsRead 的）。

**Blocked by:** 06（改名 NewsRead）

**Status:** needs-triage

- [ ] 安裝版、桌面版、Docker 的資料目錄改成 NewsRead 自己的；從原始碼執行的照舊放在原始碼目錄
- [ ] 已經用 `~/PaperRead` 跑 NewsRead 的人有明確的搬法（自動或提示），不會誤用 PaperRead 本身的文獻庫
- [ ] 深層連結換成 NewsRead 自己的 scheme，不和 PaperRead 搶
- [ ] 雲端同步資料夾的子資料夾改成 NewsRead
- [ ] 文件（README、docs/api.md 的 `.server.json` 位置）一起改
- [ ] 兩個都裝的電腦：Electron 的 `requestSingleInstanceLock` 照 userData 算，現在共用 `%APPDATA%\PaperRead`，一個開著時另一個會開不起來（ticket 06 review 第 1 輪 MEDIUM）
- [ ] `.github/workflows/test.yml` 的 `grep -q "PaperRead"`（第 42、64 行）現在是靠 i18n 裡的資料夾名稱字串才過；改資料夾名稱時一起改成 NewsRead（CI 是單向門，要使用者核准）
- [ ] `vault.py` 的錯誤訊息說「NewsRead 資料目錄」，實際資料夾還叫 PaperRead；搬完之後才一致
- [ ] 原有測試全過，搬資料的路徑有測試
