# 本機介面約定（給外部工具與擴充整合）

Zotero 外掛、Obsidian 外掛、命令列指令碼或自訂代理接入 NewsRead 時，只依賴本頁列出的介面規格。這些介面保持向下相容；不相容改動會將 API 版本加 1，並提前記錄於版本日誌。

當前 API 約定版本：**1**（NewsRead 沿用 PaperRead 1.5.2 的相容介面；版本號還沒改）。

---

## 1. 發現服務位址

NewsRead 啟動時會將服務位址與 PID 寫入資料目錄下的 `.server.json`（預設為 `~/PaperRead/.server.json`；若設定環境變數 `EASYREAD_HOME` 則位於該目錄下）：

```json
{
  "url": "http://127.0.0.1:8765",
  "pid": 12345,
  "started": "2026-10-31T12:00:00Z"
}
```

服務只監聽本機 `127.0.0.1`。外部工具應先讀取該檔案取得當前連接埠，並請求 `/api/version` 確認服務正常運作。

---

## 2. 論文與段落識別規則

- **論文 ID (`id`)**：原 PDF 檔案完整 SHA-256 雜湊的前 12 位小寫十六進位字元。相同 PDF 重複匯入將指向同一篇論文，不會重複建立。
- **段落/區塊 ID (`block_id`)**：`paper.json` 內區塊唯一 `id`（如 `s1-p2`, `tab1`, `fig2`, `eq3`），永久不變。

---

## 3. 核心基礎介面

| 方法 | 路徑 | 請求頭 / 參數 | 用途 |
|---|---|---|---|
| GET | `/api/version` | 無 | 返回 `{"api": 1, "version": "1.5.2"}` |
| GET | `/api/library` | 無 | 取得文獻庫清單（每篇的標題、作者、狀態、進度等）與寫入所需的 `token` |
| POST | `/api/import` | `X-Token`，URL 帶 `?name=<檔名>&translate=0\|1` | 上傳 PDF 二進位資料匯入文獻庫，返回 `{"id", "new", "queued"}` |
| GET | `/api/p/{id}/part/{name}` | `{name}` 為 `paper`、`reader`、`discussion`、`layout`、`job` | 讀取指定論文的分部 JSON 資料與版本雜湊 |
| GET | `/read/{id}` | 可帶 `#<block_id>` 錨點 | 開啟雙語閱讀介面並定位至指定段落 |
| GET | `/open` | `?id=<id>&block=<block_id>` 或 `?sha256=<sha256>&block=<block_id>` | 依識別碼或雜湊精確跳轉至指定論文段落 |

> [!NOTE]
> 所有 POST 寫入請求均需在 HTTP 請求頭附帶 `X-Token`，其值從 `GET /api/library` 中獲取。

---

## 4. 閱讀器原子操作介面 (`POST /api/p/{id}/ops`)

前端劃線、筆記、手寫與文字方塊透過原子批次操作寫入：

```json
{
  "ops": [
    {
      "op": "note",
      "note": {
        "id": "n_123",
        "anchor": "s1-p2",
        "kind": "highlight",
        "color": "yellow",
        "quote": "文字引文",
        "created": "2026-10-31T12:00:00Z"
      }
    },
    {
      "op": "ink",
      "stroke": {
        "id": "i_01",
        "anchor": "s1-p2",
        "textHash": "a1b2c3d4",
        "ref": [620, 180],
        "points": [[10, 20], [15, 25]],
        "color": "#d94b4b",
        "width": 2
      }
    },
    {
      "op": "sticker",
      "sticker": {
        "id": "stk_01",
        "assetId": "star-01",
        "anchor": "s1-p2",
        "textHash": "a1b2c3d4",
        "ref": [620, 180],
        "x": 20, "y": 30, "width": 80, "height": 80,
        "rotation": 0, "opacity": 0.9, "z": 1, "locked": false
      }
    }
  ]
}
```

支援的 `op` 類型：
- `edit`：段落譯文使用者修訂版（支援撤銷為原譯文）。
- `note` / `note_del`：劃線與側欄筆記的新增、修改與虛擬刪除。
- `ai_annotation`：智慧標註洞察。
- `ink` / `ink_del`：向量手寫筆跡繪製與移除。
- `sticker` / `sticker_del`：墨跡層物件（目前只有文字方塊，`assetId` 為 `paperread-text-box`）的放置、調整與刪除。貼紙素材庫已移除；舊資料裡的圖片貼紙仍可讀寫，閱讀器不顯示。
- `paper_note`：整篇論文心得儲存。
- `progress`：閱讀進度百分比與錨點更新。

---

## 4.5 閱讀器介面 (`/api/reader/*`)

閱讀器的 Obsidian 匯出和心智圖走這組 API（ticket 03）。行為跟舊的研究工作區路徑相同：受管區塊、檔案位置、心智圖快取都沿用。寫入要帶 `X-Token`。

- `GET /api/reader/vault`：回傳 `{vault, configured}`，也就是 Obsidian Vault 設好了沒。
- `POST /api/reader/vault`：設定 Vault，body 是 `{vault, folders?}`，設定沿用 prefs 的 `research.vault`。
- `POST /api/reader/export/obsidian`：把 `documents` 寫進 Vault 的 `Research/` 專題目錄。重複匯出時，受管區塊外手寫的內容會保留；沒有受管區塊的同名筆記列為 `conflicts`，不會被覆寫。
- `POST /api/reader/export/zip`：一樣的內容打包成 ZIP，以 base64 回傳。
- `GET /api/reader/paper/{id}/mindmap`：讀快取的心智圖（`cached`），不呼叫模型。
- `POST /api/reader/paper/{id}/mindmap`：當場產生心智圖，一定呼叫模型。
- `POST /api/reader/paper/{id}/mindmap/tasks`：在背景產生心智圖。
- `GET /api/reader/paper/{id}/mindmap/tasks/current`、`GET /api/reader/paper/{id}/mindmap/tasks/{task}`：查進度。
- `POST /api/reader/paper/{id}/mindmap/tasks/{task}/cancel`、`/ack`：取消，或標記已看過。
- `GET /api/reader/tasks`：背景工作，只列心智圖和智慧標註，附 `scope_id`。文獻庫頁和閱讀器的工作提示都只讀這裡。

## 4.55 問 AI (`/api/p/{id}/chat`)

