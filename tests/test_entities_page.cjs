/* Ticket 13：追蹤對象頁的畫面邏輯（送出內容、錯誤欄位對應、各狀態、跳脫）。 */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

function load() {
  const PR = {
    lang: "zh-TW",
    t: (s, values = {}) => s.replace(/\{(\w+)\}/g, (m, key) => values[key] ?? m),
    esc: (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"),
    $: () => null,
  };
  const context = { window: { PR }, document: { addEventListener() {} } };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../easyread/web/js/entities/app.js"), "utf8"), context);
  return PR.entities;
}
const E = load();
const same = (a, b) => assert.equal(JSON.stringify(a), JSON.stringify(b));
const COMPANY = { id: "E-" + "a".repeat(32), type: "company", name: "範例晶圓廠", aliases: ["SFAB"], listings: [{ market: "TW", symbol: "9901.TW" }],
                  primary: "9901.TW", benchmark: "發行量加權股價報酬指數", benchmark_default: true, industry_index: null,
                  archived: false, recent_mentions: 2, mentions: [] };

test("payload skips blank ticker rows and remembers which row each sent ticker came from", () => {
  const d = E.blankDraft();
  d.name = "  範例 GPU 廠 ";
  d.listings = [{ market: "TW", symbol: "" }, { market: "US", symbol: " sgpu " }, { market: "TW", symbol: "9901" }];
  const { body, kept } = E.payload(d);
  same(kept, [1, 2]);
  same(body.listings, [{ market: "US", symbol: "sgpu" }, { market: "TW", symbol: "9901" }]);
  assert.equal(body.name, "範例 GPU 廠");
  assert.equal(body.benchmark, null);  // 空白 = 用預設
  assert.equal(E.fieldKey("listings.0.symbol", kept), "listings.1.symbol");
  assert.equal(E.fieldKey("listings.1.market", kept), "listings.2.market");
  assert.equal(E.fieldKey("listings.9.symbol", kept), "listings");
});

test("non-company types send no tickers or indices", () => {
  const d = Object.assign(E.blankDraft(), { type: "theme", name: "AI 伺服器", benchmark: "S&P 500", industry_index: "SOX" });
  d.listings = [{ market: "US", symbol: "NVDA" }];
  const { body } = E.payload(d);
  same(body.listings, []);
  assert.equal(body.benchmark, null);
  assert.equal(body.industry_index, null);
});

test("server field names map to the right place on the form", () => {
  assert.equal(E.fieldKey("aliases.3"), "aliases");
  assert.equal(E.fieldKey("listings"), "listings");
  assert.equal(E.fieldKey("name"), "name");
  assert.equal(E.fieldKey("whatever"), "form");
  assert.equal(E.fieldKey(undefined), "form");
});

test("benchmark choices follow the primary ticker's market and keep a custom value", () => {
  const d = E.toDraft(COMPANY);
  assert.equal(d.benchmark, "");  // 預設存成空白，不寫死指數名稱
  const opts = E.benchmarkOptions(d);
  assert.match(opts[0][1], /發行量加權股價報酬指數/);
  assert.ok(opts.some(([, label]) => /不含息/.test(label)));
  d.listings = [{ market: "US", symbol: "SGPU" }];
  assert.match(E.benchmarkOptions(d)[0][1], /S&P 500 Total Return/);
  d.benchmark = "自訂指數";
  assert.ok(E.benchmarkOptions(d).some(([v]) => v === "自訂指數"));
  d.listings = [];
  assert.equal(E.benchmarkOptions(d)[0][0], "");
});

test("aliases are trimmed, deduplicated against the name and each other, and capped", () => {
  const d = Object.assign(E.blankDraft(), { name: "SFAB Corp" });
  assert.equal(E.addAlias(d, "  晶圓   一哥 "), true);
  same(d.aliases, ["晶圓 一哥"]);
  assert.equal(E.addAlias(d, "晶圓 一哥"), false);
  assert.equal(E.addAlias(d, "sfab corp"), false);
  assert.equal(E.addAlias(d, "   "), false);
  for (let i = 0; i < 30; i++) E.addAlias(d, "a" + i);
  assert.equal(d.aliases.length, 20);  // MAX_ALIASES
});

test("user text in the list and drawer is escaped", () => {
  const evil = Object.assign({}, COMPANY, { name: '<img src=x onerror="alert(1)">', aliases: ["<b>x</b>"] });
  const row = E.rowHtml(evil, false);
  assert.ok(!row.includes("<img"));
  assert.ok(!row.includes("<b>x"));
  const drawer = E.drawerHtml(E.toDraft(evil), {}, [{ id: "i1", title: "<script>" }], false);
  assert.ok(!drawer.includes("<img"));
  assert.ok(!drawer.includes("<script>"));
});

test("drawer marks the field the server rejected and lists links with their source", () => {
  const d = E.toDraft(Object.assign({}, COMPANY, { mentions: [{ item_id: "i1", source: "ai" }, { item_id: "i2", source: "manual" }] }));
  const html = E.drawerHtml(d, { "listings.0.symbol": "台股代號格式不對" }, [{ id: "i1", title: "法說會" }, { id: "i3", title: "營收" }], false);
  assert.match(html, /class="input num invalid" data-listing="0"/);
  assert.match(html, /role="alert">台股代號格式不對/);
  assert.match(html, /法說會<\/span><span class="chip ai">AI 連結/);
  assert.match(html, /chip mine">手動/);
  assert.match(html, /<option value="i3">營收<\/option>/);  // 還沒連的才列進選單
  assert.ok(!html.includes('<option value="i1">'));
  assert.match(html, /data-act="archive"/);
  assert.match(html, /封存不會刪掉帳本裡跟它有關的判斷/);
  const fresh = E.drawerHtml(E.blankDraft(), {}, [], false);
  assert.ok(!fresh.includes('data-act="archive"'));  // 新增時沒有封存、沒有連結
  assert.ok(!fresh.includes("f-link"));
});

test("the manual-link menu is capped", () => {
  const d = E.toDraft(COMPANY);
  const items = Array.from({ length: 250 }, (_, i) => ({ id: "item-" + i, title: "資料 " + i }));
  const html = E.drawerHtml(d, {}, items, false);
  assert.equal((html.match(/<option value="item-/g) || []).length, 200);  // MAX_CHOICES
});

test("user content is kept away from the DOM translator", () => {
  const d = E.toDraft(Object.assign({}, COMPANY, { name: "事件", aliases: ["公司"], mentions: [{ item_id: "i1", source: "ai" }] }));
  const row = E.rowHtml(Object.assign({}, COMPANY, { name: "事件", aliases: ["公司"] }), false);
  assert.match(row, /class="name" data-no-i18n data-open=/);
  assert.match(row, /class="sub" data-no-i18n>/);
  const html = E.drawerHtml(d, {}, [{ id: "i1", title: "題材" }, { id: "i2", title: "x" }], false);
  assert.match(html, /<h2 data-no-i18n>/);
  assert.match(html, /class="chip" data-no-i18n>公司/);
  assert.match(html, /class="mt" data-no-i18n>題材/);
  assert.match(html, /id="f-link" data-no-i18n/);
});

test("the form is disabled while a request is running and keeps a half-typed alias", () => {
  const d = E.toDraft(COMPANY);
  d.aliasInput = "晶圓 <一哥>";
  assert.match(E.drawerHtml(d, {}, [], true), /<fieldset class="plain" disabled>/);
  const idle = E.drawerHtml(d, {}, [], false);
  assert.match(idle, /<fieldset class="plain">/);
  assert.match(idle, /id="f-alias"[^>]*value="晶圓 &lt;一哥&gt;"/);
});

test("theme entities show no ticker or benchmark fields", () => {
  const html = E.drawerHtml(Object.assign(E.blankDraft(), { type: "theme" }), {}, [], false);
  assert.ok(!html.includes("data-listing"));
  assert.ok(!html.includes("f-bench"));
});

test("page states: loading, error, empty and the list with type counts", () => {
  const base = { list: [], counts: {}, total: 0, archived: 0, filter: "", showArchived: false, draft: null, errors: {}, busy: false, items: [] };
  assert.match(E.viewHtml(Object.assign({}, base, { status: "loading" })), /class="skel"/);
  assert.match(E.viewHtml(Object.assign({}, base, { status: "error" })), /data-act="retry"/);
  assert.match(E.viewHtml(Object.assign({}, base, { status: "ready" })), /還沒有追蹤對象.*data-act="new"/s);
  const theme = Object.assign({}, COMPANY, { id: "E-" + "b".repeat(32), type: "theme", name: "AI 伺服器", listings: [], primary: null, benchmark: null });
  const ready = Object.assign({}, base, { status: "ready", list: [COMPANY, theme], counts: { company: 1, theme: 1 }, total: 2, archived: 1 });
  const html = E.viewHtml(ready);
  assert.match(html, /全部 2/);
  assert.match(html, /data-type="company" aria-pressed="false">公司 1/);
  assert.match(html, /已封存 1/);
  assert.match(html, /2 則/);
  const filtered = E.viewHtml(Object.assign({}, ready, { filter: "theme" }));
  assert.ok(!filtered.includes("範例晶圓廠"));
  assert.ok(filtered.includes("AI 伺服器"));
});
