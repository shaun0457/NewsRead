# 參與貢獻

歡迎提 Issue 和 PR。下面是一些約定，照著來能更快合併。

## 本地跑起來

需要 Python 3.10+。

```bash
git clone https://github.com/YOUR_GITHUB_USERNAME/PaperRead.git
cd PaperRead
python -m pip install -e .
easyread
```

瀏覽器會開啟 `http://127.0.0.1:8765`。也可以直接用 `start.cmd`（Windows）或 `./start.sh`（macOS / Linux）。

改桌面版（Electron）還需要 Node.js 22+，見 README 的“桌面版”一節。

## 跑測試

```bash
python -m unittest discover tests -v
node --test tests/test_*.cjs
```

提 PR 後 GitHub Actions 會在 Windows、macOS、Linux 上自動跑一遍。第一次貢獻的 PR 需要維護者點一下批准才會開始跑，稍等就好。

## 提 PR

- 一個 PR 只做一件事，方便審和回退。
- 標題和說明寫清楚改了什麼、為什麼改；修 bug 的話寫一下怎麼復現。
- 改了介面的，附一張截圖。
- 修了 bug 或加了功能，儘量在 `tests/` 裡補一個測試。
- 不用改 `CHANGELOG.md` 和版本號，發版時維護者統一寫。

## 介面文字

介面跟著系統語言顯示中文或英文。寫程式碼時只寫中文，外面套一層：前端 `PR.t("已匯入 {n} 篇", { n })`，後端 `tr("已匯入 {n} 篇", n=n)`。英文寫在 `easyread/web/i18n/en.json`，缺了的話測試會報出來；不方便寫英文就在 PR 裡說一聲，維護者來補。Python package 和 CLI 仍沿用 `easyread` 名稱，以維持既有指令碼與資料相容。

`python scripts/i18n_check.py` 會列出沒套 `PR.t` / `tr` 的中文和缺英文的詞條。確實不該翻譯的中文（比如給模型的提示詞），在那一行末尾加註釋 `i18n-ok`。

## 報問題

直接開 Issue 就行，有模板提示要寫哪些資訊，填不全也沒關係。