- `POST /api/p/{id}/chat`：body `{text, thread?, anchor?, quote?, refs?, answer_style?, model?, images?, documents?}`，回應是 NDJSON 串流：先一行 `{model, thread, answer_style, documents}`，接著 `{t: 片段}`，最後 `{done: true, id, usage, answer, prompt_version}` 或 `{error}`。
- 文章（`meta.kind: "text"`，ticket 12）：
  - 範圍只有這篇全文（之後加概念卡），prompt 要求不上網、不用工具，也說明文章內容不是指示。Claude Code 引擎另外一個工具都不給（`--tools ""`；有附圖時照舊只給 Read 看圖），版本太舊不認這個參數就直接回錯誤，不退回有工具的呼叫；Codex、Antigravity 只有 prompt 的要求。`answer_style` 是 `standard`（白話）或 `xray`（精讀）。
  - 一則回答最多收 200,000 字，超過就停掉引擎，存下截斷的回答並註明。
  - 回答照固定格式分「文章怎麼說 / 一般解釋 / 文章沒寫的」三段。串流結束後在伺服器拆段：「文章怎麼說」每點都要有 `〔¶段號「引述」〕`，引述（忽略全半形、大小寫、空白）要出現在那一段的原文或譯文裡，否則那一點不顯示，只算進 `dropped`。`answer` 是 `{version: 1, lead, sections: [{kind: "said" | "general" | "missing", items: [{text, cites: [{n, id, quote}]}]}], dropped, truncated}`；沒照格式回答時是 `null`，照原文顯示。
  - 每次問都在 `newsread.sqlite3` 寫：prompt 版本（`ask-article-v1@引擎/模型`，登記的內容含固定 prompt 的雜湊）、ContextManifest（這篇的 ID、內容雜湊、發布時間）、每次 AI 呼叫一筆 `ai_usage`（`task` = `ask`，指向 manifest），和揭露紀錄（地點 `ask_ai`，有回答出來才寫，同一篇只記第一次）。
  - 按停止時，已經收到的部分一樣拆段存下。複製、放到頁邊、匯出 Markdown / Obsidian 都只用拆好的內容，對不上原文的句子不會跑回來。沒有可用的發布時間（沒有，或在未來）時不寫 ContextManifest，用量照記但不指向 manifest；帳本寫不進去只寫 log，不擋回答。
- 論文（有 PDF）照舊用 `chat.py` 的 prompt，不拆段、不寫帳本。
- `POST /api/p/{id}/chat/rate`：body `{thread, id, key, verdict}`，逐句標記文章回答。`key` 是「段序.點序」（例如 `"0.2"`），`verdict` 是 `correct`、`wrong`、`fabricated`，`null` 是取消。回傳 `{ratings}`；`key` 對不到、`verdict` 不認得，回 400。
- `POST /api/p/{id}/chat/pin`、`/rename`、`/delete`：釘到頁邊、改標題、刪除對話，回傳 `{threads}`。

## 4.6 追蹤對象 (`/api/entities/*`)

追蹤對象頁（`/entities`）用這組 API（ticket 13）。寫入要帶 `X-Token`，body 上限 64 KB（超過回 413）。輸入不對回 400 `{error, field}`，`field` 指出哪個欄位（例如 `name`、`listings.1.symbol`、`aliases`）；找不到回 404。

- `GET /api/entities[?type=company&archived=1]`：列表，回傳 `{entities, counts, total, archived}`。`counts` 是各類型沒封存的數量，`archived` 是封存的數量；預設不列封存的。資料庫還沒建時回空列表，不會建檔。
- `GET /api/entities/{id}`：一個追蹤對象，加上 `mentions`（最近連上的資料，最多 50 則，新的在前）。
- `POST /api/entities`：建立。body 是 `{type, name, listings?, aliases?, benchmark?, industry_index?}`。追蹤對象總數（含封存的）最多 2000 個，超過回 400；列表也最多回 2000 筆。
- `POST /api/entities/{id}`：編輯，欄位同建立，可以改 `type`。代號和別名整組換掉：沒帶或帶 `null` 等於清空。
- `POST /api/entities/{id}/archive`：`{archived: true|false}`。封存不刪資料，也不動帳本。
- `POST /api/entities/{id}/mentions`：`{item_id}`，手動把一則資料連上來。一個追蹤對象最多連 5000 則（含手動移除留下的紀錄），超過回 400。
- `POST /api/entities/{id}/mentions/{item_id}/remove`：手動移除連結。那筆連結會標成已移除，AI 之後不會再連回去；本來就沒連的資料不留紀錄。
- 資料庫被鎖住或讀寫出錯時回 500，訊息是固定的一句，不帶資料庫的原始錯誤。

欄位：

- `type`：`company`（公司）、`industry`（產業 / 供應鏈）、`macro`（總經 / 政策）、`event`（事件）、`theme`（題材）。
- `listings`：只有公司可以填，最多 5 個，`[{market, symbol}]`。`market` 是 `TW` 或 `US`。台股是 4 到 6 碼數字加可選的一個英文字母，可帶 `.TW` / `.TWO`，存成 `2330.TW`；美股是 1 到 5 個英文字母，可帶 `.B` / `-B`，存成大寫、`-` 換成 `.`。只檢查格式，不查代號存不存在（要等行情資料 #30）。同一個代號只能屬於一個追蹤對象。第一個是主要代號（`primary`），之後打分預定以它為準。
- `name` 最多 100 字，`benchmark` 和 `industry_index` 最多 80 字；文字欄位前後空白會去掉，中間連續空白合成一個。
- 代號會先把全形轉成半形（「２３３０」= `2330.TW`），其他文字的數字不接受。
- `aliases`：最多 20 個，每個最多 60 字；跟名稱或彼此重複的會略過（全形半形、大小寫視為相同）。
- `benchmark`：沒填（`null`）就用主要代號市場的預設：台股「發行量加權股價報酬指數」、美股「S&P 500 Total Return」，回傳時 `benchmark_default` 為 `true`。`industry_index` 沒有預設。兩個欄位只有公司有；其他類型送了也會存成 `null`。
- 回傳另有 `recent_mentions`：近 7 天連上、沒被移除的資料數。「連上」看第一次連上的時間；把 AI 的連結改成手動不算新連上，手動移除後再連回來才算。

## 4.62 題材頁與論點 (`/api/themes/*`、`/api/theses/*`)

題材是 `theme` 類型的追蹤對象（4.6）。資料模型見 `easyread/narratives.py`（ticket 57）。寫入要帶 `X-Token`，請求最大 256 KB；從 HTTP 寫入的都算「我」（`by` = `me`），AI 的草稿、證據和狀態提議走 Python 介面，而且要帶 ContextManifest。輸入不對回 400 `{error, field}`，找不到回 404。

