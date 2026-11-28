/* Ticket 68：每頁右上角的「背景工作暫停」、手動問 AI 前的提醒、設定頁的額度保護欄位。假的 DOM 和計時器。 */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const t = (s, values = {}) => s.replace(/\{(\w+)\}/g, (m, key) => values[key] ?? m);
const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

function el(tag) {
  return { tagName: tag, children: [], hidden: false, textContent: "", title: "", className: "", href: "",
    appendChild(c) { this.children.push(c); return c; }, insertBefore(c) { this.children.unshift(c); return c; },
    querySelector() { return null; } };
}

/* responses：每次 GET /api/ai/guard 依序回的東西（Error = 失敗）。 */
function setup(responses, opts = {}) {
  const bar = el("header");
  const docListeners = {}, winListeners = {};
  const timers = new Map();
  let nextId = 1;
  const calls = [];
  const toasts = [];
  const document = {
    readyState: "complete", hidden: !!opts.hidden,
    querySelector: (sel) => (sel.includes("header") ? bar : null),
    createElement: el,
    addEventListener(type, fn) { (docListeners[type] = docListeners[type] || []).push(fn); },
  };
  const PR = {
    t, esc, toast: (html) => toasts.push(html),
    api: async (url) => { calls.push(url); const r = responses.shift(); if (r instanceof Error || r === undefined) throw r || new Error("down"); return r; },
  };
  const window = { PR, addEventListener(type, fn) { (winListeners[type] = winListeners[type] || []).push(fn); } };
  const ctx = {
    window, document, PR,
    setTimeout: (fn, ms) => { const id = nextId++; timers.set(id, { fn, ms }); return id; },
    clearTimeout: (id) => { timers.delete(id); },
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../easyread/web/js/common/quota-guard.js"), "utf8"), ctx);
  const flush = () => new Promise((r) => setImmediate(r));
  const fire = async () => {  // 跑目前排著的那一個計時器
    const [id, tm] = [...timers.entries()][0] || [];
    if (!tm) return null;
    timers.delete(id);
    tm.fn();
    await flush();
    return tm.ms;
  };
  const emit = (target, type, e = {}) => ((target === "doc" ? docListeners : winListeners)[type] || []).forEach((fn) => fn(e));
  return { PR, bar, timers, calls, toasts, flush, fire, emit, document };
}

const paused = (reason, extra = {}) => Object.assign({
  settings: { background_subscription: true, threshold: 70, on_exceed: "wait", api_monthly_usd: 15 },
  quota: { used: 0.74, over: reason === "quota", until: 1800000000, at: Date.now() / 1000 - 60 },
  api: { spent_usd: 1, cap_usd: 15, reached: reason === "api_cap", month: "2026-11" },
  background: { paused: !!reason, reason: reason || null, until: null },
}, extra);

test("the header shows 'background paused' while paused and the 5-hour quota otherwise; both go to the usage page", async () => {
  const s = setup([paused("quota"), paused(null)]);
  await s.flush();
  assert.equal(s.calls.length, 1);
  const badge = s.bar.children[0];
  assert.equal(badge.textContent, "背景工作暫停 · Claude 5h 74%");
  assert.equal(badge.href, "/usage");
  assert.equal(badge.className, "quota-paused");
  assert.equal(badge.hidden, false);
  assert.ok(badge.title.includes("門檻"));
  assert.equal(await s.fire(), 60000);
  assert.equal(badge.textContent, "Claude 5h 74%");
  assert.equal(badge.href, "/usage");
  assert.equal(badge.className, "quota-paused calm");  // 額度正常：不用紅字
  assert.equal(badge.hidden, false);
  assert.ok(badge.title.includes("整個帳號"));
  assert.equal(s.bar.children.length, 1);  // 不重複加
});

test("the quota badge is hidden without a usable number or after the reset time", async () => {
  const none = setup([paused(null, { quota: { used: null, over: false, until: null } })]);
  await none.flush();
  assert.equal(none.bar.children.length, 0);  // 還沒有額度數字：不顯示
  const past = setup([paused(null, { quota: { used: 0.5, resets_at: Date.now() / 1000 - 10, at: Date.now() / 1000 - 60, over: false, until: null } })]);
  await past.flush();
  assert.equal(past.bar.children.length, 0);  // 過了重置時間：當作已經重置
  // 記下超過 5 小時的數字一定已經重置（跟後端一樣取早的），沒有記下時間的判斷不了多舊：都不顯示
  const old = setup([paused(null, { quota: { used: 0.5, resets_at: Date.now() / 1000 + 600, at: Date.now() / 1000 - 5 * 3600 - 1, over: false, until: null } })]);
  await old.flush();
  assert.equal(old.bar.children.length, 0);
  const noAt = setup([paused(null, { quota: { used: 0.5, resets_at: Date.now() / 1000 + 600, over: false, until: null } })]);
  await noAt.flush();
  assert.equal(noAt.bar.children.length, 0);
  const live = setup([paused(null, { quota: { used: 0.5, resets_at: Date.now() / 1000 + 600, at: Date.now() / 1000 - 60, over: false, until: null } }), paused(null, { quota: { used: null } })]);
  await live.flush();
  assert.equal(live.bar.children[0].textContent, "Claude 5h 50%");
  assert.equal(live.bar.children[0].hidden, false);
  await live.fire();
  assert.equal(live.bar.children[0].hidden, true);  // 後來沒有數字了：藏起來
  assert.equal(live.calls.length, 2);  // 同一個輪詢，沒有另開
});

test("each reason has its own label", async () => {
  for (const [reason, label] of [["api_cap", "背景工作暫停 · API 到上限"], ["no_api", "背景工作暫停 · 沒有 API key"]]) {
    const s = setup([paused(reason)]);
    await s.flush();
    assert.equal(s.bar.children[0].textContent, label);
  }
});

test("failures back off and stop growing at the cap", async () => {
  const s = setup(Array.from({ length: 12 }, () => new Error("down")));
  await s.flush();
  const delays = [];
  for (let i = 0; i < 10; i++) delays.push(await s.fire());
  assert.deepEqual(delays.slice(0, 4), [120000, 240000, 480000, 600000]);
  assert.ok(delays.every((d) => d <= 600000));
  assert.equal(s.PR.quotaGuard._state().delay, 600000);
  assert.equal(s.timers.size, 1);  // 一直只有一個計時器
});

test("leaving the page clears the timer and stops polling; bfcache restore resumes", async () => {
  const s = setup([paused(null), paused(null)]);
  await s.flush();
  assert.equal(s.timers.size, 1);
  s.emit("win", "pagehide");
  assert.equal(s.timers.size, 0);
  await s.PR.quotaGuard.poll();
  assert.equal(s.calls.length, 1);  // 停了就不再問
  s.emit("win", "pageshow", { persisted: true });
  await s.flush();
  assert.equal(s.calls.length, 2);
  assert.equal(s.timers.size, 1);
});

test("a hidden page does not poll until it is visible again", async () => {
  const s = setup([paused(null)], { hidden: true });
  await s.flush();
  assert.equal(s.calls.length, 0);
  assert.equal(s.timers.size, 0);
  s.document.hidden = false;
  s.emit("doc", "visibilitychange");
  await s.flush();
  assert.equal(s.calls.length, 1);
  s.document.hidden = true;
  s.emit("doc", "visibilitychange");
  assert.equal(s.timers.size, 0);
});

test("only one request at a time", async () => {
  let release;
  const s = setup([]);
  await s.flush();  // 載入時的那一次（失敗）先跑完
  s.PR.api = () => new Promise((r) => { release = r; });
  s.timers.clear();
  const first = s.PR.quotaGuard.poll();
  await s.PR.quotaGuard.poll();  // 前一個還沒回來：不再發
  release(paused(null));
  await first;
  assert.equal(s.timers.size, 1);
});

test("manual AI is reminded once per pause, and still sent", async () => {
  const s = setup([paused("quota")]);
  await s.flush();
  assert.equal(s.PR.quotaGuard.remind(), true);
  assert.equal(s.toasts[0], esc("提醒：Claude Code 5 小時額度已用 74%，超過你設的 70%。這次照樣送出。"));
  assert.equal(s.PR.quotaGuard.remind(), false);  // 同一段只提醒一次
  const cap = setup([paused("api_cap")]);
  await cap.flush();
  assert.equal(cap.PR.quotaGuard.remind(), true);
  assert.ok(cap.toasts[0].includes("API"));
  const ok = setup([paused(null)]);
  await ok.flush();
  assert.equal(ok.PR.quotaGuard.remind(), false);
  assert.equal(ok.toasts.length, 0);
});

test("the reminder only talks about the engine being used, when that is known", async () => {
  const both = paused("quota", { api: { spent_usd: 15, cap_usd: 15, reached: true, month: "2026-11" } });
  let s = setup([both]);
  await s.flush();
  assert.equal(s.PR.quotaGuard.remind("api"), true);
  assert.ok(s.toasts[0].includes("API") && !s.toasts[0].includes("Claude Code"));
  s = setup([both]);
  await s.flush();
  assert.equal(s.PR.quotaGuard.remind("subscription"), true);
  assert.ok(s.toasts[0].includes("Claude Code"));
  s = setup([paused("quota")]);
  await s.flush();
  assert.equal(s.PR.quotaGuard.remind("api"), false);  // 用 API 時訂閱額度超過不用提醒
});

test("leaving the page while a request is running does not schedule another poll", async () => {
  let release;
  const s = setup([]);
  await s.flush();
  s.PR.api = () => new Promise((r) => { release = r; });
  s.timers.clear();
  const running = s.PR.quotaGuard.poll();
  s.emit("win", "pagehide");
  release(paused(null));
  await running;
  await s.flush();
  assert.equal(s.timers.size, 0);
  assert.equal(s.PR.quotaGuard._state().busy, false);
});

test("every manual AI entry in the reader reminds before sending", () => {
  // 問 AI（論文和文章共用，筆記卡片的「點評」也走這裡）和筆記幫手（點評、幫我改、起草稿）
  // 智慧標註、心智圖（側欄產生、匯出時補產生）、讓模型重譯這段也是使用者按了就呼叫模型
  // 按了才開始的翻譯、整理在下一個測試
  for (const [file, call] of [["chat.js", 'fetch("/api/p/" + PR.pid + "/chat"'], ["notehelp.js", 'fetch("/api/p/" + PR.pid + "/notehelp"'],
    ["notespanel.js", '"/smart-annotate"'], ["planner.js", '"/mindmap/tasks"'], ["export.js", 'PR.api(endpoint, { method: "POST"'],
    ["actions.js", 'PR.ask("retranslate"']]) {
    const src = fs.readFileSync(path.join(__dirname, "../easyread/web/js/reader", file), "utf8");
    const remind = src.indexOf("PR.quotaGuard.remind()");
    assert.ok(remind > 0, file);
    assert.ok(remind < src.indexOf(call), file);
  }
  const margin = fs.readFileSync(path.join(__dirname, "../easyread/web/js/reader/margin.js"), "utf8");
  assert.match(margin, /PR\.askModel = function[\s\S]*?PR\.chatAsk\(/);  // 筆記卡片的點評經過 chat.js
});

test("every translate button reminds before it starts the job", () => {
  // 使用者按了才開始的翻譯、整理照跑，送出前提醒；匯入後自動開始的才受額度保護暫停（ticket 68）
  const read = (f) => fs.readFileSync(path.join(__dirname, "../easyread/web/js", f), "utf8");
  const before = (src, call, file) => {
    const at = src.indexOf(call);
    assert.ok(at > 0, file + " " + call);
    const r = src.lastIndexOf("remind", at);
    assert.ok(r > 0 && at - r < 400, file + " " + call);
  };
  const actions = read("reader/actions.js");
  assert.match(actions, /\["retry-failed", "translate-en", "read-rest", "translate-rest"\]\.includes\(t\.dataset\.t\)\) if \(PR\.quotaGuard\) PR\.quotaGuard\.remind\(\)/);
  before(read("common/page-cap.js"), 'await PR.api("/api/p/" + id + (action === "skip"', "page-cap.js");
  before(read("library/batch.js"), "for (const i of todo)", "batch.js");
  before(read("library/pick-pages.js"), "body: { pages: spec }", "pick-pages.js");
  const detail = read("library/detail.js");
  assert.match(detail, /function remindAi\(\) \{ if \(PR\.quotaGuard\) PR\.quotaGuard\.remind\(\);/);
  const calls = detail.split('"/translate"').length - 1;
  const reminded = (detail.match(/remindAi\(\);(\s|\n)*(try \{\s*)?(await )?PR\.api\("\/api\/p\/" \+ i\.id \+ "\/translate"/g) || []).length;
  assert.equal(reminded, calls);
});

test("a waiting auto-translation says why and whether it will continue by itself", async () => {
  const s = setup([]);
  await s.flush();
  const g = s.PR.quotaGuard;
  const sub = { state: "waiting", wait: { reason: "subscription", until: null } };
  assert.equal(g.waitLabel(sub), "等你按翻譯");
  assert.match(g.waitText(sub), /Claude Code、Codex 訂閱時，匯入後不會自動翻譯/);
  assert.equal(g.waitCanWait(sub), false);
  assert.equal(g.waitLabel({ wait: { reason: "api_off" } }), "等你按翻譯");
  const until = new Date(2026, 10, 28, 16, 40).getTime() / 1000;
  const quota = { state: "waiting", wait: { reason: "quota", until } };
  assert.equal(g.waitLabel(quota), "等額度重置");
  assert.match(g.waitText(quota), /16:40 額度重置後自動接著做/);
  assert.equal(g.waitCanWait(quota), true);
  assert.match(g.waitText({ wait: { reason: "quota", until: null } }), /先等，額度重置後自動接著做/);  // 不知道重置時間
  const cap = { read: true, wait: { reason: "api_cap", until: null } };
  assert.equal(g.waitLabel(cap), "API 到上限");
  assert.match(g.waitText(cap), /匯入後的自動整理先等，下個月或調高上限後/);
  assert.equal(g.waitLabel({ wait: {} }), "等額度重置");  // 看不懂的原因：當作等額度
});

test("a job left waiting after auto-translate was turned off waits for the user (#96)", async () => {
  const s = setup([]);
  await s.flush();
  const g = s.PR.quotaGuard;
  const job = { wait: { reason: "auto_off", until: null } };
  assert.equal(g.waitLabel(job), "等你按翻譯");
  assert.match(g.waitText(job), /你關掉了「匯入後自動翻譯」，這篇不會自動翻譯/);
  assert.equal(g.waitCanWait(job), false);
});

test("library and reader show the waiting state with a way to start now or drop it", () => {
  const read = (f) => fs.readFileSync(path.join(__dirname, "../easyread/web/js", f), "utf8");
  const app = read("library/app.js");
  assert.match(app, /j\.state === "waiting" && PR\.quotaGuard\) return '<span class="stat wait"[^\n]*waitText\(j\)[^\n]*waitLabel\(j\)/);
  const detail = read("library/detail.js");
  assert.match(detail, /const waiting = j\.state === "waiting" && PR\.quotaGuard;/);
  assert.match(detail, /waiting \? '<button class="btn sm line" data-d="cancel">' \+ PR\.t\("不用了"\)/);
  assert.match(detail, /data-d="' \+ \(read \? "read-rest" : "translate"\) \+ '">/);  // 「開始翻譯」就是現在翻譯（手動）
  assert.match(read("reader/panels.js"), /j\.state === "waiting" && PR\.quotaGuard\) \{ el\.textContent = PR\.quotaGuard\.waitLabel\(j\)/);
  const render = read("reader/render.js");
  assert.match(render, /job\.state === "waiting" && PR\.quotaGuard \? '<span class="wait">'/);
  assert.equal((render.match(/先放原页。", \{ n: miss\.length \}\) \+ wait \+/g) || []).length, 2);
});

test("every page with a header loads the indicator", () => {
  for (const page of ["library.html", "reader.html", "entities.html", "settings.html", "today.html", "theme.html", "usage.html"]) {
    const html = fs.readFileSync(path.join(__dirname, "../easyread/web", page), "utf8");
    assert.ok(html.includes("/web/js/common/quota-guard.js"), page);
    assert.ok(html.includes("/web/css/quota-guard.css"), page);
    assert.ok(html.indexOf("quota-guard.js") > html.indexOf("common/util.js"), page);
  }
});

/* ---------- 設定頁 ---------- */
function settings() {
  const PR = { lang: "zh-TW", t, esc, $: () => null };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../easyread/web/js/settings/app.js"), "utf8"),
    { window: { PR }, document: { addEventListener() {} } });
  return PR.settings;
}

test("settings show the guard fields, the default and a paused banner", () => {
  const P = settings();
  const tx = { guardTitle: "額度保護" };
  assert.equal(P.guardHtml({}, tx), "");
  const g = paused("no_api", { settings: { background_subscription: false, threshold: 70, on_exceed: "wait", api_monthly_usd: 15 } });
  const html = P.viewHtml({ status: "ready", data: { any_ai: true, guard: g, tasks: {}, choices: [], detected: {}, openai: [] } }, Date.UTC(2026, 10, 15));
  assert.match(html, /data-guard="background_subscription"(?! checked)/);
  assert.match(html, /id="f-guard-threshold"[^>]*value="70"/);
  assert.match(html, /<option value="wait" selected>/);
  assert.match(html, /id="f-guard-cap"[^>]*value="15"/);
  assert.ok(html.includes("背景工作暫停中：背景不用訂閱"));
  const q = P.viewHtml({ status: "ready", data: { any_ai: true, guard: paused("quota"), tasks: {}, choices: [], detected: {}, openai: [] } });
  assert.ok(q.includes("Claude Code 5 小時額度到 74%"));
  assert.match(q, /data-guard="background_subscription" checked/);
});

test("guard fields turn into request bodies; bad numbers are not sent", () => {
  const S = settings();
  const P = { guardBody: (el) => JSON.parse(JSON.stringify(S.guardBody(el))) };  // 換成這個 realm 的物件
  assert.deepEqual(P.guardBody({ dataset: { guard: "background_subscription" }, checked: true }), { background_subscription: true });
  assert.deepEqual(P.guardBody({ dataset: { guard: "on_exceed" }, value: "api" }), { on_exceed: "api" });
  assert.deepEqual(P.guardBody({ dataset: { guard: "threshold" }, value: "75" }), { threshold: 75 });
  assert.deepEqual(P.guardBody({ dataset: { guard: "api_monthly_usd" }, value: "20.5" }), { api_monthly_usd: 20.5 });
  assert.equal(P.guardBody({ dataset: { guard: "threshold" }, value: "" }), null);
  assert.equal(P.guardBody({ dataset: { guard: "api_monthly_usd" }, value: "abc" }), null);
});
