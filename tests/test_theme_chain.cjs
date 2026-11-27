/* Ticket 59：題材頁因果鏈清單的畫面邏輯（出處、虛線標示、營收占比 unknown、領漲 / 補漲建議、送出內容、上限、跳脫）。 */
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
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../easyread/web/js/theme/chain.js"), "utf8"), context);
  return PR.themeChain;
}
const C = load();
const same = (a, b) => assert.equal(JSON.stringify(a), JSON.stringify(b));
const E1 = "E-" + "a".repeat(32);
const link = (over = {}) => Object.assign({ index: 0, from: { label: "需求" }, to: { label: "瓶頸" }, relation: "說明", source: { url: "https://example.com/a" },
                                           inferred: false, confirmed: false }, over);
const company = (over = {}) => link(Object.assign({ to: { entity_id: E1, name: "範例電源 A", type: "company" }, revenue_share: "unknown", role: "unknown",
                                                     role_suggestion: "unknown" }, over));
const view = (links, over = {}) => Object.assign({ status: "draft", version: 2, links, unconfirmed: 0, market_data: false }, over);
const render = (v, extra = {}) => { Object.assign(C.state, { status: "ready", view: v, editing: null, entities: [], items: [], note: "" }, extra); return C.viewHtml(C.state); };

test("every link shows its source: a safe url link, an item, or an explicit no-source mark", () => {
  same(C.sourceView({ url: "https://example.com/a" }), { kind: "url", url: "https://example.com/a" });
  same(C.sourceView({ url: "javascript:alert(1)" }), { kind: "none" });  // 不是 http(s) 就不當連結
  same(C.sourceView({ item_id: "item-1" }), { kind: "item", id: "item-1" });
  same(C.sourceView(null), { kind: "none" });
  const html = render(view([link(), link({ index: 1, source: { item_id: "item-9" } }), link({ index: 2, source: null, inferred: true })]));
  assert.match(html, /href="https:\/\/example\.com\/a" title="https:\/\/example\.com\/a" target="_blank" rel="noopener noreferrer"/);
  assert.match(html, /資料 item-9/);
  assert.match(html, /沒有出處/);
});

test("AI inference links are dashed and marked until I confirm them; confirmed ones say so", () => {
  const html = render(view([link({ index: 0, source: null, inferred: true }), link({ index: 1, source: null, inferred: true, confirmed: true }), link({ index: 2 })], { unconfirmed: 1 }));
  const items = html.split("<li").slice(1);
  assert.match(items[0], /class="infer"/);
  assert.match(items[0], /AI 推論/);
  assert.match(items[0], /data-act="confirm" data-i="0"/);
  assert.doesNotMatch(items[1], /class="infer"/);
  assert.match(items[1], /你確認過/);
  assert.doesNotMatch(items[1], /data-act="confirm"/);
  assert.doesNotMatch(items[2], /AI 推論|data-act="confirm"/);
  assert.match(html, /還有 1 個 AI 推論的環節沒確認/);
  assert.equal(C.pending(link({ inferred: true })), true);
  assert.equal(C.pending(link({ inferred: true, confirmed: true })), false);
});

test("revenue share shows 不知道 when unknown, and the value or range with its source otherwise", () => {
  same(C.shareView("unknown"), { kind: "unknown" });
  same(C.shareView(undefined), { kind: "unknown" });
  same(C.shareView({ range: [8, 12], source: { url: "https://example.com/r" } }), { kind: "range", text: "8–12%", source: { kind: "url", url: "https://example.com/r" } });
  assert.equal(C.shareView({ value: 40, source: { item_id: "i" } }).text, "40%");
  assert.match(render(view([company()])), /營收占比：<b>不知道<\/b>/);
  const html = render(view([company({ revenue_share: { range: [8, 12], source: { url: "https://example.com/r" } } })]));
  assert.match(html, /<b>8–12%<\/b>/);
  assert.match(html, /href="https:\/\/example\.com\/r"/);
  assert.doesNotMatch(render(view([link()])), /營收占比/);  // 不是公司環節不顯示
});

test("role: unknown until market data exists, then a suggestion I have to adopt", () => {
  assert.match(render(view([company({ role_suggestion: "unknown" })], { market_data: false })), /unknown（行情還沒接上）/);
  const withData = render(view([company({ role_suggestion: "leader" })], { market_data: true }));
  assert.match(withData, /建議：領漲/);
  assert.match(withData, /data-act="role" data-i="0" data-role="leader"/);
  assert.doesNotMatch(withData, /行情還沒接上/);
  const confirmed = render(view([company({ role: "laggard", role_suggestion: "leader" })], { market_data: true }));
  assert.match(confirmed, /<span class="chip mine">補漲<\/span>/);
  assert.doesNotMatch(confirmed, /採用建議/);  // 已經確認過，不再建議
  assert.doesNotMatch(render(view([company({ role_suggestion: "unknown" })], { market_data: true })), /採用建議|行情還沒接上/);
});