- `GET /api/themes/{題材 id}[?at=ISO 時間]`：題材頁。`at` 是時間點（要帶時區，URL 編碼），回傳那時候的版本和狀態；預設是現在。回傳 `{theme_id, at, final, draft, theses}`：
  - `final` 是最新的定稿，`draft` 是比它新的最新草稿（沒有就是 `null`）；草稿不會蓋掉定稿。每個版本是 `{id, version, status, by, created_at, content_hash, context_manifest, body}`。
  - 題材頁的 `body`：`one_liner`、`analogy`、`origin {kind: market_first | news_first, item_id, rotation_event}`、`second_order`（最多 20 點）、`stage {name, basis}`、`chain`（因果鏈，最多 100 環）。
  - 因果鏈每一環：`from` / `to`（`{entity_id}` 或 `{label}`）、`relation`、`source`（`{item_id}` 或 `{url}`，沒有就是 `null`）、`inferred`（沒有出處 = AI 推論）、`confirmed`（只有我能確認）。`to` 是公司時多了 `revenue_share`（`{value 或 range, source}`；沒有出處一律 `"unknown"`）和 `role`（`leader` / `laggard` / `unknown`）。沒確認的 AI 推論環節不能進定稿。
  - `theses` 每個論點：`{id, created_at, final, draft, status, status_record, missing_first_hand, evidence, proposals}`。論點的 `body`：`claim`、`direction_implication {direction: bull | bear, targets: [追蹤對象 id]}`、`timing`（`now` / `roadmap`）、`edge`（賺什麼錢）、`horizon`、`refute_if`、`exit_if`（可選）。定稿要填齊（`exit_if` 除外），草稿只要 `claim`。
  - `status` 只看我確認過的變化（預設 `open`）。`evidence` 只列看得到的證據：我加的、揭露過的、我判斷過的，或被我確認的狀態變化引用過的；A、B 級排前面，再依時間由新到舊，最多 50 則。`missing_first_hand` = 看得到的證據都是 C、D 級。
  - `proposals` 是 AI 待確認的狀態提議（最多 50 筆），每筆是帳本紀錄加上 `exposes`：提議引用的證據裡還看不到的資料 id。提議本身就是 AI 對這些資料的看法，畫面顯示提議之前要先替 `exposes` 裡的資料寫揭露紀錄（地點 `theme`），之後對它們的判斷才不會被當成盲判。
- `POST /api/themes/{題材 id}/versions`：body `{status: draft | final, body}`，新增一版題材頁。
- `POST /api/themes/{題材 id}/theses`：body `{status, body}`，新增一個論點（一個題材最多 50 個）。
- `POST /api/theses/{論點 id}/versions`：body `{status, body}`，新增一版論點。每個題材頁、論點最多 500 版。
- `POST /api/theses/{論點 id}/evidence`：body `{item_id 或 story_id, relation: strengthens | weakens | related_no_change, grade: A–D, reason, source?}`。證據只能新增，一個論點最多 2000 則。
- `POST /api/theses/{論點 id}/status`：body `{to, evidence: [證據 id], reason?, confirms?}`。加強、削弱、推翻要引用這個論點、方向相符的證據（加強要有 strengthens，削弱和推翻要有 weakens），最多 50 則；退休、重新打開要寫理由。`confirms` 是 AI 提議的帳本紀錄 id，確認時狀態要跟提議一樣，證據和理由沒給就沿用提議的。每次變化都寫一筆帳本的 `thesis_status` 紀錄。
- `POST /api/theses/{論點 id}/proposals/{提議 id}/reject`：body `{reason?}`，駁回 AI 的提議（也記進帳本，狀態不變）。
- `GET /api/theses/{論點 id}/history`：這個論點的 `thesis_status` 帳本紀錄（提議、確認、駁回），由舊到新，最多 200 筆。

以上這些寫入的 POST 都回傳更新後的題材頁。版本、論點、證據的數量上限是永久的（只能新增，退休的論點也算進 50 個）。

### 因果鏈清單（ticket 59，`easyread/chain.py`）

因果鏈存在題材頁版本的 `body.chain`（見 4.62）。清單頁用下面兩個介面改一環，不用整份題材頁送回去：

- `GET /api/themes/{題材 id}/chain`：目前的因果鏈（草稿比定稿新就是草稿，否則是定稿）。回傳 `{theme_id, status, version, final_version, links, unconfirmed, market_data}`。`status` 是 `draft` / `final`，題材頁還沒有任何版本時是 `null`、`version` 是 0。`links` 每一環除了 4.62 的欄位，另有 `index`、`from` / `to` 的 `name` 和 `type`（節點是追蹤對象時）、`inferred`（沒有出處）、`confirmed`（我確認過沒有出處的環節），連到公司的環節多一個 `role_suggestion`（`leader` / `laggard` / `unknown`）。`unconfirmed` 是還沒確認的 AI 推論環節數（確認前不能進定稿）。`market_data` 是行情有沒有接上。
- `POST /api/themes/{題材 id}/chain`：body `{op, base_version, index?, link?, role?}`，回傳更新後的 `GET` 內容。`base_version` 一定要帶，且要等於目前的 `version`，不然回 400（`field: base_version`），免得蓋掉別處的修改；寫入時在同一個交易裡再比對一次，兩個分頁同時送出時後到的會被擋。
  - `op: add`：`link` 是新的一環（`from`、`to`、`relation`、`source?`，`to` 是公司時可帶 `revenue_share`、`role`；欄位檢查跟 4.62 的環節一樣）。一條鏈最多 100 環。
  - `op: update`：換掉第 `index` 環。改過的環節要重新確認：`confirmed` 不會帶過去。
  - `op: confirm`：我確認第 `index` 環（只有沒有出處、還沒確認的環節可以）。`link` 裡的 `confirmed` 一律忽略，確認只能走這個動作。
  - `op: remove`：移除第 `index` 環。
  - `op: role`：只換第 `index` 環的 `role`（`leader` / `laggard` / `unknown`，例如採用建議）；其他內容不變，確認過的不用重新確認。只有連到公司的環節可以。
  - `op: publish`：把目前的草稿寫成定稿版本。沿用 4.62 的定稿規則：沒確認的 AI 推論環節會被擋（`field: chain.<index>`）；一句話故事可以先不填。
  - `add` / `update` / `confirm` / `remove` / `role` 都是從目前的版本複製一份、改掉一環，寫成新的**草稿**（`by = me`）；定稿不會被動到。
