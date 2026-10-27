# PaperRead v1.5.0 升級交接文件 (Upstream 移植 + Antigravity CLI + 互動心智圖)

> **給接手 Agent 的快速導讀**：
> 本次改動完成了從上游 `Edwardxlai/easyread`（版本範圍 `v1.3.3` 至 `v1.4.3`）的 **11 項核心特性與穩定性修復** 移植，並新增了第 **12 項本機 Antigravity CLI (`agy`) 模型引擎深度接入**，將專案發布目標版本推進至 **v1.5.0**。
> 專案內所有現有自訂功能（**封存功能 `archived`**、**閱讀看板**、**研究工作區 `/research`**、**繁體中文 `zh-TW` 語系**）均已 100% 保留且通過所有測試。

---

## 1. 移植與實作項目清單（共 13 項）

| 編號 | 功能名稱 | 來源版本 | 核心說明與架構變動 |
| :--- | :--- | :--- | :--- |
| **1** | **分類樹狀分層 (Hierarchical Categories)** | v1.4.0 | 支援 `/` 分層路徑（如 `機器學習/Transformer`）、折疊箭頭與狀態記憶、展開直視分類內論文、父分類聚合統計、右鍵「移到…」與連帶子分類改名／刪除。嚴格保留 `!i.archived` 封存過濾與 `/research` 相容。 |
| **2** | **導入整個資料夾 (Folder Import)** | v1.4.0 | 支援遞迴選取目錄（上限 5000 篇），自動將子目錄層級轉換為樹狀分類。支援原樣去重、跳過隱藏檔與背景進度即時回傳。 |
| **3** | **Zotero 整庫遷移 (Zotero Migration)** | v1.4.0 | 自動偵測本機 `zotero.sqlite`（支援運行中鎖檔備份容錯讀取），批次遷移 PDF、多層分類、群組文獻庫、標籤與元資料。 |
| **4** | **連結本地 PDF 模式 (Link Local PDF)** | v1.4.3 (PR #74) | 批次匯入時提供「不複製 PDF 檔案，只記錄外部原路徑」選項；刪除文獻庫條目時不會誤刪外部原檔。 |
| **5** | **一次導入 >5 篇防護 (Batch Import Guard)** | v1.4.0 | 批次拖入或選取 >5 篇且上次設定為自動翻譯時，彈窗防護確認（預設「只匯入」），防止誤觸耗盡 API 額度。 |
| **6** | **一鍵停止全部翻譯／批次停止 (Stop Jobs)** | v1.4.0 | 頂欄顯示「停止翻譯（N）」按鈕一鍵終止佇列，批次操作列支援選取終止；中斷任務乾淨標記為「已取消」而非報錯。 |
| **7** | **單篇資料損壞隔離 (Corrupted Paper Isolation)** | v1.4.2 (#68) | 單篇論文 JSON 損壞時單獨隔離標示異常與實體檔案路徑，確保首頁與回收站不會整頁載入崩潰。 |
| **8** | **程式碼區塊容錯降級 (Code Block Fallback)** | v1.4.0 (PR #44) | 模型翻譯回傳 code / listing 區塊時，自動轉為含程式碼框的段落，且程式碼內的 `$` 與反斜線不誤判為 LaTeX 公式語法錯誤。 |
| **9** | **導出手機版 HTML (Mobile Export)** | v1.4.0 (#24) | 剔除已譯頁高解析度原頁圖片（檔案從 60MB 降至 ~2MB），精簡頂欄並內嵌展開筆記，CLI 提供 `--mobile` 選項。 |
| **10** | **後台應用內更新與跨平台支援 (Desktop Updates)** | v1.3.3 | 下載中可關閉彈窗轉入後台，頂欄顯示下載進度百分比，下載完成後手動「更新並重啟」；支援 Windows、macOS 與 Linux AppImage。 |
| **11** | **關鍵缺陷修復 (PR #37, PR #56)** | v1.3.3 / v1.4.1 | - PR #37：修復網頁連結導入時標題與作者名稱中單引號（撇號 `'`）截斷文字問題。<br>- PR #56：修復刪除正在翻譯中的論文導致後台佇列卡死問題。 |
| **12** | **Antigravity CLI 模型引擎接入 (Antigravity CLI Engine)** | v1.5.0 新增 | 深度接入本機 Antigravity CLI (`agy`)，免 API Key 呼叫 Gemini 4 Argon / Gemini 3.8 Flash / Claude 系列模型。<br>- **模型與強度解耦**：自 CLI 動態拉取之模型列表自動正規化（過濾 `-(low\|medium\|high\|xhigh\|max)` 與 `(High)` 等尾綴），正規化為 5 款純模型（`Gemini 4 Argon`、`Gemini 3.8 Flash`、`Claude Opus 5.5`、`Claude Sonnet 5.5`、`GPT-OSS 120B`），避免與推理強度下拉選單產生混淆。<br>- **即時單卡測試**：後端 `/api/config/test` 支援直接接收目標卡片之 `engine`、`model`、`reasoning_effort` 進行驗證，不強制依賴已寫入磁碟之全域翻譯設定；前端表單與卡片選單新增「測試此模型」按鈕；新增卡片時若無全域翻譯模型亦自動關聯。<br>- **管線化通訊**：採用無頭管道 stdin 傳遞 prompt 並關閉輸入端，徹底解決原生 CLI 的等待逾時問題。 |
| **13** | **互動式心智圖介面升級與 7 項專題微調 (Interactive Mindmap)** | v1.5.0 新增 | 參考 `SSShooter/mind-elixir-core` (v5.15.1) 全面升級論文閱讀脈絡心智圖，並完成 7 項關鍵體驗優化：<br>- **本地內嵌**：靜態資源放進 `web/vendor/mind-elixir/`，無外部依賴，相容 `build.py` 離線單檔 HTML 匯出。<br>- **Mermaid 轉 MindElixir**：前端高容錯解析器即時轉換 Mermaid `mindmap` 為樹狀資料結構，剝除框線語法與雙引號。<br>- **側欄與詳細檢視預設收合**：側欄預設「單側收合狀態」（向右單向展開，僅展開第一層主分支，其餘節點收攏帶計數徽章）；點擊「詳細檢視」大視窗 Modal 預設「雙側收合狀態」（雙欄放射分佈）。<br>- **專屬樹狀 SVG 與高對比按鈕**：徹底替換原本的 `+`/`-` 圖示為分支展開與聚合 SVG，避免與縮放功能混淆，強化工具列對比度。<br>- **Prompt 智慧引導 KaTeX 與 Basic Markdown**：引導生成時自然使用 `$O(N^2)$`、`$x$` 與 `**粗體**`、`代碼`，不硬性每點套用。<br>- **節點點擊摺疊修復**：修復 MindElixir 預設展開時收合按鈕透明度為 0 隱形的問題，支援直接點擊節點本體切換展開／收合。<br>- **PNG 匯出與 Obsidian Vault 圖片附件**：單獨下載心智圖改為直接下載高解析 `.png` 圖檔；匯出 Obsidian 檔名維持 `<stem>-mind-map.md`，文檔內放入 `![[<stem>-mind-map.png]]` 並同步在 Vault 資料夾寫入該 PNG 圖片。 |

---

## 2. 檔案變動對照表

### 2.1 新增檔案
- **後端模組與測試**：
  - `easyread/codeblocks.py`：程式碼區塊保護與正規化。
  - `easyread/jobs_api.py`：停止所有/批次任務 API。
  - `easyread/bulk/__init__.py`, `base.py`, `folder.py`, `progress.py`, `api.py`：資料夾批次匯入引擎。
  - `easyread/zotero/__init__.py`, `db.py`, `export.py`, `finder.py`, `migrate.py`, `progress.py`, `api.py`：Zotero 資料庫解析與整庫遷移引擎。
  - `tests/test_v14_features.py`：7 題針對 v1.4 移植特性的完整 Python 回歸測試。
  - `tests/test_antigravity_engine.py`：6 題針對 Antigravity CLI 路徑偵測、模型清單去重正規化、執行參數與單卡測試的單元測試。
- **前端模組與樣式**：
  - `easyread/web/css/bulk-import.css`：資料夾匯入與 Zotero 遷移進度彈窗樣式。
  - `easyread/web/css/categories.css`：分類樹展開、縮排、指示器樣式。
  - `easyread/web/css/reader-mobile.css`：手機版閱讀器精簡排版樣式。
  - `easyread/web/js/library/cat-tree.js`：分類路徑正規化與樹狀演算法。
  - `easyread/web/js/library/categories.js`：分類狀態、管理、移到、改名等邏輯。
  - `easyread/web/js/library/sidebar-tree.js`：側欄分類樹 HTML 渲染與論文展開。
  - `easyread/web/js/library/bulk-import.js`：資料夾匯入與 Zotero 前端流程。
  - `easyread/web/js/common/pick-folder.js`：跨平台/瀏覽器端通用資料夾選擇器。
  - `easyread/web/js/library/stop-jobs.js`：頂欄「停止翻譯（N）」按鈕與取消邏輯。
  - `easyread/web/js/reader/mobile.js`：手機版雙語閱讀器客戶端行為。
  - `easyread/web/vendor/mind-elixir/MindElixir.iife.js` & `MindElixir.css`：Mind Elixir 5.15.1 本地靜態資產。
  - `easyread/web/js/reader/mindmap-view.js`：心智圖轉換器、主題適配、工具列與大視窗 Modal 元件。
  - `tests/test_mindmap.cjs`：5 題心智圖資料解析、LaTeX 渲染、工具列操作與 Modal 行為測試。

### 2.2 修改檔案
- **後端核心**：
  - `easyread/engines.py`：新增 `antigravity_path`、`run_antigravity`（支援 `--output-format json`、`--effort` 與模型 ID 尾綴自動清理），整合進 `_run`、`for_translation`、`test`。
  - `easyread/cli_models.py`：新增 `antigravity()`，動態執行 `agy --models` 並去除推理強度尾綴與重複項，提供 5 款純模型 fallback。
  - `easyread/chat_models.py` & `easyread/chat_options.py`：支援 `antigravity` 引擎卡片正規化、預設模型（`gemini-4-argon`）與 `low`~`max` 推理強度驗證；解決 `DEFAULT_CHAT` 與 `engines` 模組循環引用問題。
  - `easyread/detect.py` & `easyread/netcheck.py` & `easyread/usage.py`：支援本機 `agy` 偵測、代理環境檢查與 `stats.models` Token 用量統計。
  - `easyread/settings_api.py`：增強 `test_engine`，允許前端傳入單卡 `engine`、`model`、`reasoning_effort` 直接測試，無需先儲存為全域翻譯模型。
  - `easyread/sources.py`：URL 解析撇號解碼防截斷（PR #37）。
  - `easyread/store.py`：支援連結本地 PDF（`link_pdf`）、單篇 JSON 損壞容錯隔離與修復。
  - `easyread/trash.py`：回收站容錯與連結 PDF 不刪原檔保護。
  - `easyread/jobs.py`：任務中斷乾淨處理（PR #56）、工作排程跳過已刪除項目。
  - `easyread/translate.py` & `easyread/checks.py`：整合程式碼區塊降級與 LaTeX 公式驗證。
  - `easyread/build.py` & `easyread/cli.py`：手機版 HTML 導出建構引擎（`--mobile`）。
  - `easyread/library.py` & `easyread/library_api.py`：批次匯入、任務與設定 API 整合。
  - `easyread/server.py`：註冊 `jobs_api`、`bulk.api`、`zotero.api`。
  - `easyread/research_v2.py`：放寬分類路徑長度上限至 120 字元。
- **前端介面**：
  - `easyread/web/js/common/settings-chat.js`：加入 `Antigravity CLI` 引擎卡片選擇、表單與卡片選單「測試此模型」功能，以及首次新增自動設為翻譯模型。
  - `easyread/web/js/common/settings-models.js` & `settings.js` & `easyread/web/js/reader/chat-effort.js`：整合 `antigravity` 模型清單下拉選單、推理強度選項與設定收集。
  - `easyread/web/library.html`：載入新 CSS 與 JS 模組，加入批次匯入、Zotero 遷移、停止按鈕等介面節點。
  - `easyread/web/js/library/sidebar.js`：整合樹狀分類與安全降級（相容無 `cat-tree.js` 的測試環境）。
  - `easyread/web/js/library/detail.js`：相容樹狀分類標籤顯示與安全降級，標題支援 `titleHtml` 安全渲染。
  - `easyread/web/js/library/import.js`：整合大於 5 篇防護確認彈窗。
  - `easyread/web/js/library/batch.js`：批次選取加入「停止翻譯」。
  - `easyread/web/js/library/update.js` & `electron/desktop-updates.cjs`：後台更新下載與跨平台支援。
  - `easyread/web/js/research/workspace.js` & `path-map.js`：支援多層子分類前綴過濾，研究探索全介面、起點論文、閱讀路徑節點全面套用 `titleHtml` LaTeX 安全渲染與 `cleanTopicQuery` 標題淨化。
  - `easyread/web/js/reader/planner.js`：當前論文標題套用 `titleHtml`，跳轉研究路徑自動清理 LaTeX。
  - `easyread/web/js/common/markup.js`：強化 `PR.titleText`，徹底剝除 TeX 宏與公式標記。
  - `easyread/web/i18n/zh-TW.json` & `en.json`：補齊所有新增功能與 Antigravity CLI 詞條（共 1571 條），完成 100% 繁體中文與英文對帳。

---

## 3. 重要相容性細節與避坑指引（Agent 必讀）

1. **循環引用陷阱 (`chat_models.py`)**：
   - `config.py` 在初始化時會引入 `DEFAULT_CHAT`。
   - `chat_models.py` 頂層**不可直接寫** `from . import engines`，否則會觸發 `ImportError: cannot import name 'DEFAULT_CHAT' from partially initialized module 'easyread.chat_models'`。
   - 解決方案：模組頂層定義 `DEFAULT_CHAT`，在需要 `EngineError` 的函式內採用延遲引入（lazy import）。

2. **單元測試沙箱隔離 (`sidebar.js` 與 `detail.js`)**：
   - 部分測試（如 `tests/test_library_archive.cjs`）只會在 Node `vm` 沙箱中載入 `app.js`、`sidebar.js`、`detail.js`，而**不會載入** `cat-tree.js` 與 `categories.js`。
   - 因此，`sidebar.js` 和 `detail.js` 必須具備安全預設值降級：
     - `L.cats` 降級：`typeof L.cats === "function" ? L.cats() : (L.side?.cats || [])`
     - `PR.catTree` 降級：`PR.catTree || { depth: () => 0, leaf: c => c, label: c => c, ... }`
     - `foldSlot` 降級：`const foldSlot = (kids, open) => (PR.foldSlot ? PR.foldSlot(kids, open) : '<span class="fold-slot"></span>');`

3. **桌面更新機制與倉庫位址 (`desktop-updates.cjs`, `main.cjs`, `package.json`, `updates.py`)**：
   - 上游做法：上游在 `desktop-updates.cjs` 中預設指定 GitHub 來源（`Edwardxlai/easyread`），並透過 `electron-updater` 與 GitHub Releases 中的 `latest.yml` / `.blockmap` / `Setup.exe` 進行差分或全量更新。
   - PaperRead 適配：
     - `electron/main.cjs` 設置預設更新倉庫為 `YuriyLin/PaperRead`（亦支援 `EASYREAD_UPDATE_REPOSITORY` 環境變數覆蓋）。
     - `easyread/updates.py` 設置預設倉庫 `YuriyLin/PaperRead` 並啟用 `check_updates` 檢查。
     - `package.json` 配置 `repository` 與 `build.publish`，確保 `electron-builder` 在建置 Windows NSIS 安裝檔時自動產生合規的 `latest.yml` 與內嵌更新資訊。
     - `desktop-updates.cjs` 保持無參數預設 `repository = ""`，以滿足單元測試對未配置 fork 的隔離檢查。

4. **PaperRead 封存功能嚴格保護**：
   - 在分類計數、側欄分類樹展開時，所有自建分類與內建分類（包括全部、星標、各閱讀狀態）一律需保留 `!i.archived` 判斷，確保封存條目永遠不會外溢到閱讀看板或活躍分類中。

5. **LaTeX KaTeX 安全渲染與平滑降級**：
   - 包含數學符號或公式的論文標題使用 `PR.titleHtml`（`trust: false`），並提供 `const titleHtml = (v, fallback = "") => PR.titleHtml ? PR.titleHtml(v || fallback) : esc(v || fallback);` 降級保護，防止在純邏輯測試環境中因未載入 `markup.js` 導致崩潰。

6. **Antigravity CLI (`agy`) 管線通訊與模型正規化細節**：
   - **Stdin 管道模式**：呼叫 `agy` 時必須透過 `stdin` 傳入 prompt 並立即關閉 `stdin`（即 `_communicate(_popen(args, cwd), prompt, ...)`）；不可使用 `-p prompt` 且保持 `stdin` 開啟，否則 `agy` 會持續等待標準輸入導致 timeout。
   - **模型與推理強度分離**：`agy --models` 原生會列出 `gemini-4-argon-high`、`gemini-4-argon-low` 等變體，但 `agy` 支援不帶強度後綴的乾淨模型 ID（如 `--model gemini-4-argon --effort low`）。`cli_models.antigravity()` 與 `engines.run_antigravity()` 均會自動剝除強度尾綴，由 `--effort` 統一控制推理強度。

7. **Python Editable 環境與已安裝桌面版後端注意事項**：
   - 本機開發環境已執行 `python -m pip install -e . --no-deps`，確保從任何目錄執行 `python -m easyread` 皆載入此工作區最新原始碼（避免誤載入 `site-packages` 中的舊版套件）。
   - 若修改後端 Python 程式碼，需重啟正在運行的 `easyread serve` 服務進程；若要更新已安裝的桌面版 `PaperRead.exe`，需重新打包編譯 `easyread-backend.exe`。

---

## 4. 驗證指令與測試結果

接手後若有任何修改，請執行以下命令確認無回歸：

```bash
# 1. 後端 Python 測試 (438 tests)
pytest

# 2. 前端 Node.js 單元測試 (159 tests, 排除需 playwright 的 e2e.cjs)
node --test (Get-ChildItem tests/*.cjs -Exclude e2e.cjs)

# 3. 繁體中文與多語系在地化完整度檢查 (缺英文 0，沒套中文 0)
python scripts/i18n_check.py
```

- **目前驗證狀態**：
  - `pytest`：**443 passed**（通過率 100%）。
  - `node --test`：**168 passed**（通過率 100%）。
  - `i18n_check.py`：**詞條 1594 條，缺英文 0，沒套的中文 0**。
