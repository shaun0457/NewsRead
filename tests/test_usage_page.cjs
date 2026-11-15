/* Ticket 29：用量頁的畫面邏輯（各區塊、跳脫、上限）和載入流程（過期回應、錯誤、逾時、焦點）。假的 DOM，資料是虛構的範例。 */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const WEB = path.join(__dirname, "../easyread/web");

function load(extra = {}, dom = {}) {
  const PR = Object.assign({
    lang: "zh-TW",
    t: (s, values = {}) => s.replace(/\{(\w+)\}/g, (m, key) => values[key] ?? m),
    esc: (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"),
    $: (sel) => (dom.els ? dom.els[sel] || null : null),
  }, extra);
  const document = { addEventListener() {}, querySelector: (sel) => (dom.focus ? dom.focus[sel] || null : null) };
  const context = { window: { PR }, document, setTimeout, clearTimeout, AbortController };
  vm.runInNewContext(fs.readFileSync(path.join(WEB, "js/usage/app.js"), "utf8"), context);
  return PR.usagePage;
}
const X = load();
const NOW = 1763179200;  // 2026-11-15 04:00 UTC
const daily = (n = 14) => Array.from({ length: n }, (_, i) => ({ date: `2026-11-${String(2 + i).padStart(2, "0")}`, tokens: i === 13 ? 900 : i * 10 }));
const REPORT = () => ({
  period: "month", label: "2026-11", now: NOW, empty: false,
  claude: { limits: { five_hour: { used: 0.42, resets_at: NOW + 3600 }, seven_day: { used: 0.61, resets_at: NOW + 86400 } }, at: NOW - 120,
            window: { calls: 96, tokens: 410000 } },
  cli: { codex: { calls: 64, tokens: 1100000 }, antigravity: { calls: 0, tokens: 0 } },
  api: { month: "2026-11", spent_usd: 3.37, by_engine: [{ engine: "anthropic", spent_usd: 2.4 }, { engine: "openai", spent_usd: 0.97 }] },
  tasks: [{ task: "triage", engine: "claude", model: "claude-haiku-5-5", calls: 3912, tokens: 8400000, cost_usd: null },
          { task: "thesis_change", engine: "anthropic", model: "claude-sonnet-5-5", calls: 402, tokens: 1900000, cost_usd: 2.4 },
          { task: "translate", engine: "ollama", model: "<b>x</b>", calls: 3, tokens: 10, cost_usd: 0 }],
  tasks_truncated: false,
  sources: [{ source: "triage", calls: 100, tokens: 9700000, items: 50, linked: 3 }, { source: "newsread", calls: 4, tokens: 20, items: null, linked: null },
            { source: "<img src=x>", calls: 1, tokens: 1, items: 0, linked: 0 }],
  sources_truncated: false, daily: daily(), daily_days: 14,
});
const GUARD = (over = {}) => Object.assign({
  settings: { background_subscription: true, threshold: 70, on_exceed: "wait", api_monthly_usd: 15 },
  quota: { used: 0.42, resets_at: NOW + 3600, at: NOW - 120, over: false, until: null },
  api: { spent_usd: 3.37, cap_usd: 15, month: "2026-11", warn: false, reached: false },
  background: { paused: false, reason: null, until: null },
}, over);
const ready = (over = {}) => Object.assign({ status: "ready", period: "month", data: REPORT(), guard: GUARD(), events: [], error: null }, over);

test("token and money formatting", () => {
  assert.equal(X.fmtTokens(999), "999");
  assert.equal(X.fmtTokens(8400000), "8.4M");
  assert.equal(X.fmtTokens(2000), "2K");
  assert.equal(X.fmtTokens(1.2e9), "1.2B");
  assert.equal(X.money(3.372), "$3.37");
  assert.equal(X.money(0.004), "<$0.01");
  assert.equal(X.money(0), "$0.00");
  assert.equal(X.ratioText(50, 3), "6%");
  assert.equal(X.ratioText(0, 0), "—");
  assert.equal(X.ratioText(null, null), "—");
});

test("the Claude card shows both windows, the protection line, the update time and the whole-account note", () => {
  const html = X.claudeCardHtml(REPORT(), GUARD(), X.tx());
  assert.match(html, /5 小時額度/);
  assert.match(html, /<b>42%<\/b>/);
  assert.match(html, /<b>61%<\/b>/);
  assert.match(html, /7 天額度/);
  assert.match(html, /直線 = 你設的保護線 70%/);
  assert.match(html, /left:70%/);
  assert.match(html, /role="meter"[^>]*aria-valuenow="42"/);
  assert.match(html, /整個帳號的用量，包含你自己用 Claude Code 寫程式/);
  assert.match(html, /上次更新：\d\d:\d\d/);
  assert.match(html, /NewsRead 這 5 小時：96 次 · 410K token/);
  assert.match(html, /看不到占額度幾 %/);
  assert.doesNotMatch(html, /\$/);  // 訂閱不折算成金額
});

test("the 5-hour bar turns red over the line, and a window past its reset time is marked as stale", () => {
  const hot = REPORT();
  hot.claude.limits.five_hour.used = 0.74;
  assert.match(X.claudeCardHtml(hot, GUARD(), X.tx()), /<i class="hot" style="width:74%">/);
  const old = REPORT();
  old.claude.limits.five_hour.resets_at = NOW - 1;
  const html = X.claudeCardHtml(old, GUARD(), X.tx());
  assert.match(html, /class="meter stale"/);
  assert.match(html, /已過重置時間，下次呼叫後更新/);
  assert.doesNotMatch(html, /left:70%/);  // 已經重置：不畫保護線
  // 重置時間還沒到，但數字是 5 小時多以前記的：一定已經重置過（跟後端 quota_state 一樣取早的）
  const aged = REPORT();
  aged.claude.at = NOW - 5 * 3600 - 1;
  assert.match(X.claudeCardHtml(aged, GUARD(), X.tx()), /class="meter stale"[\s\S]*已過重置時間/);
  assert.equal(X.quotaUntil({ resets_at: NOW + 3600 }, NOW - 5 * 3600 - 1, "five_hour"), NOW - 1);
  assert.equal(X.quotaUntil({ resets_at: NOW + 3600 }, NOW - 60, "five_hour"), NOW + 3600);
  assert.equal(X.quotaUntil({}, null, "five_hour"), null);
});

test("without a quota number the card says so; without the guard there is no line", () => {
  const none = REPORT();
  none.claude.limits = {};
  none.claude.at = null;
  assert.match(X.claudeCardHtml(none, GUARD(), X.tx()), /還沒有收到額度數字/);
  const html = X.claudeCardHtml(REPORT(), null, X.tx());
  assert.doesNotMatch(html, /保護線/);
  assert.match(html, /<b>42%<\/b>/);
});

test("Codex shows tokens only and says the quota is not visible; Antigravity only appears when used", () => {
  const html = X.cliCardHtml(REPORT(), "codex", "Codex CLI", X.tx());
  assert.match(html, /本月 64 次 · 1\.1M token/);
  assert.match(html, /看不到額度用了多少/);
  assert.doesNotMatch(html, /\$/);
  assert.match(X.cliCardHtml(Object.assign(REPORT(), { period: "day" }), "codex", "Codex CLI", X.tx()), /今天 64 次/);
  const view = X.viewHtml(ready());
  assert.match(view, /Codex CLI/);
  assert.doesNotMatch(view, /Antigravity CLI/);
  const used = ready();
  used.data.cli.antigravity = { calls: 2, tokens: 50 };
  assert.match(X.viewHtml(used), /Antigravity CLI/);
});

test("the API card shows this month's spend against the cap, the 80% line and the split by provider", () => {
  const html = X.apiCardHtml(REPORT(), GUARD(), X.tx());
  assert.match(html, /\$3\.37 \/ \$15\.00/);
  assert.match(html, /<b>22%<\/b>/);
  assert.match(html, /left:80%/);
  assert.match(html, /Anthropic API \$2\.40 · OpenAI 相容 \$0\.97/);
  assert.match(html, /訂閱不折算成金額/);
  const over = GUARD({ api: { spent_usd: 16, cap_usd: 15, month: "2026-11", warn: true, reached: true } });
  const big = REPORT();
  big.api.spent_usd = 16;
  assert.match(X.apiCardHtml(big, over, X.tx()), /<i class="hot" style="width:100%">/);  // 超過上限：條不超出
  const zero = X.apiCardHtml(REPORT(), GUARD({ api: { spent_usd: 3.37, cap_usd: 0 } }), X.tx());
  assert.match(zero, /月上限設成 0/);
  assert.doesNotMatch(zero, /role="meter"/);
  assert.doesNotMatch(X.apiCardHtml(REPORT(), null, X.tx()), /role="meter"/);
  const none = REPORT();
  none.api = { month: "2026-11", spent_usd: 0, by_engine: [] };
  assert.match(X.apiCardHtml(none, GUARD(), X.tx()), /這段期間沒有 API 花費/);
});

test("the daily chart has 14 bars, the tallest is full height, empty days are marked, and the dates are labelled", () => {
  const html = X.daysHtml(REPORT(), X.tx());
  assert.equal((html.match(/<span[ >][^<]*<\/span>/g) || []).filter((s) => s.includes("title=")).length, 14);
  assert.match(html, /height:100%/);
  assert.match(html, /class="zero" style="height:0%"/);  // 第一天 0 token
  assert.match(html, /role="img" aria-label="每日 token 長條圖：11\/2 0、/);
  assert.match(html, />今天</);
  assert.match(html, />11\/2</);
  const longer = REPORT();
  longer.daily = daily(30);
  assert.equal((X.daysHtml(longer, X.tx()).match(/title=/g) || []).length, 14);  // 多的只取最後 14 天
  const flat = REPORT();
  flat.daily = daily().map((d) => ({ date: d.date, tokens: 0 }));
  assert.doesNotMatch(X.daysHtml(flat, X.tx()), /height:[1-9]/);  // 全是 0：不畫高度
});

test("the task table separates engine and model, shows cost only for API and escapes model names", () => {
  const html = X.tasksHtml(REPORT(), X.tx());
  assert.match(html, /哪個工作用最多（本月）/);
  assert.match(html, /<td data-no-i18n>分類<\/td><td data-no-i18n>Claude Code · claude-haiku-5-5<\/td>/);
  assert.match(html, /3,912/);
  assert.match(html, /8\.4M/);
  assert.match(html, /<td class="r muted" data-no-i18n>訂閱<\/td>/);
  assert.match(html, /<td class="r num" data-no-i18n>\$2\.40<\/td>/);
  assert.match(html, /本機模型（Ollama）[^<]*&lt;b&gt;x&lt;\/b&gt;/);
  assert.doesNotMatch(html, /<b>x<\/b>/);
  assert.match(X.tasksHtml(Object.assign(REPORT(), { period: "day" }), X.tx()), /（今天）/);
  const none = REPORT();
  none.tasks = [];
  assert.match(X.tasksHtml(none, X.tx()), /這段期間還沒有/);
  const cut = REPORT();
  cut.tasks_truncated = true;
  assert.match(X.tasksHtml(cut, X.tx()), /只列用最多的前 3 列/);
});

test("the source table shows the linked share only where it is known and escapes source names", () => {
  const html = X.sourcesHtml(REPORT(), X.tx());
  assert.match(html, /AI 分類<\/td><td class="r num">100<\/td><td class="r num">50<\/td><td class="r num">9\.7M<\/td><td class="r num">6%<\/td>/);
  assert.match(html, /閱讀器（翻譯、問 AI）<\/td><td class="r num">4<\/td><td class="r num">—<\/td><td class="r num">20<\/td><td class="r num">—<\/td>/);
  assert.match(html, /&lt;img src=x&gt;/);
  assert.doesNotMatch(html, /<img/);
  assert.match(html, /依個別媒體分開看/);
});

test("events are escaped, show the numbers they carry, and stop at the cap", () => {
  const list = Array.from({ length: 25 }, (_, i) => ({ seq: 25 - i, at: "2026-11-14T05:20:00.000000+00:00", code: "QUOTA_PAUSED", task: "triage",
    message: i === 0 ? "<script>alert(1)</script>" : "額度保護", data: i === 1 ? { used: 0.74 } : i === 2 ? { spent_usd: 12, cap_usd: 15 } : {} }));
  const html = X.eventsHtml(list, NOW, X.tx());
  assert.equal((html.match(/<li /g) || []).length, X.MAX_EVENTS);
  assert.equal(X.MAX_EVENTS, 20);
  assert.match(html, /只顯示最近 20 筆/);
  assert.match(html, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, / · 74%/);
  assert.match(html, / · \$12\.00 \/ \$15\.00/);
  assert.match(html, /只記錯誤代碼和固定說明/);
  assert.doesNotMatch(X.eventsHtml(list.slice(0, 20), NOW, X.tx()), /只顯示最近/);
  assert.match(X.eventsHtml([], NOW, X.tx()), /還沒有額度保護、限流或上限的事件/);
  const failed = X.eventsHtml(null, NOW, X.tx());  // 讀不到不能說成沒有事件
  assert.match(failed, /事件暫時讀不到/);
  assert.doesNotMatch(failed, /還沒有額度保護/);
});

test("the guard banner says why background work is paused, with the reset time for the quota", () => {
  const quota = GUARD({ quota: { used: 0.74, over: true, until: NOW + 3600 }, background: { paused: true, reason: "quota", until: NOW + 3600 } });
  const html = X.guardBannerHtml(quota, NOW, X.tx());
  assert.match(html, /額度保護中：/);
  assert.match(html, /到 74%，超過你設的 70%/);
  assert.match(html, /\d\d:\d\d 額度重置後自動接著跑/);
  assert.match(html, /href="\/settings#models"/);
  assert.match(X.guardBannerHtml(GUARD({ background: { paused: true, reason: "api_cap", until: null } }), NOW, X.tx()), /花費到了上限/);
  assert.match(X.guardBannerHtml(GUARD({ background: { paused: true, reason: "no_api", until: null } }), NOW, X.tx()), /還沒有 API key 或本機模型/);
  assert.equal(X.guardBannerHtml(GUARD(), NOW, X.tx()), "");
  assert.equal(X.guardBannerHtml(null, NOW, X.tx()), "");
});

test("states: loading, empty (no AI calls yet), error with a fixed text, and the full page", () => {
  assert.match(X.viewHtml(ready({ status: "loading" })), /class="skel"/);
  assert.match(X.viewHtml(ready({ status: "loading" })), /aria-busy="true"/);
  const empty = ready();
  empty.data = { period: "month", now: NOW, empty: true, claude: { limits: {} }, cli: {}, api: {}, tasks: [], sources: [], daily: [] };
  const e = X.viewHtml(empty);
  assert.match(e, /還沒有任何 AI 呼叫/);
  assert.match(e, /每一次呼叫都會記下日期、來源、工作、引擎、模型和 token/);
  assert.doesNotMatch(e, /class="quota"/);
  const err = X.viewHtml(ready({ status: "error", error: "failed" }));
  assert.doesNotMatch(err, /role="alert"/);  // 錯誤只由 #usageStatus 念一次
  assert.match(err, /讀不到用量/);
  assert.match(err, /本機服務暫時沒有回應。資料沒有遺失。/);
  assert.match(err, /data-act="retry"/);
  assert.match(X.viewHtml(ready({ status: "error", error: "timeout" })), /等太久了/);
  const full = X.viewHtml(ready({ events: [{ at: "2026-11-14T05:20:00+00:00", message: "訊息", data: {} }] }));
  for (const part of ["Claude Code", "API key 花費", "最近 14 天", "哪個工作用最多", "哪個來源用最多", "事件"]) assert.ok(full.includes(part), part);
});

test("the period buttons say which one is pressed", () => {
  const month = X.controlsHtml(ready(), X.tx());
  assert.match(month, /data-period="month"[^>]*aria-pressed="true"/);
  assert.match(month, /data-period="day"[^>]*aria-pressed="false"/);
  assert.match(X.controlsHtml(ready({ period: "day" }), X.tx()), /data-period="day"[^>]*aria-pressed="true"/);
});

/* ---------- 載入流程 ---------- */
function page(responses) {
  const els = { "#view": { innerHTML: "", setAttribute() {} }, "#controls": { innerHTML: "" }, "#stamp": { innerHTML: "" }, "#usageStatus": { textContent: "" } };
  const focused = [];
  const focus = {};
  const target = (sel, disabled = false) => (focus[sel] = { disabled, focus: () => focused.push(sel) });
  const calls = [];
  const api = async (url, opts) => {
    calls.push(url);
    const r = responses(url, opts, calls.length);
    if (r instanceof Promise) return r;
    if (r instanceof Error) throw r;
    return r;
  };
  const P = load({ api }, { els, focus });
  Object.assign(P.state, { status: "loading", period: "month", data: null, guard: null, events: null, error: null, busy: false, said: "" });
  return { P, els, focused, calls, target };
}
const serve = (over = {}) => (url) => {
  if (url.startsWith("/api/usage")) return over.usage || REPORT();
  if (url === "/api/ai/guard") return over.guard === undefined ? GUARD() : over.guard;
  if (url === "/api/ai/guard/events") return over.events === undefined ? { events: [{ at: "2026-11-14T05:20:00+00:00", message: "訊息", data: {} }] } : over.events;
  throw new Error("unexpected " + url);
};

test("load asks for the report with the period and shows the page", async () => {
  const s = page(serve());
  await s.P.load();
  assert.deepEqual(s.calls.sort(), ["/api/ai/guard", "/api/ai/guard/events", "/api/usage?period=month"]);
  assert.equal(s.P.state.status, "ready");
  assert.match(s.els["#view"].innerHTML, /最近 14 天/);
  assert.match(s.els["#stamp"].innerHTML, /更新於 \d\d:\d\d/);
  assert.match(s.els["#controls"].innerHTML, /data-period="month"/);
});

test("without the guard or the events the rest of the page still shows; without the report it is an error", async () => {
  const s = page(serve({ guard: new Error("down"), events: new Error("down") }));
  await s.P.load();
  assert.equal(s.P.state.status, "ready");
  assert.equal(s.P.state.events, null);
  assert.match(s.els["#view"].innerHTML, /事件暫時讀不到/);
  assert.doesNotMatch(s.els["#view"].innerHTML, /保護線/);
  const bad = page(serve({ usage: new Error("secret path C:\\Users\\x\\db.sqlite3") }));
  await bad.P.load();
  assert.equal(bad.P.state.status, "error");
  assert.match(bad.els["#view"].innerHTML, /本機服務暫時沒有回應/);
  assert.doesNotMatch(bad.els["#view"].innerHTML, /secret path|Users/);  // 只顯示固定文案
  const odd = page(serve({ usage: { error: "x" } }));
  await odd.P.load();
  assert.equal(odd.P.state.status, "error");  // 回傳的不是用量報表
});

test("a slow report that comes back after a newer request is ignored", async () => {
  let release;
  const slow = new Promise((r) => { release = r; });
  const s = page((url, opts, n) => (url.startsWith("/api/usage") && n === 1 ? slow : serve()(url)));
  const first = s.P.load();
  s.P.state.period = "day";
  await s.P.load(true);
  const day = REPORT();
  day.label = "STALE";
  release(Object.assign(day, { period: "month" }));
  await first;
  assert.equal(s.P.state.data.label, "2026-11");  // 慢的那次沒有蓋掉新的
});

test("a quiet reload marks the page busy, ignores another refresh, and says when it is done", async () => {
  let release;
  const s = page((url, opts, n) => (url.startsWith("/api/usage") && n > 3 ? new Promise((r) => { release = r; }) : serve()(url)));
  const attrs = {};
  s.els["#view"].setAttribute = (k, v) => { attrs[k] = v; };
  await s.P.load();
  assert.equal(attrs["aria-busy"], "false");
  const press = (act) => s.P.onClick({ target: { closest: () => ({ dataset: { act } }) } });
  const pending = press("refresh");
  assert.equal(s.P.state.status, "ready");  // 舊的資料還留著
  assert.equal(attrs["aria-busy"], "true");
  assert.match(s.els["#controls"].innerHTML, /data-act="refresh" aria-disabled="true"/);
  const before = s.calls.length;
  press("refresh");
  assert.equal(s.calls.length, before);  // 正在讀：不重複發
  release(REPORT());
  await pending;
  assert.equal(attrs["aria-busy"], "false");
  assert.equal(s.els["#usageStatus"].textContent, "用量已更新");
  assert.doesNotMatch(s.els["#controls"].innerHTML, /aria-disabled/);
});

test("a newer load cancels the request it replaces", async () => {
  const signals = [];
  const s = page((url, opts, n) => {
    if (url.startsWith("/api/usage")) signals.push(opts.signal);
    return url.startsWith("/api/usage") && n === 1
      ? new Promise((_, reject) => opts.signal.addEventListener("abort", () => reject(Object.assign(new Error("aborted"), { name: "AbortError" }))))
      : serve()(url);
  });
  const first = s.P.load();
  await s.P.load(true);
  await first;
  assert.equal(signals[0].aborted, true);
  assert.equal(signals[1].aborted, false);
  assert.equal(s.P.state.status, "ready");  // 被取消的那次不會把頁面變成錯誤
});

test("a request that takes too long is aborted and shown as a timeout", async () => {
  const s = page((url, opts) => new Promise((_, reject) => opts.signal.addEventListener("abort", () => reject(Object.assign(new Error("aborted"), { name: "AbortError" })))));
  s.P.timeoutMs = 5;
  await s.P.load();
  assert.equal(s.P.state.status, "error");
  assert.equal(s.P.state.error, "timeout");
  assert.match(s.els["#view"].innerHTML, /等太久了/);
  assert.equal(X.errorKind(new Error("x"), false), "failed");
  assert.equal(X.errorKind({ name: "AbortError" }, false), "timeout");
});

test("switching the period reloads, keeps the focus on the pressed button, and ignores a repeat press", async () => {
  const s = page(serve());
  s.target('#controls [data-period="day"]');
  await s.P.load();
  const press = (dataset) => s.P.onClick({ target: { closest: () => ({ dataset }) } });
  await press({ period: "day" });
  assert.equal(s.P.state.period, "day");
  assert.ok(s.calls.includes("/api/usage?period=day"));
  assert.ok(s.focused.includes('#controls [data-period="day"]'));
  const before = s.calls.length;
  await press({ period: "day" });
  await press({ period: "year" });
  assert.equal(s.calls.length, before);  // 一樣的和不認得的都不發請求
});

test("retry and refresh reload and put the focus back", async () => {
  const s = page(serve());
  s.target("[data-act=retry]");
  s.target("#controls [data-act=refresh]");
  await s.P.load();
  const press = (act) => s.P.onClick({ target: { closest: () => ({ dataset: { act } }) } });
  await press("refresh");
  assert.ok(s.focused.includes("#controls [data-act=refresh]"));
  const n = s.calls.length;
  await press("retry");
  assert.equal(s.calls.length, n + 3);
});

/* ---------- 頁面 ---------- */
test("every page with a nav links to the usage page right before settings", () => {
  for (const f of ["today.html", "entities.html", "settings.html", "theme.html", "usage.html"]) {
    const html = fs.readFileSync(path.join(WEB, f), "utf8");
    assert.match(html, /<a href="\/usage"[^>]*>用量<\/a><a href="\/settings"/, f);
  }
  const usage = fs.readFileSync(path.join(WEB, "usage.html"), "utf8");
  assert.match(usage, /href="\/usage" aria-current="page"/);
  assert.ok(usage.indexOf("quota-guard.js") > usage.indexOf("common/util.js"));
  assert.ok(usage.includes("/web/js/usage/app.js") && usage.includes("/web/css/usage-page.css"));
});