- 領漲 / 補漲：`role` 是我確認的值，預設 `unknown`。`role_suggestion` 只是建議，不會自動寫進 `role`。行情（ticket 30）還沒做時，`market_data` 是 `false`、建議一律是 `unknown`。行情做好後，在 app 上提供 `market_returns(entity_id, since_iso) -> 報酬或 None`：`since` 是這個題材第一個版本的時間，有報酬的公司至少 2 家時，報酬不低於中位數的建議 `leader`，低於的建議 `laggard`；取不到資料的是 `unknown`。每次最多查 100 家、總共最多 3 秒（超過的當成 `unknown`；行情來源要自己限制單次呼叫的時間），行情來源出錯只記錯誤類型。
- 頁面：`GET /theme/{題材 id}` 是題材頁（目前只有因果鏈區塊）。

## 4.65 貼新聞連結匯入 (`POST /api/ingest`)

每一頁右上角的「＋ 貼網址」、不在輸入框時按 Ctrl+V 貼網址，都呼叫這一個介面（`easyread/ingest.py`）。

- 抓網址：`{url}`。網址先正規化（小寫主機、去掉 `#`、utm / fbclid / gclid 等追蹤參數、AMP 版的 `amp.` 主機、結尾 `/amp` 或 `.amp`、`?amp=1`），用正規化後的網址算 ID；同一篇已經匯入過就不再抓，回 `status: "exists"`。只抓公開網路上的 http / https 網址，指向本機或內網的回 400、`kind: "invalid_url"`。抓取走共用的抓取規則（逾時、大小、重試、每小時上限，見 `easyread/fetch.py`）。
- 手動貼全文：`{text, title?, publisher?, published_at?, url?}`。`published_at` 要是帶時區的 ISO 8601，沒填就是時間不明。給了 `url` 而且那篇已經在，就存成新版本（原本只有預覽時用這個補全文）；沒填的媒體、發布時間沿用原本抓到的。發布時間記了就不改：那篇已經有時間、又填了不同的時間，回 400 `bad_input`；原本時間不明的，填了就補進資料和 Story。
- 成功回 200：`{status, id, title, publisher, published_at, time_source, published_raw, fetched_at, url, paragraphs, chars, preview_only, same_language, hant_converted, added, translate}`。`status` 是 `created` / `updated` / `unchanged` / `exists`；`time_source` 是 `metadata`（頁面標的時間）、`user`（手動填的）或 `unknown`（時間不明，`published_at` 是空字串，`published_raw` 是頁面上沒有時區的原文）。
- 失敗回 `{error, kind}`，`error` 是固定的一句話，不帶上游原文或使用者輸入：輸入不對 400（`bad_input`、`invalid_url`）、這篇正在翻譯 409（`busy`）、抽不到正文 422（`no_text`）、body 超過 2 MB 413（`too_large`）、其他沒預期的錯誤 500（`internal`，例外原文不回、log 只記類型）、抓取失敗 502（`timeout`、`blocked`、`paywall`、`not_found`、`unsupported`、`too_large`、`over_limit`、`network`、`upstream`、`redirect`）。
- 每則資料自成一個 Story；時間不明的 Story 不記發布時間（不拿抓取時間代替），不納入事件驗證。原文是中文的不送翻譯（譯文語言是台灣繁體、原文是簡體時，用 OpenCC 的 s2twp 轉成繁體放譯文欄，轉出來的「臺」換回「台」（原文本來寫「臺」的不動），不叫 AI，原文保留，`hant_converted` 是 true；原文已經是繁體就照放，閱讀頁打開時也不再轉）；其他照「導入後自動翻譯」設定排進翻譯。頁面段落太多或太長時截到一則資料收得下的量（2000 段、40 萬字），`meta.truncated` 記為 true。
- `created`、`updated` 的資料同時排進 AI 分類（4.66）。

## 4.66 AI 分類 (`/api/triage/*`)

新匯入或換了內容的文章自動排進「待分類」（存在資料庫）；背景的排程每分鐘最多分類 5 則（`easyread/triage.py`，ticket 14）。送給 AI 的只有這篇全文、所有追蹤對象（含已封存的）和論點的最新定稿（草稿不送），不送任何市場熱度的內容。結果在同一個交易裡寫進：AI 連結（`mentions`，`source = ai`，手動移除過的不連回去）、證據（`evidence`，`by` = AI）、帳本的快速判斷（每個相關論點一筆，沒有論點時每個追蹤對象一筆）和分類結果；中間出錯就整筆不寫。

- `GET /api/triage/{資料 id}`：`{item_id, state: pending | done | failed, attempts, next_at, error, error_message, result}`。`error` 只是代碼（例如 `UPSTREAM_ERROR`、`BAD_OUTPUT`、`WRITE_FAILED`），不帶上游原文。`result` 是最新的分類結果或 `null`：
  - `{id, who, created_at, context_manifest, stale, importance, entities, theses, points, dropped, retrospective, time_unknown, linked, evidence, judgments}`。`importance` 是對各論點 / 追蹤對象最高的一級；`stale` = 結果之後內容又換了。
  - `entities` 每個 `{id, name, relation: bull | bear | neutral | noise, importance: high | mid | low | noise, noise_kind, confidence, reason}`；`theses` 每個 `{id, version, theme_id, relation: strengthens | weakens | related_no_change, grade, importance, noise_kind, confidence, reason}`。重要度和雜訊類別都是相對於那一個；`noise_kind` 只在重要度是 `noise` 時有值（`priced_in`、`rehash`、`no_new_info`、`unreliable`、`unrelated`、`short_term`）。
  - `points` 每個 `{text, cites: [{n, id, quote}], inferred}`：引述對不上原文的重點不列（算進 `dropped.points`）；`inferred: true` 是沒附出處的，畫面要標「AI 推論」。
  - 結果就是 AI 對這則資料的看法：畫面顯示之前要先寫揭露紀錄，之後的判斷才不會被當成盲判。
