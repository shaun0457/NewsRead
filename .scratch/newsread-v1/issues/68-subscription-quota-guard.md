# 68: 訂閱額度保護

**What to build:** 訂閱額度是使用者自己寫程式也在用的同一份，NewsRead 的背景工作不能把它吃光。Claude Code 的 5 小時額度超過設定的比例時，背景工作暫停到重置時間，或依設定改用 API key；使用者手動觸發的工作照跑。

**Blocked by:** 07（常駐與排程器）、14（AI 分類寫進帳本）、67（AI 引擎偵測、自帶 key 和每種工作的引擎）

**Status:** in-progress（保護、事件、右上角標示、用量頁、匯入後自動翻譯的保護已做；背景預設不用訂閱已定（spec）；Telegram 通知等 #16）

- [x] 開工前先查 Anthropic 和 OpenAI 對「第三方程式在背景呼叫個人訂閱 CLI」的條款，結論寫進這張 ticket；如果不允許，背景工作預設改用 API key
- [x] 門檻〔預設〕70%，可以設定；超過時背景工作（分類、翻譯、起草、論點變化偵測）不再呼叫引擎（用假引擎回報 75% 測試）
  - 2026-11-15：保護做在 `Engines.run(trigger="background")`，四種工作都測過。注意：目前只有分類真的走 `Engines.run`；匯入後的自動翻譯還走舊的 `/api/config` 引擎（不經過這裡，也是使用者貼網址時才觸發），起草和論點變化偵測還沒有呼叫端，改走 `Engines.run` 時要帶 `trigger="background"`。
- [x] 暫停期間新進的資料照常匯入，標「待分類」存在資料庫，不放在記憶體佇列
- [x] 到了重置時間依匯入時間補做，每一輪補做不超過上限〔預設〕50 則（碰到上限的測試）
- [x] 設成「改用 API key」時，背景工作改走 API，並受 API 每月上限約束
- [ ] 手動問 AI、按起草照跑，執行前提醒額度已超過門檻
  - 2026-11-15：後端的手動呼叫都照跑並在 `quota_notice` 帶提醒。（當時畫面只有閱讀器的問 AI 會提醒；已由下一條取代。）
  - 2026-11-15 補：規則定為「每個手動 AI 入口都在送出前提醒」。閱讀器的問 AI（論文和文章共用 chat.js，筆記卡片的點評也走這裡）、筆記幫手（點評、幫我改、起草稿，notehelp.js）、智慧標註、心智圖（側欄產生和匯出時補產生）、讓模型重譯這段都已接上（`test_quota_guard_ui.cjs` every manual AI entry…）。2026-11-27（gate F1）：按了才開始的翻譯、整理算手動，送出前提醒。2026-11-28：匯入後的自動翻譯接上保護（使用者決定）：用 Claude Code、Codex 訂閱時預設要使用者按；額度超過門檻、API 到上限時等，排程每 5 分鐘補翻（每輪最多 5 篇）；文獻庫和閱讀器顯示「等額度重置」/「等你按翻譯」，可以現在開始或不用了。設定頁的「測試引擎」是很小的探測呼叫，不提醒。提醒沒有依這次用的引擎區分（前端不知道計費方式），用 API 或本機模型時也可能看到 Claude 額度提醒，每段暫停只一次。題材頁目前沒有手動起草的按鈕，之後加的時候照同一個規則接。
- [ ] API 每月上限：到 80% Telegram 通知；到上限停掉翻譯和起草，分類改等訂閱額度（測試）
  - 2026-11-15：80% 和到上限都記事件並呼叫通知介面（`quota_guard.set_notifier`），預設不送；Telegram 等 ticket 16 接上。到上限停掉翻譯和起草、分類改等訂閱額度已做並有測試。
- [ ] 每次觸發保護都記一筆事件（錯誤代碼 + 固定說明），用量頁看得到
  - 2026-11-15：事件的儲存和讀取 API（`GET /api/ai/guard/events`）已做；用量頁本身是 ticket 29。
- [x] 每頁右上角在保護中時顯示「背景工作暫停」

## 條款查證（2026-11-15）

引文怎麼取得：除了特別標注的，都是實作 agent 在 2026-11-15 用 WebFetch 抓官方頁面取得；主 session 沒有另外逐字核對，拍板前建議用瀏覽器再對一次。

問題：NewsRead 是使用者自己在本機跑的程式，呼叫未修改的 `claude` / `codex` 執行檔、用使用者自己的登入。手動按的（問 AI）和排程在背景跑的（分類等），各自是否符合 Anthropic 和 OpenAI 的條款？只引用官方一手來源，查詢日期都是 2026-11-15。

### Anthropic（Claude Code）：不明確，偏向不允許背景使用

