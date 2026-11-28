/* Ticket 15：今日新聞頁的畫面邏輯（查詢參數、篩選、各狀態、跳脫、上限），和載入流程（過期回應、錯誤、逾時、焦點）。 */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

function load(extra = {}) {
  const PR = Object.assign({
    lang: "zh-TW",
    t: (s, values = {}) => s.replace(/\{(\w+)\}/g, (m, key) => values[key] ?? m),
    esc: (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"),
    $: () => null,
  }, extra);
  const context = { window: { PR }, document: { addEventListener() {} }, setTimeout, clearTimeout, AbortController };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../easyread/web/js/today/app.js"), "utf8"), context);
  return PR.today;
}
const X = load();
const base = () => ({ status: "ready", levels: ["high", "mid", "none"], entity: "", limit: 50, items: [], counts: {}, entities: [], total: 0, more: false, truncated: false });
const ITEM = {
  id: "abc123", title: "<b>範例</b> 新聞", publisher: "範例通訊社", at: "2026-11-12T01:00:00+00:00", state: "done", importance: "high",
  preview_only: false, stale: false, retrospective: false,
  top: { kind: "thesis", id: "T-1", relation: "strengthens", importance: "high", confidence: "high", reason: "營收成長 <script>" },
  entities: [{ id: "E-1", name: "範例科技", relation: "bull", importance: "high", noise_kind: null, confidence: "mid", reason: "年增 30%" }],
  theses: [{ id: "T-1", theme_id: "E-2", theme_name: "AI 伺服器", claim: "需求兩年向上", relation: "strengthens", grade: "B", importance: "high",
             noise_kind: null, confidence: "high", reason: "公司公告營收成長" },
           { id: "T-2", theme_id: "E-2", theme_name: "AI 伺服器", claim: "資本支出下修", relation: "related_no_change", grade: "C", importance: "noise",
             noise_kind: "short_term", confidence: "low", reason: "只是短期波動" }],
};

test("params keep the level order, cap the limit and only send an entity when chosen", () => {
  const same = (a, b) => assert.equal(JSON.stringify(a), JSON.stringify(b));
  same(X.params(base()), { importance: "high,mid,none", limit: 50 });
  const s = Object.assign(base(), { levels: ["noise", "high"], entity: "E-" + "a".repeat(32), limit: 9999 });
  same(X.params(s), { importance: "high,noise", limit: 200, entity: "E-" + "a".repeat(32) });
  same(X.params(Object.assign(base(), { levels: [] })), { importance: "high,mid,none", limit: 50 });
});

test("toggling a level ignores unknown values and nextLimit stops at the maximum", () => {
  const same = (a, b) => assert.equal(JSON.stringify(a), JSON.stringify(b));
  same(X.toggleLevel(["high"], "low"), ["high", "low"]);
  same(X.toggleLevel(["high", "low"], "high"), ["low"]);
  same(X.toggleLevel(["high"], "bogus"), ["high"]);
  assert.equal(X.nextLimit(50), 100);
  assert.equal(X.nextLimit(180), 200);
  assert.equal(X.nextLimit(200), 200);
});

test("a row links to the reader, shows the importance and the AI reason, and escapes text", () => {
  const html = X.rowHtml(ITEM);
  assert.match(html, /href="\/read\/abc123"/);
  assert.match(html, /class="imp h">高</);
  assert.match(html, /營收成長 &lt;script&gt;/);
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /&lt;b&gt;範例&lt;\/b&gt; 新聞/);
  assert.equal(X.readerHref("a/b c"), "/read/a%2Fb%20c");
});

test("detail lists the judgment against every thesis, then every entity", () => {
  const html = X.detailHtml(ITEM);
  assert.match(html, /<details/);
  assert.match(html, /需求兩年向上/);
  assert.match(html, /資本支出下修/);
  assert.match(html, /有關但不改變/);
  assert.match(html, /短期波動/);
  assert.match(html, /題材：AI 伺服器/);
  assert.match(html, /相對於每個追蹤對象的判斷/);
  assert.match(html, /範例科技/);
  assert.equal(X.detailHtml({ theses: [], entities: [] }), "");
});