- `POST /api/triage/{資料 id}/retry`：重試失敗（或還在等）的分類，次數歸零、馬上排；已經完成的回 400。要帶 `X-Token`，body 最多 1 KB（內容不用）。
- 分類的 prompt 裡是外部內容，所以引擎不能有任何工具：只用 Claude Code（以 `--tools ""` 呼叫，不帶設定裡的額外參數；版本太舊不認這個參數就失敗，不退回有工具的呼叫）、API key（Anthropic、OpenAI 相容服務）或 Ollama。Codex CLI 和 Antigravity CLI 關不掉工具，分類一律跳過它們；只剩它們時算沒有 AI（`/api/ai` 的 `triage` 是 `no_ai`、`reason: no_tools`）。
- 沒有 AI、key 失效又沒有備用、服務在關：留在待分類，不算次數，這一輪停下。其他錯誤最多自動試 3 次，間隔 5、10 分鐘，之後標成 `failed`；一則失敗不影響同一輪的下一則，只有限流（`RATE_LIMITED`）算一次失敗之後這一輪就停下。沒預期的內部錯誤記成 `INTERNAL`，同樣算一次。找不到資料、不是文章的直接標 `failed`（`NOT_ARTICLE`）。
- 發布時間晚於現在不到 24 小時：延後到發布時間再分類，不算次數；晚超過 24 小時記 `BAD_TIME`。沒有發布時間也沒有匯入時間記 `NO_TIME`。
- 分類是背景工作，受額度保護（4.7 的「額度保護」，ticket 68）。**背景工作預設不用訂閱 CLI**，所以只裝了 Claude Code、沒有 API key 或本機模型時，分類預設會停在待分類，要加 key、開 Ollama，或在設定頁打開「背景工作也可以用訂閱」：背景不用訂閱又沒有 API key 或本機模型（`BACKGROUND_NO_API`）、Claude Code 5 小時額度超過門檻（`QUOTA_PAUSED`）、API 這個月到上限（`API_CAP`）時，跟沒有 AI 一樣留在待分類（資料庫裡）、不算次數，這一輪停下；暫停期間新匯入的照樣排進來。暫停解除後依排進來的順序補做，補做期間每一輪最多 50 則（不受一般每輪 5 則的限制，每一則送出前都再檢查一次門檻），排隊的都輪過一次、而且保護已經解除才記 `CATCHUP_DONE`。一輪最多跑 15 分鐘，超過就停，剩下的留給下一輪。Claude Code 的額度檔讀不出來時當作沒有額度資料（只記錯誤類型），不讓 AI 呼叫失敗。

## 4.67 今日新聞 (`POST /api/today`)

今日新聞頁（`/today`，`easyread/today.py`，ticket 15）用這一個介面。它會寫揭露紀錄，所以只有 POST：要帶 `X-Token`（別的網站觸發不了），body 是 JSON，上限 1 KB（超過回 413，不是 JSON 物件回 400）。沒有 GET。

- body 欄位（都可省略）：`importance`（逗號分隔，`high`、`mid`、`none`、`low`、`noise`，預設 `high,mid,none`；`none` = 還沒有重要度：待分類、失敗，或沒有相關對象）、`entity`（追蹤對象 id，也可以是題材；只列連到它的資料，題材是透過論點所屬的題材連到）、`limit`（預設 50，最多 200，超過照 200 回）。不認得的值回 400 `{error, field}`。
- 「今天」是台北時間的日期，依發布時間算（時間不明就用匯入時間，跟分類一樣）。一次最多讀 1000 則最近兩天有動靜（分類狀態有更新）的資料，新的在前，超過時 `truncated` 是 `true`（畫面請使用者用篩選縮小）。讀不出來的資料（檔案壞掉或被鎖住）跳過那一則，log 只記 ID 和錯誤類型。標題和來源顯示使用者改過的（`meta_override`）。
- 回傳 `{date, tz, levels, limit, items, total, more, truncated, counts, entities}`：`total` 是符合篩選的總數，`more` 是還有沒回的；`counts` 是各重要度的數量（已套用 `entity`，不套用 `importance`）；`entities` 是追蹤對象 / 題材的篩選清單 `[{id, name, type, count}]`（已套用 `importance`，最多 200 個）。資料庫還沒建時回空列表，不會建檔。
- `items` 依重要度（高、中、未分類、低、雜訊）再依時間（新的在前）排，每則 `{id, title, publisher, published_at, time_known, at, url, preview_only, state, importance, stale, retrospective, reader_url, top, entities, theses}`。`importance` 是它對各論點最高的一級（有論點就只看論點，沒有論點才看各追蹤對象，見規格「雜訊是相對的」）；`top` 是決定這一級的那個判斷（所以標籤和理由一定對得上） `{kind, id, relation, importance, confidence, reason}`；`entities`、`theses` 是相對於每個追蹤對象 / 論點的判斷（欄位同 4.66，論點另有 `claim`、`theme_name`）。沒有分類結果的資料 `top` 是 `null`、兩個清單是空的；分類結果讀不出來或格式不對的判斷也當成沒有。
- **揭露紀錄**：讀取全部做完之後，用一個交易替回傳的每一則、而且有分類結果的資料寫揭露紀錄（地點 = `today`，同一則只記第一次），寫完才回傳；寫不進去整個請求失敗（500），不回任何 AI 的看法，也不會留下一部分紀錄。被篩掉或超過 `limit` 沒回的不寫。`counts` 和 `entities` 只有數量，沒有個別資料的看法，不算揭露。
- 資料庫被鎖住或讀寫出錯時回 500，訊息是固定的一句，不帶原始錯誤。

## 4.7 AI 引擎與自帶 key (`/api/ai/*`)

設定頁（`/settings`）的「AI 模型」區用這組 API（ticket 67）。其他模組呼叫 AI 一律走 `easyread/ai_engines.py` 的 `Engines.run(task, prompt, prompt_version=…, trigger=…)`，不直接呼叫引擎。寫入要帶 `X-Token`，body 上限 16 KB（超過回 413）。輸入不對回 400 `{error, field}`；找不到回 404；其他錯誤回 500，訊息是固定的一句。回應裡的 key 只有末四碼（`last4`，key 短於 12 字時是空字串），完整的 key 只存在資料目錄的 `ai.json`，不寫進 log。