- [Claude Code — Legal and compliance](https://code.claude.com/docs/en/legal-and-compliance)
  - 適用條款：「Consumer Terms of Service - for Free, Pro, Max, and Ultra users」。
  - 「**OAuth authentication** is intended exclusively for purchasers of Claude Free, Pro, Max, Ultra, Team, and Enterprise subscription plans and is designed to support ordinary use of Claude Code and other native Anthropic applications.」
  - 「Developers building products or services that interact with Claude's capabilities, including those using the Agent SDK, should use API key authentication through Claude Console or a supported cloud provider. Anthropic does not permit third-party developers to offer Claude.ai login into their own applications, or to route requests through Free, Pro, Max, or Ultra plan credentials on behalf of their users.」
  - 「…Nor does it prevent an end user from signing in to the unmodified Claude Code binary with their own Claude subscription」（原文是一句排除說明的後半句：前半句說上面那條限制不涵蓋什麼，這裡只引用後半）。
  - 「Advertised usage limits for Pro, Max, and Ultra plans assume ordinary, individual usage of Claude Code and the Agent SDK.」
- [Consumer Terms of Service](https://www.anthropic.com/legal/consumer-terms)（Effective Oct 8, 2025）第 3 節：「You may not access or use, or help another person to access or use, our Services in the following ways:」第 7 點：「Except when you are accessing our Services via an Anthropic API Key or where we otherwise explicitly permit it, to access the Services through automated or non-human means, whether through a bot, script, or otherwise.」
- [Run Claude Code programmatically](https://code.claude.com/docs/en/headless)：官方示範 `claude -p` 用在腳本和 CI，但同一頁說「Set `ANTHROPIC_API_KEY` before running it, because bare mode doesn't use your subscription login」，並且「`--bare` is the recommended mode for scripted and SDK calls, and will become the default for `-p` in a future release.」

判讀：
- 手動觸發（使用者按了才呼叫一次）：使用者自己登入、未修改的執行檔、只給自己用，不是「on behalf of their users」，最接近「ordinary, individual usage」。**允許的可能性高，但沒有明文。**
- 背景排程（沒人在場、定時呼叫）：屬於 Consumer Terms 3.7 的「automated or non-human means … script」，例外只有 API key 或「explicitly permit」。官方文件示範了 `claude -p` 腳本，卻建議腳本用 `--bare`（不讀訂閱登入、要 API key）。沒有任何一句明文允許第三方程式在背景用個人訂閱。**不明確，偏向不允許。**
- 實務風險：`--bare` 變成 `-p` 的預設之後，NewsRead 目前用 `claude -p` 的呼叫不會再讀訂閱登入。

### OpenAI（Codex CLI）：不明確，偏向不允許背景使用

- [Codex — Authentication](https://learn.chatgpt.com/docs/auth)（`developers.openai.com/codex/auth` 轉址到這裡；`learn.chatgpt.com` 是不是 OpenAI 的官方文件站沒有另外確認，只知道是從官方網址轉過去的）
  - 「Sign in with an API key」一節：「Use API key authentication for programmatic Codex CLI workflows, such as CI/CD jobs.」
  - 「Login on headless devices」一節：「API keys are still the recommended default for automation.」
  - 給排程用的 access token 只有 ChatGPT Enterprise 工作區（管理員開權限後由成員建立）：「Access tokens are intended for trusted scripts, schedulers, and private CI runners.」個人方案沒有對應的做法。
- [OpenAI Terms of Use](https://openai.com/policies/row-terms-of-use/)：「What you cannot do」列了「Automatically or programmatically extract data or Output」。**注意**：這頁和 Help Center 的〈Using Codex with your ChatGPT plan〉用 WebFetch 抓都回 403，這句是從搜尋引擎對官方頁面的摘錄取得，沒有逐字對過原頁；之後要用瀏覽器再對一次。

判讀：官方文件把「程式化、自動化」的用法都導向 API key，個人 ChatGPT 方案沒有給排程的認證方式；條款禁止程式化取得 Output。沒有明文禁止「本機程式呼叫使用者自己登入的 Codex CLI」，但也沒有允許。**不明確，偏向不允許。**（另外：Codex CLI 關不掉工具，分類本來就不用它，見 ticket 14。）

### 沒查的

- Antigravity CLI（Google）的條款這次沒查（ticket 只要求 Anthropic 和 OpenAI），先比照上面的處理。

### 據此的預設（待使用者拍板）

照這張 ticket 的規則（不允許或不明確 → 背景工作預設改用 API key）：
- **背景工作**（分類、翻譯、起草、論點變化偵測）**預設不用任何訂閱 CLI**（Claude Code、Codex CLI、Antigravity CLI），改用 API key（Anthropic、OpenAI 相容）或本機模型（Ollama）。沒有 key 也沒有本機模型時，背景工作留在「待分類」，不會失敗。
- 設定頁有一個開關「背景工作也可以用訂閱」，預設關。使用者自己判斷條款後打開，才會用訂閱跑背景工作，這時才套用 70% 門檻保護。
- **手動觸發**（問 AI、按起草）照常可以用訂閱。