test("unclassified rows say why there is no AI view and have no detail", () => {
  const html = X.rowHtml({ id: "p1", title: "等待中", at: "2026-11-12T01:00:00+00:00", state: "pending", importance: "none", top: null, entities: [], theses: [] });
  assert.match(html, /等待 AI 分類/);
  assert.match(html, /class="imp u">未分類</);
  assert.doesNotMatch(html, /<details/);
  assert.match(X.rowHtml({ id: "f1", title: "x", at: "", state: "failed", importance: "none", top: null }), /分類失敗/);
});

test("view states: loading, error with retry, empty day, empty filter, list", () => {
  assert.match(X.viewHtml(Object.assign(base(), { status: "loading" })), /aria-busy/);
  const error = X.viewHtml(Object.assign(base(), { status: "error", error: "network" }));
  assert.match(error, /data-act="retry"/);
  assert.match(error, /data-act="reset"/);
  assert.match(error, /連不上 NewsRead 本機服務/);
  assert.match(error, /data-level="high"/);  // 錯誤時篩選還在，可以改條件
  assert.match(X.viewHtml(Object.assign(base(), { status: "error", error: "toString" })), /本機資料庫暫時讀不到/);
  const empty = X.viewHtml(base());
  assert.match(empty, /今天還沒有資料/);
  assert.match(empty, /href="\/entities"/);
  assert.match(empty, /data-act="paste"/);
  const filtered = X.viewHtml(Object.assign(base(), { counts: { low: 3 } }));  // 今天有資料，只是這個篩選沒有
  assert.match(filtered, /這個篩選沒有資料/);
  const list = X.viewHtml(Object.assign(base(), { items: [ITEM], total: 1, counts: { high: 1 }, entities: [{ id: "E-1", name: "範例科技", count: 1 }] }));
  assert.match(list, /顯示 1 \/ 1 則/);
  assert.match(list, /data-level="high" checked/);
  assert.match(list, /data-level="low">/);
  assert.match(list, /data-entity="E-1"/);
  assert.match(list, /揭露紀錄/);
  assert.match(list, /aria-label="篩選"/);
});

test("rows are grouped by importance and noise is collapsed", () => {
  const noise = Object.assign({}, ITEM, { id: "n1", importance: "noise" });
  const mid = Object.assign({}, ITEM, { id: "m1", importance: "mid" });
  const html = X.viewHtml(Object.assign(base(), { items: [ITEM, mid, noise], total: 3, counts: { high: 1, mid: 4, noise: 1 } }));
  assert.ok(html.indexOf("重要") < html.indexOf("值得看") && html.indexOf("值得看") < html.indexOf("AI 判為雜訊"));
  assert.match(html, /共 4 則 · 顯示 1/);
  assert.match(html, /<details class="group noise-group" data-id="group:noise"><summary/);
  assert.match(html, /data-i="2"/);
});

test("unknown publish time is labelled as import time and odd levels fall back safely", () => {
  assert.match(X.rowHtml(Object.assign({}, ITEM, { time_known: false })), /\d\d:\d\d 匯入/);
  assert.doesNotMatch(X.rowHtml(Object.assign({}, ITEM, { time_known: true })), /匯入/);
  assert.match(X.rowHtml(Object.assign({}, ITEM, { importance: "constructor" })), /class="imp u"/);
});

test("error kinds are fixed codes, never the raw message", () => {
  assert.equal(X.errorKind(new Error("x"), true), "timeout");
  assert.equal(X.errorKind(new Error("offline")), "network");
  assert.equal(X.errorKind(Object.assign(new Error("bad"), { status: 400 })), "bad");
  assert.equal(X.errorKind(Object.assign(new Error("boom"), { status: 500 })), "server");
  assert.equal(X.errorKind(Object.assign(new Error("bad token"), { status: 403 })), "expired");
});

/* ---------- 載入流程：假的 #view 和 PR.api ---------- */
function page(api, opts = {}) {
  const focused = [];
  const el = (sel, data) => ({ dataset: data || {}, focus() { focused.push(sel); } });
  const missing = opts.missing || (() => false);
  const view = { innerHTML: "", attrs: {}, setAttribute(k, v) { this.attrs[k] = v; },
                 querySelector: (sel) => (missing(sel) ? null : (opts.el || el)(sel)),
                 querySelectorAll: (sel) => (sel === "input[data-entity]" ? [el("entity:E-1", { entity: "E-1" })] : (opts.all ? opts.all(sel) : [])) };
  const calls = [];
  const P = load({ $: (sel) => (sel === "#view" ? view : null), api: (p, opts) => { calls.push({ p, opts }); return api(opts, calls.length); } });
  return { P, view, calls, focused };
}
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
const more = { target: { closest: () => ({ dataset: { act: "more" } }) } };