- `GET /api/ai`：設定頁要的全部東西。
  - `detected`：本機 CLI（`claude`、`codex`、`antigravity`）有沒有找到、版本、最近一次呼叫的登入結果（`auth`：`ok` / `invalid` / `null` 還沒用過）和計費方式（`billing`：`subscription` / `api`）；`ollama` 有沒有在執行、有哪些模型。偵測沿用啟動時的背景偵測和 5 分鐘快取，`detected_at` 是上次偵測完的 Unix 秒。CLI 本身不回報登入狀態，所以「已登入」是看最近一次呼叫有沒有成功。
  - `claude_quota`：Claude Code 最近一次回報的額度（`five_hour` / `seven_day` 的 `used` 0–1 和 `resets_at`）。
  - `anthropic`：`{last4, status, tested_at, code}` 或 `null`；`status` 是 `ok`、`invalid`、`unverified`（連不上或服務不支援列模型清單，key 照樣存著）、`untested`。`anthropic_sdk` 表示這台電腦有沒有裝 `anthropic` 套件。
  - `openai`：OpenAI 相容服務的清單，每個 `{id, name, base_url, api, model, last4, has_key, status, tested_at, code}`。
  - `tasks`：五種工作（`triage` 分類、`translate` 翻譯、`draft` 題材頁 / 概念卡起草、`thesis_change` 論點變化偵測、`ask` 問 AI），每個 `{primary, fallback, resolved, using, state, reason, today, month_cost}`。`primary` / `fallback` 是選項 id（`null` = 自動 / 不用備用）；`resolved` 是實際的主要引擎（自動時是自動挑到的），`using` 是現在會用的。`state`：`ready`、`fallback`（主要的不能用，改用備用）、`paused`（key 失效或登入過期，也沒有可以用的備用）、`no_ai`（沒有任何可以用的引擎）。`reason` 是主要的不能用的原因（`missing` / `auth_invalid` / `no_tools`：這個工作不能用關不掉工具的 CLI，目前只有 `triage`，見 4.66）。`today` 是今天（台北時間）的呼叫次數，`month_cost` 是這個月的 API 花費（美元，沒有就是 `null`）。
  - `choices`：下拉選單的選項，每個 `{id, engine, model, entry, model_label, name, kind, usable}`。選項 id 是 `引擎|服務 id|模型`，例如 `claude||claude-haiku-5-5`、`codex||`、`openai|o1a2b3c4d5e6|gpt-x`。
  - `any_ai`：有沒有任何工作找得到引擎。
  - `guard`：額度保護的狀態，同 `GET /api/ai/guard`。
- `POST /api/ai/detect`：重新偵測。之前標成登入過期的 CLI 會先清掉標記，下次呼叫再看結果。
- `POST /api/ai/tasks`：`{task, primary, fallback}`，設定一種工作的主要和備用引擎；空字串 = 自動 / 不用備用，備用跟主要一樣等於不用備用。
- `POST /api/ai/keys/anthropic`：`{key}`，儲存並測試（列模型清單，不花 token）。回傳同 `GET /api/ai`，另有 `test: {ok, status, code, message}`。`POST /api/ai/keys/anthropic/remove` 移除。
- `POST /api/ai/keys/openai`：`{name?, base_url, api?, model, key?}` 新增一個 OpenAI 相容服務並測試（`GET {base_url}/models`）；`POST /api/ai/keys/openai/{id}` 編輯（沒帶 `key` = 不換；換了 `base_url` 又沒帶新 key 時，舊 key 會清掉，不送到新地址）；`POST /api/ai/keys/openai/{id}/remove` 移除，選了它的工作改回自動。最多 10 個。
- 限制：key 8–300 個 ASCII 可見字元、不能有空白；`base_url` 最多 300 字，只能是 `http` / `https`，不能帶帳密、query 或 fragment，不是這台電腦（`localhost`、`127.0.0.1`、`::1`）的服務一定要 `https`；`name` 最多 40 字，`model` 最多 100 字。呼叫 OpenAI 相容服務時不跟 redirect（3xx 當成錯誤），免得 key 被轉送到別的主機或 http。

呼叫 AI 時（`Engines.run`）：

- 依工作的設定選引擎；「自動」依序找 Claude Code、Codex CLI、Antigravity CLI、Anthropic key、OpenAI 相容服務、Ollama，Claude 的模型預設分類用 Haiku、起草用 Opus、其他用 Sonnet。
- prompt 有外部內容、引擎不能有工具的工作（`triage`，或呼叫端帶 `tools=False`）：Claude Code 以 `--tools ""` 呼叫，Codex CLI 和 Antigravity CLI 跳過；所以分類只能用 Claude Code、API key 或 Ollama。
- key 失效或登入過期（`AUTH_INVALID`）時不重試同一把：標成失效，有備用就改用，回傳的 `notice` 是 `AUTH_INVALID`；沒有就丟 `PAUSED`。換新 key（或重新偵測）之後才會再用。
- 限流（`RATE_LIMITED`）時指數退避：等 2、4、8 秒（上游給的 `Retry-After` 比較長就用它，每次最多 30 秒），同一個引擎最多試 4 次，之後丟 `RATE_LIMITED`，不改用備用（額度保護見下面）。
- 每次成功都記一筆用量到 `ai_usage`：引擎、模型、token。API 依官方價格算費用，不認得的模型或價格不確定時記成不明；本機 CLI 用訂閱時不折算金額，Claude Code 有回報時記額度和重置時間；Ollama 記 0。
- 實際用的引擎和模型記進 prompt 版本：呼叫端給 `prompt_version="ask-v2"`，帳本記 `ask-v2@claude/claude-sonnet-5-5`；換引擎或模型就是另一個版本。
- 錯誤只帶錯誤代碼和固定訊息：`NO_AI`、`PAUSED`、`AUTH_INVALID`、`RATE_LIMITED`、`UPSTREAM_ERROR`、`NETWORK`、`TIMEOUT`、`BAD_REQUEST`、`ENGINE_MISSING`、`OUTPUT_TRUNCATED`、`ENGINE_ERROR`、`CANCELLED`。上游的原文過 scrubber 才留在例外上，不寫進 log、不回給畫面。
- 額度保護多了三個代碼：`QUOTA_PAUSED`、`API_CAP`、`BACKGROUND_NO_API`（見下面）。限流（`RATE_LIMITED`）重試用完時另外記一筆事件，給用量頁看（4.71）。

額度保護（ticket 68，`easyread/quota_guard.py`；條款查證見 `.scratch/newsread-v1/issues/68-subscription-quota-guard.md`）：