test("text from the data is escaped", () => {
  const html = render(view([link({ relation: "<img src=x onerror=alert(1)>", from: { label: "<b>x</b>" }, source: { url: 'https://example.com/"><script>' } })]));
  assert.doesNotMatch(html, /<img|<script|<b>x/);
  assert.match(html, /&lt;img/);
});

test("payload: label and tracked-entity nodes, source by url or item, blanks trimmed", () => {
  const d = C.blankDraft();
  d.from = { kind: "label", text: "  CoWoS 產能 ", entity: "" };
  d.to = { kind: "entity", text: "ignored", entity: E1 };
  d.relation = " 受益 "; d.url = " https://example.com/a "; d.item = "item-1";
  const body = C.payload(d, true);
  same(body.from, { label: "CoWoS 產能" });
  same(body.to, { entity_id: E1 });
  assert.equal(body.relation, "受益");
  same(body.source, { url: "https://example.com/a" });  // 網址優先
  d.url = "";
  same(C.payload(d, false).source, { item_id: "item-1" });
  d.item = "";
  assert.equal(C.payload(d, false).source, null);
});

test("payload: company links carry share and role; other links carry neither", () => {
  const d = C.blankDraft();
  assert.equal("revenue_share" in C.payload(d, false), false);
  assert.equal("role" in C.payload(d, false), false);
  assert.equal(C.payload(d, true).revenue_share, "unknown");
  d.shareMode = "range"; d.shareLow = "8"; d.shareHigh = " 12 "; d.shareUrl = "https://example.com/r"; d.role = "leader";
  const p = C.payload(d, true);
  same(p.revenue_share, { range: [8, 12], source: { url: "https://example.com/r" } });
  assert.equal(p.role, "leader");
  d.shareMode = "value"; d.shareValue = "abc";
  assert.equal(C.payload(d, true).revenue_share.value, null);  // 不是數字：送 null，讓後端回欄位錯誤
  d.shareValue = "";
  assert.equal(C.payload(d, true).revenue_share.value, null);  // 空白不是 0
  d.role = "evil";
  assert.equal(C.payload(d, true).role, "unknown");
});

test("toDraft round-trips an existing link, and editing resets nothing the server keeps", () => {
  const l = company({ revenue_share: { range: [8, 12], source: { url: "https://example.com/r" } }, role: "laggard", source: { item_id: "item-3" } });
  const d = C.toDraft(l);
  assert.equal(d.shareMode, "range");
  assert.equal(d.item, "item-3");
  assert.equal(d.role, "laggard");
  const p = C.payload(d, true);
  same(p.revenue_share, { range: [8, 12], source: { url: "https://example.com/r" } });
  same(p.to, { entity_id: E1 });
  assert.equal("confirmed" in p, false);  // 確認只能走確認的動作
});

test("server field names map to places on the form", () => {
  assert.equal(C.fieldKey("chain.2.from"), "from");
  assert.equal(C.fieldKey("chain.2.to"), "to");
  assert.equal(C.fieldKey("chain.2.relation"), "relation");
  assert.equal(C.fieldKey("chain.2.source"), "source");
  assert.equal(C.fieldKey("chain.2.revenue_share.value"), "share");
  assert.equal(C.fieldKey("chain.2.revenue_share.source"), "share");
  assert.equal(C.fieldKey("chain.2.role"), "role");
  assert.equal(C.fieldKey("link"), "form");
  assert.equal(C.fieldKey(undefined), "form");
});

