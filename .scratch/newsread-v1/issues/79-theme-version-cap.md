# 79: 題材頁的版本上限會被因果鏈編輯用完

**What to build:** 題材頁和論點最多 500 個版本（`narratives.MAX_VERSIONS`，ticket 57）。因果鏈清單（ticket 59）每改一環就寫一個新的草稿版本：從零建一條 30 環的鏈加上確認和修正，就要 60–90 個版本，再加上 AI 草稿，長期追蹤的題材會碰到上限。到上限之後所有修改都回「版本最多 500 個」，**連 publish 也是**；版本表是 append-only，清不掉，最後那份草稿就再也進不了定稿。（ticket 59 python-reviewer 第 1 輪 MEDIUM）

**Blocked by:** 59（因果鏈清單）

**Status:** needs-triage

- [ ] 決定做法（要回頭看 ticket 57 的資料模型），例如：publish 不受上限限制或保留額度；同一段時間內「我」連續的草稿合併成一版；上限只算定稿
- [ ] 測試：patch `MAX_VERSIONS`，因果鏈的 add 和 publish 碰到上限時回 400 和看得懂的訊息，而且 publish 照決定的做法能過
