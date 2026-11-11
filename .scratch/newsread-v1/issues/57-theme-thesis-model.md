# 57: 題材與論點的資料模型

**What to build:** 建立題材頁、論點、因果鏈環節、證據的資料模型和 API。題材頁和論點有草稿 / 定稿版本，論點狀態的變化寫進帳本。

**Blocked by:** 10（帳本與索引核心）、13（追蹤對象管理）

**Status:** ready-for-agent

- [ ] 題材頁（theme 類型的追蹤對象）可以存：一句話故事、白話類比、起源（市場先動 / 消息先動 + 觸發的 Item 或輪動事件）、第二層效應、目前階段；每個版本標草稿或定稿，草稿不會蓋掉定稿（測試）
- [ ] 論點：一句可以被推翻的說法、`direction_implication`、`timing`（now / roadmap）、賺什麼錢、`horizon`、推翻條件、交易下車條件（可選）
- [ ] 論點狀態（open / strengthening / weakening / refuted / retired）的變化寫進帳本；沒有指向 Evidence 的狀態變化被拒絕（測試）
- [ ] AI 只能提議狀態變化，使用者確認後才生效；確認前論點狀態不變（測試）。論點狀態和「缺第一手確認」只用已經揭露過或使用者判斷過的證據計算，不洩漏還沒判斷的新資料（測試）
- [ ] 因果鏈環節：from → to、關係說明、出處；連到公司時有營收占比（數值或區間 + 出處，或 unknown）和 role（leader / laggard / unknown）
- [ ] 沒有出處的環節標「AI 推論」，不能進定稿，除非使用者手動確認（測試）；沒有來源的營收占比一律 unknown（測試）
- [ ] 證據：Item 或 Story 對論點的關係（strengthens / weakens / related_no_change）、等級 A–D、理由、出處、by（ai / me）
- [ ] 可以查詢某個時間點的題材頁和論點版本（給打分和 golden set 用）
- [ ] 只有 C、D 級證據的論點自動標「缺第一手確認」