- 呼叫端一定要標 `trigger`：`background`（排程自己跑的分類、翻譯、起草、論點變化偵測）或 `manual`（使用者按了才跑的）。沒標是程式錯誤。
- **背景工作預設不用訂閱 CLI**（Claude Code、Codex CLI、Antigravity CLI）：Anthropic 和 OpenAI 都沒有明文允許其他程式在背景用個人訂閱，所以改用 API key 或 Ollama（設定的引擎是訂閱時，自動接著試 API key 和本機模型）；都沒有時丟 `BACKGROUND_NO_API`。設定 `background_subscription` 打開才用訂閱。本機 CLI 最近一次是 API 計費（`billing: api`）的不算訂閱。
- 允許背景用訂閱時，Claude Code 回報的 5 小時額度到門檻（預設 70%，含）：`on_exceed = wait` 時，原本會用 Claude Code 訂閱的背景工作丟 `QUOTA_PAUSED`，不改用 API；`api` 時改用 API key，沒有 key 就丟 `QUOTA_PAUSED`。設定成 API、Codex 的工作不受這個門檻影響（看不到 Codex 的額度）。額度只在 Claude Code 有回應時更新：過了重置時間就當作已經重置；重置時間不明或太遠時，最多暫停到記下額度的時間 + 5 小時；沒有記下時間的數字不算。
- API 每月上限（預設 15 美元，台北時間的月份；只算有費用的呼叫，訂閱和費用不明的不算）：到 80% 和到上限各記一筆事件、各通知一次（每個月一次；通知介面 `quota_guard.set_notifier`，預設什麼都不送，等 ticket 16 接 Telegram）。到上限後經過 `Engines.run` 的背景翻譯和起草丟 `API_CAP`（用訂閱也停；匯入後的自動翻譯另見下面「匯入後的自動翻譯」），分類和論點變化偵測不用 API、改等訂閱額度（背景不能用訂閱時丟 `API_CAP`）。上限設 0 = 背景不用 API（不算「到上限」：不通知、翻譯和起草照樣可以用本機模型、右上角不顯示暫停）。事件 `API_CAP_STOPPED`、`BACKGROUND_NO_API` 每個工作每個月記一段。
- 手動的照跑；回傳的 `quota_notice` 是 `QUOTA_OVER`（這次用的是 Claude Code 訂閱、額度超過門檻）、`API_CAP`（這次用的是 API、這個月到上限）或 `null`。每個手動 AI 入口都在送出前看 `GET /api/ai/guard` 提醒一次：閱讀器的問 AI（論文和文章共用，筆記卡片的點評也走這裡）、筆記幫手（點評、幫我改、起草稿）、智慧標註、心智圖、讓模型重譯這段。使用者按了才開始的翻譯（整篇、整頁、挑頁、重試、整理原文、文獻庫的批次翻譯）也算手動：照跑，送出前提醒。設定頁的「測試引擎」不提醒。提醒照這次用的引擎（`GET /api/ai/guard` 的 `engines`）：Claude Code 訂閱只提醒 5 小時額度，API key 只提醒月上限，本機模型和看不到額度的訂閱（Codex、Antigravity）不提醒；重譯這段看 `engines.translate`；整篇翻譯跟 `translate_api.enqueue` 一樣，任務在 confirm、waiting 或重試失敗頁時看任務記的模型（匯入時選的問 AI 模型），否則看翻譯引擎；批次翻譯每篇種類都一樣才用它；問 AI 看選的模型（名單裡找不到的兩項都看），其他（筆記幫手、智慧標註、心智圖）看問 AI 名單的預設；不知道種類時兩項都看，同時碰到的合成一則（#97）。之後加的手動入口照同一個規則接。
- 每次觸發保護都記一筆事件（同一段暫停、同一個月只記一次），只有代碼和固定欄位的數字。
- 匯入後的自動翻譯（貼網址、貼文字、匯入 PDF 時勾了翻譯；翻譯還用閱讀器自己的 `/api/config` 引擎）算背景工作，送出前問 `Engines.translation_gate`：用 Claude Code、Codex 訂閱翻譯時預設不自動翻（設定 `background_subscription` 打開才照額度門檻跑）；Claude Code 額度超過門檻時等重置（`on_exceed = api` 時改用 AI 模型頁設定的本機模型或價格認得的 API key，`Engines.translation_gate` 回 `{use: 改用的引擎設定}`，記 `QUOTA_SWITCHED_API`；API 這個月到上限、上限 0、價格不認得的都不改用，照樣等）；用 API key（含 API 計費的本機 CLI）時，API 這個月到上限就等，上限設 0 就不自動翻；Antigravity 和本機模型不受限。不能送時任務的 `state` 是 `waiting`，`wait` 是 `{reason, until}`（`reason`：`subscription` / `quota` / `api_off` / `api_cap` / `check`（額度保護剛啟動還沒接上，或讀不到） / `auto_off`（等的時候關掉了「匯入後自動翻譯」：補翻那一輪不排回去，要使用者按；開回來之後照常問）；`until` 是預計重置的 Unix 秒或 `null`），原頁照樣渲染。排程每 5 分鐘補翻一次（`translate_catchup`），額度解除或設定改了就把等著的排回去，每輪最多 5 篇，先等的先補；服務剛啟動、額度保護還沒接上時輪到的背景任務也先等（`check`），由補翻那一輪接著問；重啟前在等的照樣等，補翻那一輪會再問。使用者按翻譯（手動，沿用匯入時選的範圍、模型和語言）或取消（`POST /api/p/<id>/cancel`，變成「已匯入，未翻譯」）都可以結束等待。`quota` 記 `QUOTA_PAUSED`、`api_cap` 記 `API_CAP_STOPPED`（`task` 是 `translate`）。
- `GET /api/ai/guard`：`{settings, quota, api, background, engines}`。`engines` 是每個手動 AI 入口用的引擎算哪一種：`{translate, chat: {模型 id: 種類}, chat_default}`，種類是 `claude` / `subscription`（Codex、Antigravity）/ `api`（含 API 計費的本機 CLI）/ `local` / `none`；設定讀不到時是 `{}`。`settings` 是 `{background_subscription, threshold, on_exceed, api_monthly_usd}`；`quota` 是 `{used, resets_at, at, over, until}`（Unix 秒）；`api` 是 `{spent_usd, cap_usd, month, warn, reached}`；`background` 是 `{paused, reason, until}`，`reason` 是 `quota`（等重置）、`api_cap`（API 到上限）、`no_api`（背景不用訂閱，又沒有 API key 或本機模型）或 `null`。用分類判斷（一直在跑的背景工作）；根本沒有 AI 時不算保護。每一頁右上角的 Claude 5 小時額度和「背景工作暫停」每分鐘讀一次（`js/common/quota-guard.js`），點了到用量頁（4.71）。
- `POST /api/ai/guard`：只改有帶的欄位，回傳同 `GET /api/ai`。`threshold` 要是 1–100 的整數，`on_exceed` 是 `wait` / `api`，`api_monthly_usd` 是 0–100000 的數字，`background_subscription` 是布林值；格式不對回 400 `{error, field}`。
- `GET /api/ai/guard/events`：`{events}`，新的在前，最多 200 筆。每筆 `{seq, at, code, task, message, data}`，`message` 是代碼對應的固定說明，`data` 只有 `used`、`threshold`、`until`、`spent_usd`、`cap_usd`、`month`、`count`。用量頁（ticket 29，4.71）讀這裡。資料庫還沒建時回空清單。