test("dropdowns are capped but always keep the selected choice", () => {
  const list = Array.from({ length: C.MAX_CHOICES + 50 }, (_, i) => ({ id: "x" + i, name: "n" + i }));
  assert.equal(C.capChoices(list, null).length, C.MAX_CHOICES);
  const last = list[list.length - 1].id;
  const kept = C.capChoices(list, last);
  assert.equal(kept.length, C.MAX_CHOICES + 1);
  assert.equal(kept[kept.length - 1].id, last);
  const html = render(view([]), { entities: list, editing: { index: null, draft: Object.assign(C.blankDraft(), { to: { kind: "entity", text: "", entity: "" } }), errors: {} } });
  assert.equal((html.match(/<option value="x/g) || []).length, C.MAX_CHOICES);
});

test("adding stops at the link limit", () => {
  const links = Array.from({ length: C.MAX_LINKS }, (_, i) => link({ index: i }));
  const html = render(view(links));
  assert.match(html, /data-act="add" disabled/);
  assert.match(html, /最多 100 環/);
  assert.doesNotMatch(render(view(links.slice(0, 3))), /data-act="add" disabled/);
});

test("company form shows share and role fields only when the target is a tracked company", () => {
  const ents = [{ id: E1, name: "範例電源 A", type: "company" }, { id: "E-" + "b".repeat(32), name: "範例題材 B", type: "theme" }];
  const draft = (id) => Object.assign(C.blankDraft(), { to: { kind: "entity", text: "", entity: id } });
  assert.equal(C.entityIsCompany(ents, E1), true);
  assert.equal(C.entityIsCompany(ents, "E-" + "b".repeat(32)), false);
  assert.match(render(view([]), { entities: ents, editing: { index: null, draft: draft(E1), errors: {} } }), /data-k="shareMode"/);
  assert.doesNotMatch(render(view([]), { entities: ents, editing: { index: null, draft: draft("E-" + "b".repeat(32)), errors: {} } }), /data-k="shareMode"/);
});

test("errors from the server show on the field; busy and loading and error states render", () => {
  const html = render(view([]), { editing: { index: null, draft: C.blankDraft(), errors: { relation: "這一欄要填。" } } });
  assert.match(html, /class="input invalid" data-k="relation"/);
  assert.match(html, /這一欄要填。/);
  assert.match(render(view([]), { status: "loading" }), /aria-busy="true"/);
  assert.match(render(view([]), { status: "error" }), /讀不到這個題材/);
  assert.match(render(view([])), /還沒有因果鏈/);
  assert.match(render(view([]), { note: "不能進定稿" }), /role="alert"[^]*不能進定稿/);
});

test("publish only offers itself for a draft", () => {
  assert.match(render(view([link()], { status: "draft" })), /data-act="publish"/);
  assert.doesNotMatch(render(view([link()], { status: "final" })), /data-act="publish"/);
});

test("while a form is open, the other links' actions are disabled (removing one would shift the form's index)", () => {
  const links = [link({ index: 0, inferred: true }), link({ index: 1 }), company({ index: 2, role_suggestion: "leader" })];
  const html = render(view(links, { market_data: true }), { editing: { index: 1, draft: C.toDraft(links[1]), errors: {} } });
  for (const act of ["edit", "remove", "confirm", "role"]) {
    const buttons = html.match(new RegExp(`<button[^>]*data-act="${act}"[^>]*>`, "g")) || [];
    assert.ok(buttons.length > 0, act);
    for (const b of buttons) assert.match(b, / disabled/, act);
  }
  assert.doesNotMatch(render(view(links, { market_data: true })).match(/<button[^>]*data-act="remove"[^>]*>/)[0], / disabled/);
  assert.match(render(view(links), { busy: true }).match(/<button[^>]*data-act="edit"[^>]*>/)[0], / disabled/);
});

test("row actions name the link they act on", () => {
  assert.match(render(view([link()])), /data-act="remove"[^>]*aria-label="移除：需求 → 瓶頸"/);
});

test("a revenue share sourced from an item survives toDraft and payload", () => {
  const d = C.toDraft(company({ revenue_share: { value: 12, source: { item_id: "item-9" } } }));
  assert.equal(d.shareItem, "item-9");
  same(C.payload(d, true).revenue_share, { value: 12, source: { item_id: "item-9" } });
  d.shareUrl = "https://example.com/s";
  same(C.payload(d, true).revenue_share.source, { url: "https://example.com/s" });  // 有網址就用網址
});

test("company detection falls back to the chain's own types when the entity list is missing", () => {
  const links = [company()];
  assert.equal(C.entityIsCompany([], E1, links), true);
  assert.equal(C.entityIsCompany([], "E-" + "c".repeat(32), links), false);
  assert.equal(C.entityIsCompany([{ id: E1, type: "theme" }], E1, links), false);  // 名單有就以名單為準
});

test("an error on another link of the chain shows on the form, not on my field", () => {
  assert.equal(C.fieldKey("chain.0.to", 3), "form");
  assert.equal(C.fieldKey("chain.3.to", 3), "to");
  assert.equal(C.fieldKey("chain.3.role", 3), "role");
  assert.equal(C.fieldKey("base_version", 3), "form");
});

test("long source urls are kept whole in the title", () => {
  const url = "https://example.com/" + "a".repeat(180);
  assert.match(render(view([link({ source: { url } })])), new RegExp(`title="${url}"`));
});

test("while a request is in flight, no form opens and cancel is disabled", async () => {
  const links = [link({ index: 0 }), link({ index: 1 }), link({ index: 2 })];
  render(view(links), { busy: true });
  await C.act("edit", 2);
  await C.act("add", null);
  assert.equal(C.state.editing, null);
  const html = render(view(links), { busy: true, editing: { index: 1, draft: C.toDraft(links[1]), errors: {} } });
  assert.match(html.match(/<button[^>]*data-act="cancel"[^>]*>/)[0], / disabled/);
  C.state.busy = false;
  await C.act("edit", 2);
  assert.equal(C.state.editing.index, 2);
  C.state.editing = null;
});
