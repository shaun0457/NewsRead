# 04: 移除研究工作區、文獻搜尋、Zotero 與批次匯入

**What to build:** 移除論文專用的功能：arXiv / OpenAlex / Semantic Scholar 文獻搜尋、研究工作區（規劃、閱讀路徑、論文深度剖析、研究任務監控）、Zotero 匯入和批次匯入。

**Blocked by:** 03（把閱讀器仍要用的功能從研究模組抽出來）

**Status:** done（2026-11-11）

- [x] 文獻庫和閱讀器不再出現研究、文獻搜尋、Zotero、批次匯入的入口（「研究探索」按鈕、匯入對話框的資料夾／Zotero 連結、批次「跨論文比較」都拿掉；Zotero RDF 引用匯出保留，那是匯出引用，不是匯入）
- [x] 相關的後端 API 回 404，背景任務和啟動流程不再載入研究模組（`tests/test_research_removed.py`；任務提示在每一頁都只讀 `/api/reader/tasks`）
- [x] 使用者資料夾裡既有的研究資料不刪除，只是不再讀取（`.paperread-planning.sqlite3` 只讀寫 statuses 和 cache；舊的摘要回收站不再列出，清空回收站也不會刪到它）
- [x] 相關測試隨功能移除，其餘測試全過：2026-11-11 Python 519 個、前端 228 個
- [x] 介面文字的 i18n 檢查通過（缺英文 0）

## 留下來的東西

- `sources.py`：貼連結、arXiv 編號、DOI 匯入單篇論文用的，不是文獻搜尋；ticket 11 會再處理。
- `planning_store.py`：縮成閱讀狀態清單和心智圖快取。自訂閱讀狀態原本只能在研究工作區編輯，現在只能看不能改。
- `jobs.bulk`：翻譯佇列，名字同樣叫 bulk，跟成批導入無關。
- `prefs` 的 `research` 鍵：Vault 設定還存在 `research.vault`。
