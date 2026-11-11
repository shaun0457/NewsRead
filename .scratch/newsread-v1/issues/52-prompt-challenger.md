# 52: Challenger 並行判斷

**What to build:** 換新 prompt 或新模型時，新版本先當 challenger，跟現行版本並行判斷新進的資料。

**Blocked by:** 14（AI 分類寫進帳本）

**Status:** ready-for-agent

- [ ] 每個 AI 任務可以設定 champion 和 challenger 版本
- [ ] challenger 對新進資料並行判斷，寫進帳本並標明版本
- [ ] challenger 的判斷不出現在簡報、今日新聞和推播裡
- [ ] 有試行期和每日上限，有測試碰到上限
- [ ] 不提供用歷史資料回測來決定升級的功能
- [ ] 畫面符合已核准的 Mockup B
