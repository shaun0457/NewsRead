# 84: AI 分類的 review 後續

**What to build:** ticket 14 第 1 輪 review（python-reviewer、security-reviewer）的 MEDIUM，當時決定不擋 commit，在這裡補上。

**Blocked by:** 14（AI 分類寫進帳本）

**Status:** needs-triage

- [ ] 分類結果的顯示改成 `POST /api/triage/<id>/show {place}`：伺服器先寫揭露紀錄再回結果；`GET` 只回狀態，不回 AI 的看法（現在要靠畫面自己記得先寫揭露紀錄）
- [ ] 送給 AI 的追蹤對象清單排序：先送文中出現的，再送一般的，最後送已封存的；超過 `ENTITY_BUDGET` 省略的數量記進結果
- [ ] 證據到上限前先檢查，省略的記進 `dropped.evidence`；其他 `EntityError` 照 `WRITE_FAILED` 處理，不吞掉
- [ ] 重新匯入（`unchanged`、`exists`）時，沒有分類狀態的資料補排進待分類（ticket 14 之前匯入的資料）
- [ ] `POST /api/triage/<id>/retry` 只接受 `failed` 的（現在 `pending` 也會被重置次數）
- [ ] `_fail` 在寫入交易裡讀目前的次數，不用排程開始時讀到的值
- [ ] `_context`（追蹤對象和論點清單）每一輪只算一次，不是每則算一次
- [ ] 補上限的測試：`MAX_OUT_ENTITIES`、`MAX_OUT_THESES`、`ENTITY_BUDGET`、`MAX_CTX_THESES`、`THESIS_LINE`、`MAX_BASELINE`、證據上限，以及已退休的論點不送
