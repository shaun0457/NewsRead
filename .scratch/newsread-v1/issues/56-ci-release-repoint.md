# 56: CI 和 release 設定改成自己的 repo

**What to build:** release 和 Docker workflow 目前還指向上游的 PaperRead（image 名稱、發佈位置），改成自己的 repo。

**Blocked by:** 06（改名 NewsRead）

**Status:** ready-for-agent

- [ ] release 和 Docker workflow 的 image 名稱和發佈位置改成自己的 repo
- [ ] 這是單向門，commit 時會被 hook 擋下：擱置這張，最後回報時附上給使用者的 approve 碼
- [ ] 不在 v1 的必要路徑上