NewsRead 留下來的閱讀器功能（翻譯論文、頁邊問 AI）還是用舊的 `/api/config` 引擎設定（匯入後的自動翻譯照上面的規則受額度保護），之後改走這裡。翻譯的每次呼叫已經會記一筆 `ai_usage`（`task` 是 `translate`，引擎和模型照舊設定；帳本記不進去只寫 log，不讓翻譯失敗）；走 API（不是本機地址）時照 `PRICES` 算出金額（快取一律照全價算，寧可多算），算進 API 每月上限，模型不認得的照舊記費用不明；文章的問 AI 也記（`task` 是 `ask`，見 4.55），論文的問 AI 還沒記。

## 4.71 用量頁 (`GET /api/usage`)

用量頁（`/usage`，ticket 29）讀這支，加上 4.7 的 `GET /api/ai/guard`（保護線、API 月上限、背景暫停的原因）和 `GET /api/ai/guard/events`（事件）。三個都是唯讀：帳本檔還沒建就回空的，不建檔、不寫任何東西。日期和月份都用台北時間；錯誤只有固定的一句話，不帶例外或資料庫的原文。

- `GET /api/usage?period=month|day`（預設 `month`）：統計區間是本月或今天，只影響 `tasks`、`cli`、`sources`；`api` 一律是本月，`daily` 一律是最近 14 天。`period` 不是這兩個值回 400 `{error, field: "period"}`。
- 回傳 `{period, label, now, empty, claude, cli, api, tasks, tasks_truncated, sources, sources_truncated, daily, daily_days}`：
  - `empty`：`ai_usage` 一筆都沒有（還沒用過 AI）。這時清單都是空的，`claude` 只有額度。
  - `claude`：`{limits, at, window}`。`limits` 是 Claude Code 最近一次回報的 `five_hour` / `seven_day`（`{used, resets_at}`，`used` 是 0–1，`resets_at` 是 Unix 秒），沒有就是空物件；`at` 是記下這組數字的時間（Unix 秒）。這是整個帳號的用量，包含使用者自己用 Claude Code 寫程式；數字只在呼叫時更新，所以畫面在 `resets_at` 或 `at` 加上視窗長度（5 小時 / 7 天）兩者較早的那個時間過了之後，標成已重置。額度檔裡不是有限數字的值（NaN、inf）一律當作沒有。`window` 是最近 5 小時 NewsRead 自己用 Claude Code 的 `{calls, tokens}`（看不到佔額度幾 %，只能看 token）。
  - `cli`：Codex 和 Antigravity 在這段期間的 `{calls, tokens}`。它們只回報 token，看不到額度。
  - `api`：`{month, spent_usd, by_engine}`。`spent_usd` 跟額度保護算的是同一個數字（本月有費用的呼叫，訂閱不算）；`by_engine` 是各引擎的花費，大到小。月上限在 `GET /api/ai/guard` 的 `api.cap_usd`。
  - `tasks`：依工作、引擎、模型分組，每列 `{task, engine, model, calls, tokens, cost_usd}`，token 多的在前，最多 50 列（`tasks_truncated` 表示還有）。`cost_usd` 是 `null` 表示沒有費用（訂閱不折算成金額）。`engine` 只會是 `claude`、`codex`、`antigravity`、`anthropic`、`openai`、`ollama`、`other`：OpenAI 相容服務的 id 不外露（幾個服務合成一列 `openai`），不認得的引擎叫 `other`；`api.by_engine` 也一樣。
  - `sources`：依 `ai_usage.source` 分組，每列 `{source, calls, tokens, items, linked}`，最多 50 列。`source` 是呼叫 AI 的功能入口（分類是 `triage`，翻譯和閱讀器問 AI 是 `newsread`），**不是個別媒體**：`ai_usage` 還沒有記每次呼叫用的是哪一則資料，要依媒體分得等資料來源（ticket 19 等）接上。`items`、`linked` 只有 `triage` 算得出來：這段期間分類過的資料有幾則、其中幾則有證據（`evidence`）掛在論點上（掛到論點的比例 = `linked / items`）；其他來源是 `null`。
  - `daily`：最近 14 天（含今天，舊的在前）每天的 `{date, tokens}`，沒有呼叫的日子補 0；token = 輸入 + 輸出（命中快取的算在輸入裡，不重複算），訂閱和 API 合計。
- 事件：4.7 的 `GET /api/ai/guard/events`。除了額度保護和 API 上限的代碼，還有 `RATE_LIMITED`：AI 引擎重試用完（4.7 的指數退避）還是限流，同一個工作、同一個 10 分鐘時段（依記事件的時間）只記一筆；它不打斷其他事件的「跟上一筆一樣就不記」。畫面只畫最近 20 筆；事件讀不到時寫「事件暫時讀不到」，不說成沒有事件。
- 每頁右上角的 Claude 5 小時額度（`js/common/quota-guard.js`，沿用 `GET /api/ai/guard` 的輪詢，沒有另開）：顯示「Claude 5h 42%」，背景工作暫停時顯示「背景工作暫停 · …」，點了都到 `/usage`。額度還沒有數字、沒有記下時間（`quota.at`）、或已經過了重置時間（`resets_at` 和 `at` + 5 小時取早的，跟後端判斷超過門檻的規則一樣）就不顯示。

## 5. 已移除的介面

研究工作區（`/api/research/v1/*`、`/api/research/v2/*`、`/research` 頁面）、Zotero 遷移（`/api/zotero/*`、`/api/migrate/*`）和成批導入在 ticket 04 移除，現在都回 404。心智圖和 Obsidian 匯出改用 4.5 節的 `/api/reader/*`。

---

## 6. 桌面專屬通訊協定（Custom URL Scheme）

桌面版註冊了 `paperread://` 協定（舊版 `easyread://` 保持向下相容）：

```text
paperread://open?id=<論文 id>&block=<段落 id>
paperread://open?sha256=<完整 SHA-256>&block=<段落 id>
easyread://open?id=<論文 id>&block=<段落 id>
```

點選後自動喚起 NewsRead 桌面應用程式視窗並精準定位至該論文的對應段落。在未安裝桌面版時，透過瀏覽器直接造訪 `http://127.0.0.1:8765/open?...` 具備相同效果。