test("loads with POST and drops a stale response", async () => {
  const first = deferred(), second = deferred();
  const { P, calls } = page((opts, n) => (n === 1 ? first.promise : second.promise));
  const a = P.load(true);
  const b = P.onChange({ target: { dataset: { level: "low" } } });
  second.resolve({ items: [{ id: "new" }], counts: {}, entities: [], total: 1 });
  await b;
  first.resolve({ items: [{ id: "old" }], counts: {}, entities: [], total: 1 });
  await a;
  assert.equal(calls[0].p, "/api/today");
  assert.equal(calls[0].opts.method, "POST");
  assert.equal(calls[1].opts.body.importance, "high,mid,none,low");
  assert.deepEqual(P.state.items.map((i) => i.id), ["new"]);
  assert.equal(P.state.busy, false);
});

test("at least one level stays checked", async () => {
  const { P, calls } = page(() => Promise.resolve({ items: [], counts: {}, entities: [] }));
  P.state.levels = ["high"];
  const box = { dataset: { level: "high" }, checked: false };
  await P.onChange({ target: box });
  assert.equal(box.checked, true);
  assert.equal(calls.length, 0);
});

test("focus returns to the changed control and to the first new row after show more", async () => {
  const { P, focused } = page(() => Promise.resolve({ items: [], counts: {}, entities: [{ id: "E-1", name: "範例科技", count: 1 }] }));
  await P.onChange({ target: { dataset: { level: "low" } } });
  assert.equal(focused.at(-1), 'input[data-level="low"]');
  await P.onChange({ target: { dataset: { entity: "E-1" } } });
  assert.equal(focused.at(-1), "entity:E-1");
  P.state.items = [{ id: "a" }, { id: "b" }];
  await P.onClick(more);
  assert.equal(focused.at(-1), '.story[data-i="2"] .t a');
});

test("focus falls back to a control when the new row is missing, and retry keeps focus on retry", async () => {
  let r = page(() => Promise.reject(new Error("offline")), { missing: (sel) => sel.startsWith(".story") || sel === "[data-act=more]" });
  r.P.state.items = [{ id: "a" }];
  await r.P.onClick(more);
  assert.equal(r.focused.at(-1), "[data-act=retry]");
  r = page(() => Promise.reject(new Error("offline")));
  await r.P.onClick({ target: { closest: () => ({ dataset: { act: "retry" } }) } });
  assert.equal(r.focused.at(-1), "[data-act=retry]");
});

test("open detail and the noise group stay open after a re-render, and focus opens a folded group", async () => {
  const fold = { open: false };
  const groups = [{ dataset: { id: "group:noise" }, open: false }, { dataset: { id: "abc" }, open: false }];
  const all = (sel) => (sel === "details[open][data-id]" ? [{ dataset: { id: "group:noise" } }] : sel === "details[data-id]" ? groups : []);
  const target = (sel) => ({ dataset: {}, closest: () => fold, focus() { target.focused = sel; } });
  const { P } = page(() => Promise.resolve({ items: [], counts: {}, entities: [] }), { all, el: target });
  await P.onChange({ target: { dataset: { level: "low" } } });
  assert.equal(groups[0].open, true);
  assert.equal(groups[1].open, false);
  assert.equal(fold.open, true);
  assert.equal(target.focused, 'input[data-level="low"]');
});

test("a timeout while the body is read is an error, not an empty day", async () => {
  const r = page((opts) => new Promise((resolve) => opts.signal.addEventListener("abort", () => resolve({}))));
  r.P.timeoutMs = 20;
  await r.P.load();
  assert.equal(r.P.state.status, "error");
  assert.equal(r.P.state.error, "timeout");
});

