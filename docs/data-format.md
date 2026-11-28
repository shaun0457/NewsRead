# 資料格式

PaperRead 的核心資料結構以檔案與標準 SQLite 為核心，兼顧單機易讀性、Git 備份友善與高效檢索。

---

## 1. 論文目錄結構 (`papers/{id}/`)

每篇論文擁有獨立目錄，以 PDF 雜湊前 12 碼小寫命名（例如 `papers/a1b2c3d4e5f6/`）。沒有 PDF 的資料（見下方「沒有 PDF 的資料」）用 `t` 或 `w` 開頭的 ID，沒有 `source.pdf`、`pages/`、`layout.json`，另有 `versions/` 存舊版（同一個網址重新匯入、內容變了時）。下表是每則資料目錄裡的檔案：

| 檔案 | 權限/職責 | 說明 |
|---|---|---|
| `paper.json` | 引擎寫入 | 論文中英文雙語內容、排版區塊（Blocks）、中繼資料、術語表與參考文獻 |
| `discussion.json` | 引擎寫入 | 保存於頁邊的 AI 解釋、問答與即時追問記錄 |
| `reader.json` | 使用者寫入 | 讀者劃線、邊注、智慧標註、手寫筆跡（Ink）、文字方塊（`stickers`；舊資料的圖片貼紙保留但不顯示）、全文心得與閱讀進度 |
| `report.json` | 引擎寫入 | 論文深度技術剖析（五維技術審查報告） |
| `layout.json` | 系統生成 | PDF 字元座標與區塊歸一化邊界框（Bounding Box），供原頁燈箱高亮 |
| `item.json` | 系統/使用者 | 閱讀狀態、星標、自定義分類標籤與中繼資料覆蓋 |
| `chat.json` | 系統寫入 | 「問 AI」的多分頁對話記錄、圖片附件與錨定上下文。文章的回答另外存 `answer`（拆好的三段，格式見 api.md 4.55）、`prompt_version`、`manifest`（ContextManifest ID），逐句標記存在 `ratings`：`{"段序.點序": {"verdict": "correct" \| "wrong" \| "fabricated", "at"}}` |
| `job.json` | 系統排程 | 背景翻譯任務狀態（進度、失敗頁面、重試佇列） |
| `source.pdf` | 唯讀原檔 | 使用者匯入的原始 PDF 檔案 |
| `pages/page-*.webp` | 系統生成 | PDF 各頁高解析度光柵圖，供原頁燈箱全頁呈現 |
| `figures/crop-*.webp` | 系統生成 | 自動擷取的圖表檔案（以雜湊防快取衝突） |

書庫根目錄另有 `.url-aliases.json`（`{網址: ID}`，貼的網址和存的 ID 不同時記下，最多 20000 筆；可以刪，刪了只是同一個網址要再抓一次才認得出重複）。

---

## 2. paper.json

```json
{
  "schema": 2,
  "meta": {
    "title_zh": "給評測加上誤差條：語言模型評測的統計學方法",
    "short_zh": "給評測加上誤差條",
    "title_en": "Adding Error Bars to Evals: ...",
    "authors": "Evan Miller",
    "affiliation": "Anthropic",
    "date": "2024 年 11 月 4 日",
    "arxiv": "arXiv:2411.00640v1 [stat.AP]",
    "pdf": "source.pdf",
    "source_sha256": "…",
    "pages": [{"n": 1, "w": 612, "h": 792, "img": "pages/page-001.webp"}]
  },
  "translation": {
    "scope": "全文",
    "done_pages": [1, 2, 3],
    "note": "參考文獻保留原文"
  },
  "glossary": [
    { "en": "standard error", "zh": "標準誤差", "note": "統計術語" }
  ],
  "references": [
    { "id": "1", "text": "原文條目" }
  ],
  "blocks": [ … ]
}
```

### 沒有 PDF 的資料（`meta.kind: "text"`）

純文字和網頁正文由 `easyread/textitem.py` 建立，沿用同一份 paper.json，差別在：

