# NewsRead

- 範圍和界線看 `intent.md`，規格看 `docs/spec-v1.md`。動到 AI 呼叫、數字或引述、買賣建議、持股、手機端時，先對照 intent 的「原則與限制」和「不做的事」。
- Ticket 檔 `.scratch/newsread-v1/issues/NN-*.md` 對應 GitHub issue #NN。新 ticket 先開 GitHub issue 拿到編號，再用那個編號建檔（issue 和 PR 共用編號，本機自己往下編會撞號）。狀態變了就更新檔頭的 `**Status:**`，以及 GitHub Project「NewsRead v1」的 Status、Review rounds、AI cost。
- Repo 是 public：commit、ticket、文件裡不放個資和本機私人路徑。

## 完成前的檢查

```bash
python -m pytest -q
node --test tests/test_*.cjs
python scripts/i18n_check.py
ruff check .
```
