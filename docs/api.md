# 本機介面約定（給外部工具與擴充整合）

Zotero 外掛、Obsidian 外掛、命令列指令碼或自訂代理接入 PaperRead 時，只依賴本頁列出的介面規格。這些介面保持向下相容；不相容改動會將 API 版本加 1，並提前記錄於版本日誌。

當前 API 約定版本：**1**（PaperRead 1.5.2 延續相容介面）。

---

## 1. 發現服務位址

PaperRead 啟動時會將服務位址與 PID 寫入資料目錄下的 `.server.json`（預設為 `~/PaperRead/.server.json`；若設定環境變數 `EASYREAD_HOME` 則位於該目錄下）：

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

## 4.7 AI 引擎與自帶 key (`/api/ai/*`)

設定頁（`/settings`）的「AI 模型」區用這組 API（ticket 67）。其他模組呼叫 AI 一律走 `easyread/ai_engines.py` 的 `Engines.run(task, prompt, prompt_version=…)`，不直接呼叫引擎。寫入要帶 `X-Token`，body 上限 16 KB（超過回 413）。輸入不對回 400 `{error, field}`；找不到回 404；其他錯誤回 500，訊息是固定的一句。回應裡的 key 只有末四碼（`last4`，key 短於 12 字時是空字串），完整的 key 只存在資料目錄的 `ai.json`，不寫進 log。

- `GET /api/ai`：設定頁要的全部東西。
  - `detected`：本機 CLI（`claude`、`codex`、`antigravity`）有沒有找到、版本、最近一次呼叫的登入結果（`auth`：`ok` / `invalid` / `null` 還沒用過）和計費方式（`billing`：`subscription` / `api`）；`ollama` 有沒有在執行、有哪些模型。偵測沿用啟動時的背景偵測和 5 分鐘快取，`detected_at` 是上次偵測完的 Unix 秒。CLI 本身不回報登入狀態，所以「已登入」是看最近一次呼叫有沒有成功。
  - `claude_quota`：Claude Code 最近一次回報的額度（`five_hour` / `seven_day` 的 `used` 0–1 和 `resets_at`）。
  - `anthropic`：`{last4, status, tested_at, code}` 或 `null`；`status` 是 `ok`、`invalid`、`unverified`（連不上或服務不支援列模型清單，key 照樣存著）、`untested`。`anthropic_sdk` 表示這台電腦有沒有裝 `anthropic` 套件。
  - `openai`：OpenAI 相容服務的清單，每個 `{id, name, base_url, api, model, last4, has_key, status, tested_at, code}`。
  - `tasks`：五種工作（`triage` 分類、`translate` 翻譯、`draft` 題材頁 / 概念卡起草、`thesis_change` 論點變化偵測、`ask` 問 AI），每個 `{primary, fallback, resolved, using, state, reason, today, month_cost}`。`primary` / `fallback` 是選項 id（`null` = 自動 / 不用備用）；`resolved` 是實際的主要引擎（自動時是自動挑到的），`using` 是現在會用的。`state`：`ready`、`fallback`（主要的不能用，改用備用）、`paused`（key 失效或登入過期，也沒有可以用的備用）、`no_ai`（沒有任何可以用的引擎）。`reason` 是主要的不能用的原因（`missing` / `auth_invalid`）。`today` 是今天（台北時間）的呼叫次數，`month_cost` 是這個月的 API 花費（美元，沒有就是 `null`）。
  - `choices`：下拉選單的選項，每個 `{id, engine, model, entry, model_label, name, kind, usable}`。選項 id 是 `引擎|服務 id|模型`，例如 `claude||claude-haiku-5-5`、`codex||`、`openai|o1a2b3c4d5e6|gpt-x`。
  - `any_ai`：有沒有任何工作找得到引擎。
- `POST /api/ai/detect`：重新偵測。之前標成登入過期的 CLI 會先清掉標記，下次呼叫再看結果。
- `POST /api/ai/tasks`：`{task, primary, fallback}`，設定一種工作的主要和備用引擎；空字串 = 自動 / 不用備用，備用跟主要一樣等於不用備用。
- `POST /api/ai/keys/anthropic`：`{key}`，儲存並測試（列模型清單，不花 token）。回傳同 `GET /api/ai`，另有 `test: {ok, status, code, message}`。`POST /api/ai/keys/anthropic/remove` 移除。
- `POST /api/ai/keys/openai`：`{name?, base_url, api?, model, key?}` 新增一個 OpenAI 相容服務並測試（`GET {base_url}/models`）；`POST /api/ai/keys/openai/{id}` 編輯（沒帶 `key` = 不換；換了 `base_url` 又沒帶新 key 時，舊 key 會清掉，不送到新地址）；`POST /api/ai/keys/openai/{id}/remove` 移除，選了它的工作改回自動。最多 10 個。
- 限制：key 8–300 個 ASCII 可見字元、不能有空白；`base_url` 最多 300 字，只能是 `http` / `https`，不能帶帳密、query 或 fragment，不是這台電腦（`localhost`、`127.0.0.1`、`::1`）的服務一定要 `https`；`name` 最多 40 字，`model` 最多 100 字。呼叫 OpenAI 相容服務時不跟 redirect（3xx 當成錯誤），免得 key 被轉送到別的主機或 http。

呼叫 AI 時（`Engines.run`）：

- 依工作的設定選引擎；「自動」依序找 Claude Code、Codex CLI、Antigravity CLI、Anthropic key、OpenAI 相容服務、Ollama，Claude 的模型預設分類用 Haiku、起草用 Opus、其他用 Sonnet。
- key 失效或登入過期（`AUTH_INVALID`）時不重試同一把：標成失效，有備用就改用，回傳的 `notice` 是 `AUTH_INVALID`；沒有就丟 `PAUSED`。換新 key（或重新偵測）之後才會再用。
- 限流（`RATE_LIMITED`）時指數退避：等 2、4、8 秒（上游給的 `Retry-After` 比較長就用它，每次最多 30 秒），同一個引擎最多試 4 次，之後丟 `RATE_LIMITED`，不改用備用（額度保護是 ticket 68）。
- 每次成功都記一筆用量到 `ai_usage`：引擎、模型、token。API 依官方價格算費用，不認得的模型或價格不確定時記成不明；本機 CLI 用訂閱時不折算金額，Claude Code 有回報時記額度和重置時間；Ollama 記 0。
- 實際用的引擎和模型記進 prompt 版本：呼叫端給 `prompt_version="ask-v2"`，帳本記 `ask-v2@claude/claude-sonnet-5-5`；換引擎或模型就是另一個版本。
- 錯誤只帶錯誤代碼和固定訊息：`NO_AI`、`PAUSED`、`AUTH_INVALID`、`RATE_LIMITED`、`UPSTREAM_ERROR`、`NETWORK`、`TIMEOUT`、`BAD_REQUEST`、`ENGINE_MISSING`、`OUTPUT_TRUNCATED`、`ENGINE_ERROR`、`CANCELLED`。上游的原文過 scrubber 才留在例外上，不寫進 log、不回給畫面。

PaperRead 留下來的閱讀器功能（翻譯論文、頁邊問 AI）還是用舊的 `/api/config` 引擎設定，之後改走這裡。

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

點選後自動喚起 PaperRead 桌面應用程式視窗並精準定位至該論文的對應段落。在未安裝桌面版時，透過瀏覽器直接造訪 `http://127.0.0.1:8765/open?...` 具備相同效果。