- **ID**：網頁是 `w` + 正規化網址（小寫主機、去掉 `#`、預設埠和 utm/fbclid/gclid 等追蹤參數、查詢參數排序）的 SHA-256 前 11 碼；純文字是 `t` + 內容的 SHA-256 前 11 碼。
- **一段算一頁**：每段是一個 `para` 區塊，`page` 是段落序號（從 1 開始）；`meta.pages` 每段一筆 `{"n": i}`、沒有原頁圖。原文放在 `en`（沿用欄位名，意思是「原文」，不一定是英文）。
- **段落 ID**：`p` + 段落內容的 SHA-256 前 10 碼，同一段出現第二次加 `-2`。內容不變，重新匯入 ID 就不變，劃線和筆記還掛得住。
- **翻譯**：建立時每段都在 `translation.done_pages` 和 `en_pages`，翻譯走「補譯文」流程，每批 12 段，不受「超過多少頁先問我」限制；譯好的段從 `en_pages` 移除，中斷後只譯剩下的。
- **新版本**：同一個網址再匯入、內容變了，舊的 paper.json 存成 `versions/paper-NNNN.json`（最多 50 份，滿了刪最舊的，第一版永遠留著），`meta.version` 加一；內容沒變的段落沿用 ID 和譯文。
- **上限**：全文 40 萬字、2,000 段；單段超過 6,000 字在句尾切開。
- 閱讀器沒有原頁面板，也不顯示 `p.N` 標記。
- **新聞**（`easyread/ingest.py`，`POST /api/ingest`）另外在 `meta` 記：`publisher`（媒體）、`published_at`（帶時區的 ISO 8601，時間不明時是空字串）、`time_source`（`metadata` / `user` / `unknown`）、`published_raw`（頁面上沒有時區的時間原文）、`preview_only`（付費牆後面只抓到預覽）、`canonical_url`（頁面寫的 canonical 原文；可信的那個也是這則的 `source_url` 和 ID 的來源）、`same_language`（原文是中文，譯文欄直接放原文、不送翻譯；譯文語言是台灣繁體、原文是簡體時放 OpenCC 轉成的繁體，另記 `hant_converted: "opencc"`、`title_zh_auto`（自動轉出的標題；`title_zh` 還等於它時，重新匯入跟著更新，改過就不動）；原文是簡體或繁體都記 `target: zh-TW`、`paperread_traditional_v: 1`（閱讀頁打開時不再轉一次））、`manual`（手動貼的全文）、`truncated`（頁面太長，只收了前面收得下的部分）。抓取時間是 `fetched_at`，內容雜湊是 `content_sha256`。

### 區塊（Blocks）定義
每個區塊擁有全域唯一且不可變的 `id`，後續筆記、劃線與原頁定位均錨定於此：

| type | 欄位 | 說明 |
|---|---|---|
| `heading` | `level`(1/2)、`num`、`zh`、`en`、`appendix` | 章節標題。`num` 如 "2.1"、"A"；附錄標記 `"appendix": true` |
| `para` | `zh`、`en`、`role`、`cont` | 段落。`role: "abstract"` 為摘要樣式；`cont: true` 表示緊接公式的未完句 |
| `list` | `ordered`、`items: [{zh, en}]` | 項目清單 |
| `math` | `tex`、`tag` | 獨立行間公式。`tag` 為原文編號（如 "(4)"） |
| `table` | `num`、`head: [[…]]`、`rows: [[…]]`、`align`、`caption_zh`、`caption_en` | 三線書籍表格。單元格支援換行與行內標記 |
| `figure` | `num`、`src`、`box`、`image_en`、`image_zh`、`caption_zh`、`caption_en` | 圖表區塊。`box` 為歸一化裁剪框，`src` 為圖檔路徑 |
| `references` | `zh`、`en` | 參考文獻列表容器（取用 `references` 條目） |
| `note` | `zh` | 正文流內的專題閱讀註解 |

### 行內語法支援
- `$...$`：行內 KaTeX 數學公式（純文字美元符號請跳脫為 `\$`）。
- `**粗體**`、`*斜體*`、`` `程式碼` ``。
- `[7]`、`[2, 5]`：自動連結至文末參考文獻。
- 自動跳轉：文字中的「公式 (4)」、「表 2」、「圖 3」、「第 2.2 節」自動識別為可點選跳轉與懸停預覽的微連結。

---

## 3. reader.json

由前端透過 `/api/p/{id}/ops` 發送原子操作寫入：