test("a chosen entity that drops out of the facets keeps its name", async () => {
  const { P } = page(() => Promise.resolve({ items: [], counts: {}, entities: [] }));
  P.state.entities = [{ id: "E-1", name: "範例科技", count: 3 }];
  await P.onChange({ target: { dataset: { entity: "E-1" } } });
  assert.deepEqual(P.state.entities.map((e) => e.name), ["範例科技"]);
});

test("errors become a fixed kind and the wait is capped by a timeout", async () => {
  let r = page(() => Promise.reject(Object.assign(new Error("secret C:/x"), { status: 400 })));
  await r.P.load();
  assert.equal(r.P.state.error, "bad");
  assert.doesNotMatch(r.view.innerHTML, /secret/);
  r = page((opts) => new Promise((resolve, reject) => opts.signal.addEventListener("abort", () => reject(new Error("aborted")))));
  r.P.timeoutMs = 20;
  await r.P.load();
  assert.equal(r.P.state.status, "error");
  assert.equal(r.P.state.error, "timeout");
  assert.equal(r.P.state.busy, false);
});

test("show more is ignored while a request is running", async () => {
  const pending = deferred();
  const { P, calls } = page(() => pending.promise);
  const first = P.load(true);
  assert.equal(P.state.busy, true);
  P.onClick(more);
  assert.equal(calls.length, 1);
  pending.resolve({ items: [], counts: {}, entities: [] });
  await first;
});

test("the show-more button stops at the maximum and then asks for a narrower filter", () => {
  const some = { items: [ITEM], total: 120, more: true, counts: { high: 120 } };
  assert.match(X.viewHtml(Object.assign(base(), some, { limit: 50 })), /data-act="more"/);
  const capped = X.viewHtml(Object.assign(base(), some, { limit: 200 }));
  assert.doesNotMatch(capped, /data-act="more"/);
  assert.match(capped, /沒顯示的還有 119 則/);
  assert.match(X.viewHtml(Object.assign(base(), some, { truncated: true })), /只讀了最新的一部分，今天有些資料可能沒列出/);
});

test("pending rows and a banner say why triage waits when only a CLI with tools is found (ticket 104)", () => {
  const waiting = { id: "p1", title: "等待中", at: "2026-11-12T01:00:00+00:00", state: "pending", importance: "none", top: null, entities: [], theses: [] };
  const failed = Object.assign({}, waiting, { id: "f1", state: "failed" });
  const block = { reason: "no_tools", engines: ["codex"] };
  const S = Object.assign(base(), { items: [waiting, failed], total: 2, counts: { none: 2 }, pending: 12, triageBlock: block });
  const html = X.viewHtml(S);
  assert.match(html, /<div class="banner warn"><span class="ico">!<\/span><div>有 12 則等著分類，但現在沒有能分類的引擎：Codex CLI 可以閱讀和翻譯，不支援分類。分類要 Claude Code、API key 或本機模型。/);
  assert.match(html, /<a class="btn sm" href="\/settings#models">到設定的 AI 模型<\/a>/);
  assert.match(html, /等待 AI 分類：分類要 Claude Code、API key 或本機模型/);
  assert.match(html, /分類失敗/);  // 只有待分類的換說明
  const both = X.viewHtml(Object.assign({}, S, { triageBlock: { reason: "no_tools", engines: ["codex", "antigravity", "<x>"] } }));
  assert.match(both, /Codex CLI、Antigravity CLI 可以閱讀和翻譯/);  // 不認得的引擎名稱不顯示
  assert.match(X.viewHtml(Object.assign({}, S, { triageBlock: { reason: "no_tools", engines: [] } })), /有 12 則等著分類，但現在沒有能分類的引擎。分類要/);
  for (const quiet of [{ triageBlock: null }, { pending: 0 }, { triageBlock: { reason: "other" } }]) {
    const h = X.viewHtml(Object.assign({}, S, quiet));
    assert.doesNotMatch(h, /等著分類/);
    if (quiet.pending !== 0) assert.match(h, />等待 AI 分類<\/div>/);
  }
  assert.doesNotMatch(X.viewHtml(Object.assign({}, S, { status: "error", error: "network" })), /等著分類/);
  assert.match(X.rowHtml(waiting), />等待 AI 分類<\/div>/);  // 沒給狀態時照舊
});

