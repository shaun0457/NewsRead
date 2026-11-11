# 03: 把閱讀器仍要用的功能從研究模組抽出來

**What to build:** 閱讀器的 Obsidian 匯出（含 zip 匯出和受管區塊）、心智圖等功能目前走研究工作區的 API。把它們抽成不依賴研究工作區的獨立模組和 API，行為不變，之後才能安全移除研究工作區。

**Blocked by:** None (can start immediately)

**Status:** done（2026-11-11）

- [x] 列出閱讀器和文獻庫呼叫研究模組的所有 API，逐一標成「保留並抽出」或「隨研究工作區移除」，清單記在這張 ticket 裡；論文專用的功能（文獻搜尋、閱讀路徑、論文深度剖析）標為移除
- [x] 閱讀器匯出到 Obsidian、匯出 zip 的結果跟改動前相同，用回歸測試固定
- [x] 重複匯出時，受管區塊外的手寫內容保留（測試）
- [x] 心智圖照常運作
- [x] 閱讀器不再呼叫研究工作區的 API；研究工作區本身仍可運作（04 才移除）
- [x] 原有測試全過（基準：Python 501 個、前端 233 個），新增的行為有測試：2026-11-11 跑過 Python 595 個（連跑 3 次）、前端 236 個，全部通過

## 盤點：閱讀器和文獻庫呼叫研究模組的 API（2026-11-11）

新的獨立 API 前綴是 `/api/reader`。它的後端模組是 `easyread/reader_api.py`，加上抽出來的 `easyread/vault.py`、`easyread/obsidian_export.py`、`easyread/mindmap.py` 和 `easyread/tasks.py`。這些模組都不 import `easyread.research*`。

### 閱讀器（reader.html）

| 現在呼叫的 API | 呼叫的位置 | 分類 | 抽出後 |
|---|---|---|---|
| `GET /api/research/v1/status`（只看 Vault 設好沒） | reader/export.js、reader/chat-export.js | 保留並抽出 | `GET /api/reader/vault` |
| `POST /api/research/v1/setup`（設定 Vault） | 同上 | 保留並抽出 | `POST /api/reader/vault` |
| `POST /api/research/v2/export/obsidian` | 同上 | 保留並抽出（受管區塊） | `POST /api/reader/export/obsidian` |
| `POST /api/research/v2/export/zip` | reader/export.js | 保留並抽出 | `POST /api/reader/export/zip` |
| `GET` / `POST /api/research/v2/paper/{pid}/mindmap` | reader/export.js、reader/planner.js | 保留並抽出 | `/api/reader/paper/{pid}/mindmap` |
| `POST …/paper/{pid}/mindmap/tasks`、`GET …/tasks/current`、`GET …/tasks/{id}`、`POST …/tasks/{id}/cancel`、`POST …/tasks/{id}/ack` | reader/planner.js、common/research-task-monitor.js | 保留並抽出 | `/api/reader/paper/{pid}/mindmap/tasks…` |
| `GET /api/research/v1/monitor`（背景工作列表） | common/research-task-monitor.js | 保留並抽出（只剩心智圖工作） | `GET /api/reader/tasks` |
| `GET …/paper/{pid}/deep-analysis` 和它的 tasks | reader/planner.js、reader/export.js（匯出選項「論文深度剖析」） | 隨研究工作區移除（論文專用） | 閱讀器拿掉 |
| `GET /api/research/v2`（閱讀狀態清單）、`POST /api/research/v2/item`（閱讀狀態、感興趣） | reader/planner.js | 隨研究工作區移除（論文閱讀規劃） | 閱讀器拿掉 |
| `/research?mode=relation\|topic` 連結（文獻搜尋） | reader/planner.js | 隨研究工作區移除（論文專用） | 閱讀器拿掉 |
| `…/reading-path/tasks*` | common/research-task-monitor.js | 隨研究工作區移除（論文專用） | 閱讀器不再輪詢 |
| `GET` / `POST /api/research/v2/keywords*`、`…/keywords/scan/tasks` | reader/anchor.js（選字「關鍵字」）、reader/panels.js（術語面板「關鍵字」分頁） | 隨研究工作區移除：跨論文關鍵字和主題圖是研究工作區的功能，之後由追蹤對象（13、18）取代 | 閱讀器拿掉 |
| `/research?mode=keywords` 連結 | reader/panels.js | 隨研究工作區移除 | 閱讀器拿掉 |
| `…/v1/tasks/{id}/ack\|cancel` | common/research-task-monitor.js | 隨研究工作區移除 | 閱讀器不再呼叫 |

原本的「研究脈絡」側欄（planner.js）只留下心智圖，改成「心智圖」側欄。它的快捷鍵 R 和工具列按鈕位置都不變。

### 文獻庫（library.html）：03 不動，04 移除

| 現在呼叫的 API | 呼叫的位置 | 分類 |
|---|---|---|
| `GET /api/research/v1/monitor`、reading-path、deep-analysis、v1 tasks 的 ack/cancel | common/research-task-monitor.js | 隨研究工作區移除 |
| `/research` 連結「研究探索」 | library.html | 隨研究工作區移除 |
| `/research?mode=comparisons` | library/batch.js | 隨研究工作區移除 |

### 交給 04 的注意事項

- 心智圖的快取放在 `planning_store` 的 `cache` 資料表裡，鍵是 `mindmap:*`。04 移除研究工作區時，這張表或它的讀法要留下，不然舊的心智圖會讀不到。
- Vault 設定還是存在 prefs 的 `research.vault` 和 `research.folders`。名稱沒改，是為了讓舊使用者的設定照樣能用。
