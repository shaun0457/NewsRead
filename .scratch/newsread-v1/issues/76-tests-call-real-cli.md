# 76: 有測試真的呼叫了本機的 Claude Code CLI

**What to build:** ticket 06 review 時，完整 `python -m unittest discover tests` 的輸出出現「翻译失败 … Claude Code 出错：You've hit your session limit」，代表有既有的測試沒有用測試替身，真的去呼叫本機的 Claude Code CLI（會用掉使用者的額度，結果也受網路和額度影響）。找出是哪個測試，改成用替身。

**Blocked by:** None (can start immediately)

**Status:** needs-triage

- [ ] 找出呼叫真的 CLI 的測試
- [ ] 改成測試替身；加一個保護（例如測試環境裡呼叫真的 CLI 就直接失敗）
- [ ] 完整測試全過，輸出裡不再出現 CLI 的錯誤
