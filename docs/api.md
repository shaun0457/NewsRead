# 本機介面約定（給外部工具）

Zotero 外掛、指令碼等外部工具接入 PaperRead 時，只依賴本頁列出的介面。這些介面保持相容；不相容的改動會把 API 版本加 1，並提前寫進 CHANGELOG。本頁沒列的 `/api/*` 都是介面內部用的，隨時可能改。

當前 API 版本：**1**（PaperRead 1.4.5 延續相容介面）。

## 找到服務

PaperRead 執行時把地址寫在資料目錄的 `.server.json`（預設 `~/PaperRead/.server.json`，設定了 `EASYREAD_HOME` 時在那個目錄下）：

```json
{ "url": "http://127.0.0.1:52341", "pid": 12345, "started": "2026-10-03T12:00:00Z" }
```

埠每次啟動可能不同，不要寫死。服務只監聽 `127.0.0.1`。讀到地址後先請求 `/api/version` 確認服務還活著、版本是否支援。

## 論文怎麼標識

- **論文 id** = 原 PDF 完整 SHA-256 的前 12 位（小寫十六進位制）。同一個 PDF 重複匯入得到同一個 id，不會建第二篇。
- **段落 id** 是 `paper.json` 裡塊的 `id`（如 `p3-2`、`eq4`、`fig2`），定下後不變，見 [data-format.md](data-format.md)。

## 介面

| 方法 | 路徑 | 用途 |
| --- | --- | --- |
| GET | `/api/version` | `{"api": 1, "version": "1.3.1"}`；`api` 是本頁約定的版本，`version` 是應用版本 |
| GET | `/api/library` | 文獻庫列表 `items`（每篇的 `id`、標題、作者、DOI、進度、筆記數等）和寫操作要用的 `token` |
| POST | `/api/import?name=<檔名>&translate=0\|1` | 請求體是 PDF 原始位元組，請求頭帶 `X-Token`。返回 `{"id", "new", "queued"}`；已有同一 PDF 時 `new` 為 false |
| GET | `/api/p/{id}/part/paper` | `{"data": paper.json, "version": …}`：標題、段落原文和譯文 |
| GET | `/api/p/{id}/part/reader` | `{"data": reader.json, "version": …}`：劃線、批註、整篇心得 |
| GET | `/api/p/{id}/part/discussion` | `{"data": discussion.json, "version": …}`：儲存到頁邊的 AI 回答 |
| GET | `/read/{id}` | 閱讀頁，可加 `#段落id` 定位 |
| GET | `/open?sha256=<完整 SHA-256>&block=<段落 id>` | 按指紋開啟論文；也可用 `id=<論文 id>`。找到就跳到閱讀頁，找不到迴文獻庫 |

`/api/p/{id}/state` 是閱讀頁自己用的：會把論文標記成"開啟過"、觸發補圖，外部工具讀資料請用上面的 `part/*`。

寫操作（POST）都要帶 `X-Token` 請求頭，值從 `/api/library` 取；token 每次啟動都會變。

## 桌面版開啟連結

桌面版（1.4.5 起）註冊了 `paperread://` 協議；舊版 `easyread://` 仍保留用於相容既有外部連結：

```
paperread://open?sha256=<完整 SHA-256>&block=<段落 id>
paperread://open?id=<論文 id>
easyread://open?sha256=<完整 SHA-256>&block=<段落 id>
easyread://open?id=<論文 id>
```

點選後開啟（或喚起）PaperRead 視窗並定位到該段落，引數含義同 `/open`。引數只接受字母、數字、`-`、`_`，其餘內容會被忽略。沒裝桌面版時，用瀏覽器開啟 `<url>/open?...` 效果相同。

## 資料格式

`part/*` 返回的 JSON 結構見 [data-format.md](data-format.md)。其中欄位只會增加，不會改名或改含義；改了算不相容，按上面的規則升 API 版本。