```json
{
  "schema": 2,
  "rev": 15,
  "edits": {
    "s1-p3": { "zh": "讀者修訂後的中文", "base": "修改時譯者稿的雜湊", "at": "2026-10-31T12:00:00Z" },
    "tab1#caption": { "zh": "修訂後的表格題注", "base": "…", "at": "…" }
  },
  "notes": {
    "n_123": {
      "id": "n_123", "anchor": "s1-p2", "key": "s1-p2",
      "quote": "選中的文字片段", "prefix": "前文", "suffix": "後文",
      "kind": "note | question | highlight",
      "color": "yellow | green | blue | pink",
      "body": "讀者筆記內容",
      "created": "2026-10-31T12:00:00Z", "updated": "2026-10-31T12:00:00Z",
      "deleted": false
    }
  },
  "ai_annotations": {
    "a_456": {
      "annotation_id": "a_456", "block_id": "s2-p1",
      "quote": "關注語句", "kind": "terminology | methodology | insight",
      "comment": "AI 生成的智慧洞察", "created_at": "…", "updated_at": "…"
    }
  },
  "ink": {
    "i_789": {
      "id": "i_789", "group": "g_01", "anchor": "s1-p2", "textHash": "1234abcd",
      "ref": [620, 180], "points": [[20, 30], [22, 34]],
      "color": "#d94b4b", "width": 2,
      "updated": "2026-10-31T12:00:00Z", "deleted": false
    }
  },
  "stickers": {
    "stk_01": {
      "id": "stk_01", "assetId": "star-01", "anchor": "s1-p2", "textHash": "1234abcd",
      "ref": [620, 180], "x": 20, "y": 30, "width": 80, "height": 80,
      "rotation": 0, "opacity": 0.9, "z": 1, "locked": false,
      "strokeColor": "#d94b4b", "strokeWidth": 2,
      "href": "https://...", "textColor": "#23211d", "textSize": 14, "textBold": false,
      "text": "圖章文字", "updated": "2026-10-31T12:00:00Z", "deleted": false
    }
  },
  "paper_note": {
    "body": "全篇論文綜合筆記（支援 Markdown 與 KaTeX）",
    "at": "2026-10-31T12:00:00Z"
  },
  "progress": {
    "block": "s3-1-p2", "ratio": 0.42, "at": "2026-10-31T12:00:00Z"
  }
}
```

---

## 4. report.json（論文深度剖析，已停用）

深度剖析在 ticket 04 移除。舊版留下的 `report.json` 不會被刪，也不再讀取。

```json
{
  "schema": 1,
  "paper_id": "a1b2c3d4e5f6",
  "markdown": "## 1. 核心主張與證據對照\n...\n## 2. 消融實驗審查 (Ablation Audit)\n...\n## 3. 關鍵公式拆解與數值示範 (Formula & Toy Example)\n...\n## 4. 基準線公平性與數據審查\n...\n## 5. 局限性、邊界與盲點\n...",
  "focus": "重點檢視 Transformer 注意力層的計算量瓶頸",
  "model": "claude-3-7-sonnet",
  "created_at": "2026-10-31T10:00:00Z",
  "updated_at": "2026-10-31T10:00:00Z"
}
```

---

## 5. discussion.json（AI 頁邊問答）

```json
{
  "schema": 2,
  "entries": [
    {
      "id": "d001-ab12c",
      "anchor": "s2-1-p4",
      "quote": "對它進行推斷",
      "kind": "explain | qa | insight | reply | check",
      "title": "原句推導疑問",
      "body": "詳細解答內容...",
      "reply_to": "n_123",
      "at": "2026-10-31T11:00:00Z"
    }
  ]
}
```

---

## 6. layout.json（原頁歸一化座標定位）

```json
{
  "s1-p3": {
    "page": 1,
    "src": "text",
    "box": [0.08, 0.10, 0.92, 0.90],
    "boxes": [
      [0.08, 0.60, 0.48, 0.90],
      [0.52, 0.10, 0.92, 0.30]
    ]
  }
}
```

每個座標方框均為以原 PDF 頁面寬高為基準的歸一化數值 `[x0, y0, x1, y1]`。`boxes` 支援多欄排版中折行段落的分段精準框選。

---

## 7. 文獻庫狀態資料庫 (`.paperread-planning.sqlite3`)

存放於資料目錄根目錄下，採用 SQLite WAL 模式。ticket 04 移除研究工作區之後，程式只讀寫 `statuses` 和 `cache` 兩張表；其餘表是舊版留下的研究資料，不刪除、不再建立也不再讀取：

- **`statuses`**：文獻庫的閱讀狀態清單（`id`, `label`, `color`, `position`, `builtin`）。
- 舊版留下、不再讀取的表：`saved_papers`（候選論文與研讀計劃）、`candidates`（文獻搜尋的候選池）、`paper_summaries` 與 `paper_summary_trash`（AI 預讀摘要和它的回收站）、`milestones`、`follows`、`skipped`、`reminder_claims`、`keywords`、`keyword_links`、`keyword_scans`、`keyword_exclusions`（跨論文關鍵字）。
- **`cache`**：心智圖（`mindmap:*`）與心智圖背景工作狀態（`mindmap:task:*`）的快取；舊版的閱讀路徑快取（`reading-path:latest`）不再讀取。

