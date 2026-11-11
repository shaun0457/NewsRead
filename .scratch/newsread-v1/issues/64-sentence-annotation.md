# 64: 逐句標註進 golden set

**What to build:** 使用者對 AI 起草的因果鏈、概念卡、題材頁句子和證據逐句標「正確 / 錯誤 / 編造」，標註寫進帳本，之後進 golden set。

**Blocked by:** 58（AI 起草題材頁）、60（概念卡與閱讀器自動連結）

**Status:** ready-for-agent

- [ ] 可以標註的目標：因果鏈環節、概念卡的句子、題材頁某個版本的句子、證據
- [ ] 標註只能新增；改標註是新增一筆修正紀錄（測試）
- [ ] 標註指向被標的版本和產生它的 ContextManifest
- [ ] 提供查詢 API；golden set 匯出（#46）包含這些標註
- [ ] 畫面符合已核准的 Mockup B
