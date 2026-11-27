# 88: 完整預測照五步寫與行動備註

**What to build:** 完整預測照五步寫：關鍵事實、價值、結構、市場預期差、結論，AI 起草每一步並附出處；另有只給我寫的行動備註。spec user story 117、118，領域模型「Analysis 五步」。（2026-11-26 使用者確認方向）

**Blocked by:** 41（寫成完整預測）

**Status:** needs-triage

- [ ] Prediction 加 `facts`、`value`、`structure`、`gap`、`conclusion`（含期中考的檢查點）、`action_note`
- [ ] AI 起草五步；數字和引述沒有出處的標「AI 推論」（測試）；`gap` 查不到市場預期時寫 `unknown`，不估
- [ ] `action_note` 不出現在任何 AI 呼叫的輸入和 ContextManifest（測試）；不打分
- [ ] 輸入長度有上限，碰到上限的測試
- [ ] UI 先做 mockup 給使用者確認