---

## 8. Obsidian 知識庫匯出目錄規範

在觸發匯出至 Obsidian 時，系統於目標 Vault 建立嚴格隔離的 6 大專題目錄：

```text
Vault Root/
├── 01-論文分析/          # 核心觀點、架構剖析與引文導讀
├── 02-心智圖/            # Markmap 階層大綱與雙向結構圖
├── 03-閱讀標註/          # 匯總全文劃線、邊注與 AI 洞察
├── 04-論文深度剖析/      # 五維技術審查（Claims, Ablations, Toy Example 等）
├── 05-跨論文比較/        # 多篇論文之橫向綜合比較
├── 06-論文摘要/          # 候選論文精簡速讀摘要
└── .paperread-index.json # 匯出索引與雜湊映射表
```

### 使用者自定義筆記保護機制
匯出之 Markdown 檔案均包含受管區塊標記：

```markdown
<!-- paperread:managed:start -->
# 系統自動生成之結構化內容
...
<!-- paperread:managed:end -->

## 我的個人心得與延伸思考
讀者在此區塊手動撰寫的心得、待辦清單或 [[內部雙向連結]]，在後續覆蓋更新時均獲得 100% 完整保留。
```

---

## 9. NewsRead 索引資料庫 (`newsread.sqlite3`)

放在資料目錄根目錄，SQLite WAL 模式。帳本相關的表（`stories`、`item_story`、`ledger`、`context_manifests`、`ai_usage`、`prompt_versions`、`prompt_current`、`exposures`）見 `easyread/ledger.py`，其中帳本類的表由 trigger 擋掉更新和刪除。`exposures` 是揭露紀錄：`item_id`、`place`（`board`、`theme`、`today`、`digest`、`push`、`reader`、`quiz`、`ask_ai`）、`at`；同一則資料同一個地點只記第一次，之後的判斷用它決定 `blind`。追蹤對象（ticket 13）放在同一個檔案：

- **`entities`**：`id`（`E-` 加 32 位十六進位）、`type`、`name`、`benchmark`（`NULL` = 用預設）、`industry_index`、`archived`、`created_at`、`updated_at`。封存只設 `archived=1`，不刪資料。
- **`entity_listings`**：`entity_id`、`position`（0 是主要代號）、`market`、`symbol`；`(market, symbol)` 全域唯一。
- **`entity_aliases`**：`entity_id`、`position`、`alias`、`folded`（比對用的小寫）。
- **`theme_versions`、`thesis_versions`**（ticket 57）：題材頁和論點的版本，只能新增。`id`（`TV-` / `PV-` 開頭）、`theme_id` 或 `thesis_id`、`version`（從 1 起）、`status`（`draft` / `final`）、`by`（`me` 或 `ai:<model>@<prompt 版本>`）、`created_at`、`body`（JSON，欄位見 api.md 4.62）、`content_hash`、`context_manifest`（AI 才有）。AI 的版本同時在帳本記一筆 `draft` 紀錄，payload 是 `{target: theme | thesis, of: 題材或論點 id, version_id, version, content_hash}`。
- **因果鏈環節**（ticket 59，沒有自己的表）：存在 `theme_versions.body` 的 `chain` 陣列裡，每一環 `{from, to, relation, source, inferred, confirmed, revenue_share?, role?}`；`from` / `to` 是 `{entity_id}` 或 `{label}`，`source` 是 `{url}` 或 `{item_id}`（沒有就是 `null`，`inferred` 為 true）。`confirmed` 只有我能設，且只在沒有出處的環節上有意義。連到公司的環節才有 `revenue_share`（`"unknown"` 或 `{value | range, source}`）和 `role`。清單頁的每次修改都新增一個草稿版本，舊版本不動。
- **`theses`**：論點屬於哪個題材，只能新增。`id`（`T-` 開頭）、`theme_id`、`created_at`。論點狀態不存在這裡，存在帳本的 `thesis_status` 紀錄：AI 的是提議（`proposal: true`），`who = me` 的才生效（`{thesis_id, from, to, evidence, reason, confirms}`；駁回是 `{thesis_id, rejects, reason}`）。
- **`evidence`**：證據，只能新增。`id`（`EV-` 開頭）、`thesis_id`、`item_id` 或 `story_id`（二選一）、`relation`、`grade`（A–D）、`reason`、`source`（JSON）、`by`、`created_at`、`context_manifest`。
- **`triage_state`**（ticket 14）：每則資料目前的 AI 分類狀態（可以改）：`item_id`、`content_hash`（排進來時的內容）、`state`（`pending` / `done` / `failed`）、`attempts`、`next_at`、`error`（只存代碼）、`result_id`、`updated_at`。額度保護暫停時（ticket 68）資料留在 `pending`、不算次數，`updated_at` 是排進來的時間，補做時依它排序。
- **`ai_guard_events`**（ticket 68）：額度保護和 API 上限的事件，欄位見第 10 節最後。
- **`triage_results`**：分類結果，只能新增。`id`（`TR-` 開頭）、`item_id`、`content_hash`、`who`、`created_at`、`body`（JSON，欄位見 api.md 4.66）、`context_manifest`。同一個交易裡也寫 AI 連結、證據和帳本的 `judgment` 紀錄。
- **帳本的 `judgment`（AI 分類寫的）**：`who = ai:<model>@triage-v1@<引擎>/<模型>`，payload `{item, story, target: {type: thesis | entity, id}, thesis_version?, relation, signal, importance, importance_signal, noise_kind, confidence, reason, blind: null, retrospective, time_unknown, engine, model, prompt_version, content_hash, baseline: [{entity, benchmark, industry_index, basket_version}]}`。`signal` 由 `relation` 推出（加強、削弱、偏多、偏空、中性）；`importance_signal` = 重要度高或中。`retrospective` = 發布後超過 2 個交易日才判斷（交易日先用週一到週五、台北時間算，國定假日也算進去）；時間不明的資料 `time_unknown = true`、不標事後補判。`baseline.basket_version` 在題材籃子（ticket 32）之前都是 `null`。ContextManifest 在 AI 回答之後才記，判斷時間是送出前的時間。
- **`mentions`**：資料和追蹤對象的連結，`(item_id, entity_id)` 唯一；`source` 是 `ai` 或 `manual`。`removed=1` 是手動移除留下的紀錄，AI 不能再連回去，也不能蓋掉手動的連結。`created_at` 是連上的時間（移除後再連回來才重設），`updated_at` 是最後一次改動。一個追蹤對象最多 5000 筆。

## 10. AI 引擎設定 (`ai.json`)

放在資料目錄根目錄（跟 `config.json` 分開，因為 `/api/config` 會把整份設定回給頁面），只存在這台電腦；非 Windows 系統上權限設成只有自己能讀（0600）。內容（ticket 67，格式見 `easyread/ai_engines.py`）：

- **`tasks`**：每種工作的 `primary` / `fallback`，各是 `{engine, model, entry}` 或 `null`（自動 / 不用備用）。
- **`anthropic`**：`{key, status, tested_at, code}` 或 `null`。
- **`openai`**：OpenAI 相容服務的清單，每個 `{id, name, base_url, api, model, key, status, tested_at, code}`，最多 10 個。
- **`engines`**：本機 CLI 最近一次呼叫的結果 `{auth, at, billing}`。
- **`guard`**（ticket 68，額度保護，見 `easyread/quota_guard.py`）：`{background_subscription, threshold, on_exceed, api_monthly_usd}`。
  - `background_subscription`：背景工作能不能用訂閱 CLI，預設 `false`（條款不明確，見 ticket 68 的條款查證）。
  - `threshold`：Claude Code 5 小時額度到幾 % 就保護，1–100 的整數，預設 `70`。
  - `on_exceed`：超過門檻時 `wait`（等重置，預設）或 `api`（改用 API key）。
  - `api_monthly_usd`：API 每月上限（美元），0–100000，預設 `15`。

手改壞掉的欄位讀進來時會被丟掉，改回預設。

額度保護的事件存在 `newsread.sqlite3` 的 **`ai_guard_events`**（可以刪，最多留 1000 筆，多的刪最舊的）：`seq`、`at`、`code`（`QUOTA_PAUSED`、`QUOTA_SWITCHED_API`、`BACKGROUND_NO_API`、`API_CAP_WARN`、`API_CAP_REACHED`、`API_CAP_STOPPED`、`CATCHUP_DONE`、`RATE_LIMITED`）、`task`（工作；每月一次的 API 通知是空字串）、`key`（去重用：同一段暫停的重置時間；API 通知、`API_CAP_STOPPED`、`BACKGROUND_NO_API` 是月份；`RATE_LIMITED` 是 10 分鐘的時段）、`data`（JSON，只有固定欄位：`used`、`threshold`、`until`、`spent_usd`、`cap_usd`、`month`、`count`）。不存上游原文。
