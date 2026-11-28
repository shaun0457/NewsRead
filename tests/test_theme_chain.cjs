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

/* ---------- 版本衝突時保留表單（ticket 108） ---------- */
function loadWith(replies, doc = { addEventListener() {} }) {
  const calls = [];
  const PR = {
    lang: "zh-TW",
    t: (s, values = {}) => s.replace(/\{(\w+)\}/g, (m, key) => values[key] ?? m),
    esc: (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"),
    $: () => null, toast() {},
    api: (url, opts) => {
      calls.push({ url, method: (opts && opts.method) || "GET", body: opts && opts.body ? JSON.parse(JSON.stringify(opts.body)) : null });
      const r = replies.shift();
      if (!r) return Promise.reject(new Error("no reply"));
      return r.fail ? Promise.reject(r.fail) : Promise.resolve(r.ok);
    },
  };
  const context = { window: { PR }, document: doc };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../easyread/web/js/theme/chain.js"), "utf8"), context);
  return { C: PR.themeChain, calls, replies };
}
const STALE = { fail: { status: 400, data: { error: "這一頁已經有新的版本，請重新整理再改。", field: "base_version" } } };
const A = link({ index: 0, from: { label: "AI 加速器需求" }, to: { label: "CoWoS 產能" }, relation: "產能是出貨上限" });
const B = link({ index: 1, from: { label: "CoWoS 產能" }, to: { label: "台積電" }, relation: "月產能 8 萬片", source: { url: "https://example.com/80k" } });
function editing(C, links, index, relation) {
  Object.assign(C.state, { id: "E-x", status: "ready", view: view(links), entities: [], items: [], note: "", busy: false, conflict: null });
  const draft = index === null ? C.blankDraft() : C.toDraft(links[index]);
  if (index === null) { draft.from.text = "新的起點"; draft.to.text = "新的終點"; }
  draft.relation = relation;
  C.state.editing = { index, draft, errors: {} };
}

test("a save blocked by a newer version keeps the form, shows the new version beside mine, and resends on top of it", async () => {
  const theirs = Object.assign({}, B, { relation: "月產能年底前到 8 萬片（另一個分頁）" });
  const { C, calls, replies } = loadWith([STALE, { ok: view([A, theirs], { version: 3 }) }], { addEventListener() {}, body: { onbeforematch: null } });
  editing(C, [A, B], 1, "月產能拉到 9 萬片");
  await C.submit();
  assert.equal(C.state.editing.index, 1);
  assert.equal(C.state.editing.draft.relation, "月產能拉到 9 萬片");  // 打的內容還在
  assert.equal(C.state.view.version, 3);
  assert.equal(C.state.note, "");
  let html = C.viewHtml(C.state);
  assert.match(html, /<div class="banner warn" role="alert"><span class="ico">!<\/span><div>另一個分頁已經存了新版本（v3）。你這邊打的內容還在，還沒送出。/);
  assert.match(html, /data-act="compare" aria-expanded="false" aria-controls="chain-cmp">看新版</);
  assert.match(html, /data-act="resend"[^>]*>用我的內容重送</);
  assert.match(html, /data-act="discard"[^>]*>放棄我的，改用新版</);
  assert.match(html, /<div class="cmp" id="chain-cmp" hidden="until-found">/);  // 收著，但頁內搜尋找得到
  assert.match(html, /value="月產能拉到 9 萬片"/);
  assert.match(html, /type="submit">用我的內容重送</);
  await C.act("compare", null);
  html = C.viewHtml(C.state);
  assert.match(html, /aria-expanded="true"/);
  assert.match(html, /<div class="cmp" id="chain-cmp">/);
  assert.match(html, /<dd class="chg" data-no-i18n>月產能年底前到 8 萬片（另一個分頁）<\/dd>/);
  assert.match(html, /<dd class="chg" data-no-i18n>月產能拉到 9 萬片<\/dd>/);
  assert.match(html, /<dd data-no-i18n>CoWoS 產能 → 台積電<\/dd>/);  // 一樣的欄位不上底色
  assert.match(html, /v3 · 另一個分頁/);
  replies.push({ ok: view([A, Object.assign({}, B, { relation: "月產能拉到 9 萬片" })], { version: 4 }) });
  await C.act("resend", null);
  const last = calls[calls.length - 1];
  same([last.method, last.body.base_version, last.body.op, last.body.index, last.body.link.relation], ["POST", 3, "update", 1, "月產能拉到 9 萬片"]);
  assert.equal(C.state.editing, null);
  assert.equal(C.state.conflict, null);
  assert.doesNotMatch(C.viewHtml(C.state), /另一個分頁/);
});

test("the link being edited is followed to its new place, or the resend becomes an add when it is gone", async () => {
  const X = link({ index: 0, from: { label: "雲端資本支出" }, to: { label: "AI 加速器需求" } });
  let r = loadWith([STALE, { ok: view([X, Object.assign({}, A, { index: 1 }), Object.assign({}, B, { index: 2 })], { version: 3 }) }]);
  editing(r.C, [A, B], 1, "我的說明");
  await r.C.submit();
  assert.equal(r.C.state.editing.index, 2);  // 另一個分頁在前面加了一環
  assert.match(r.C.viewHtml(r.C.state), /另一個分頁已經存了新版本（v3）。/);
  r.replies.push({ ok: view([X, A, B], { version: 4 }) });
  await r.C.submit();
  same([r.calls[2].body.op, r.calls[2].body.index], ["update", 2]);

  r = loadWith([STALE, { ok: view([A], { version: 3 }) }]);
  editing(r.C, [A, B], 1, "我的說明");
  await r.C.submit();
  assert.equal(r.C.state.editing.index, null);
  assert.equal(r.C.state.conflict.moved, true);
  const html = r.C.viewHtml(r.C.state);
  assert.match(html, /這一環在新版裡被移除，或改了從、到。你這邊打的內容還在，重送會加成新的一環。/);
  assert.doesNotMatch(html, /data-act="compare"/);
  assert.match(html, /value="我的說明"/);
  r.replies.push({ ok: view([A, B], { version: 4 }) });
  await r.C.submit();
  same([r.calls[2].body.op, r.calls[2].body.base_version, r.calls[2].body.link.relation], ["add", 3, "我的說明"]);
});

test("a blocked add keeps the form; an unreadable new version keeps the old one and the next resend tries again", async () => {
  let r = loadWith([STALE, { ok: view([A, B], { version: 3 }) }]);
  editing(r.C, [A], null, "新的一環");
  await r.C.submit();
  assert.equal(r.C.state.editing.index, null);
  assert.match(r.C.viewHtml(r.C.state), /另一個分頁已經存了新版本（v3），上面已經是新版的因果鏈。/);
  assert.equal(r.C.viewHtml(r.C.state).match(/<li class="edit">/g).length, 1);

  r = loadWith([STALE, { fail: new Error("offline") }]);
  editing(r.C, [A, B], 1, "我的說明");
  await r.C.submit();
  assert.equal(r.C.state.view.version, 2);
  assert.equal(r.C.state.editing.index, 1);
  assert.match(r.C.viewHtml(r.C.state), /但現在讀不到新版。你這邊打的內容還在，稍後再按「用我的內容重送」。/);
  r.replies.push(STALE, { ok: view([A, B], { version: 3 }) });
  await r.C.act("resend", null);
  same([r.calls[2].body.base_version, r.C.state.view.version, r.C.state.conflict.unread], [2, 3, false]);
});

test("dropping mine closes the form and reloads; other actions blocked by a new version still just reload", async () => {
  let r = loadWith([STALE, { ok: view([A, B], { version: 3 }) }, { ok: view([A, B], { version: 3 }) }]);
  editing(r.C, [A, B], 1, "我的說明");
  await r.C.submit();
  await r.C.act("discard", null);
  same([r.C.state.editing, r.C.state.conflict, r.calls[2].method], [null, null, "GET"]);

  r = loadWith([STALE, { ok: view([A], { version: 3 }) }]);
  Object.assign(r.C.state, { id: "E-x", status: "ready", view: view([A, B]), editing: null, conflict: null, busy: false, note: "" });
  await r.C.act("remove", 1);
  same([r.C.state.note, r.C.state.view.version, r.C.state.conflict], ["這一頁已經有新的版本，已重新載入。", 3, null]);
});

test("matchLink: same place first, then the only link with the same from and to; duplicates or none give null", () => {
  const E2 = "E-" + "b".repeat(32);
  const ent = link({ from: { label: "需求" }, to: { entity_id: E2, name: "改名後也一樣" } });
  assert.equal(C.matchLink(A, 0, [A, B]), 0);
  assert.equal(C.matchLink(B, 0, [B, A]), 0);
  assert.equal(C.matchLink(B, 0, [A, B]), 1);
  assert.equal(C.matchLink(B, 1, [A, B, B]), 1);
  assert.equal(C.matchLink(B, 0, [A, B, B]), null);  // 好幾個一樣的：不猜
  assert.equal(C.matchLink(B, 1, [A]), null);
  assert.equal(C.matchLink(link({ from: { label: "需求" }, to: { entity_id: E2 } }), 0, [ent]), 0);  // 追蹤對象看 id，不看名稱
  assert.equal(C.matchLink(null, 0, [A]), null);
});

test("browsers without hidden=until-found get a plain hidden comparison, and the global hidden rule leaves until-found alone", async () => {
  const theirs = Object.assign({}, B, { relation: "另一個分頁的說明" });
  const { C } = loadWith([STALE, { ok: view([A, theirs], { version: 3 }) }], { addEventListener() {}, body: {} });
  editing(C, [A, B], 1, "我的說明");
  await C.submit();
  assert.match(C.viewHtml(C.state), /<div class="cmp" id="chain-cmp" hidden>/);
  const css = fs.readFileSync(path.join(__dirname, "../easyread/web/css/newsread.css"), "utf8");
  assert.match(css, /\[hidden\]:not\(\[hidden="until-found" i\]\) \{ display: none !important; \}/);
  assert.doesNotMatch(css, /^\[hidden\] \{ display: none/m);
});

/* ---------- 欄位的來源和定稿前的預覽（ticket 106） ---------- */
const AI = { by: "ai:opus@v1", reviewed: false }, REVIEWED = { by: "ai:opus@v1", reviewed: true }, ME = { by: "me", reviewed: false };

test("each link shows who wrote it once AI wrote anything in this version; nothing when it is all mine", () => {
  const html = render(view([link({ index: 0, provenance: AI }), link({ index: 1, provenance: REVIEWED }), link({ index: 2, provenance: ME })],
                           { provenance: { one_liner: ME, second_order: [] } }));
  const items = html.split("<li").slice(1);
  assert.match(items[0], /<span class="chip ai">AI 起草<\/span>/);
  assert.match(items[1], /<span class="chip ai">AI 起草・你確認過<\/span>/);
  assert.match(items[2], /<span class="chip mine">我寫的<\/span>/);
  assert.doesNotMatch(render(view([link({ provenance: ME })], { provenance: { one_liner: ME, second_order: [ME] } })), /我寫的|AI 起草/);
  assert.match(render(view([link({ provenance: ME })], { provenance: { one_liner: AI } })), /我寫的/);  // AI 寫的是這頁沒顯示的欄位也算
  assert.doesNotMatch(render(view([link()])), /我寫的|AI 起草/);  // 舊的回應沒有 provenance
});

const PREVIEW = () => view([link({ index: 0, provenance: AI }), company({ index: 1, provenance: ME })], {
  version: 5,
  fields: { one_liner: "雲端廠把資本支出集中到 AI 伺服器", analogy: null, origin: { kind: "news_first", item_id: "item-3", rotation_event: null },
            second_order: ["液冷需求上升", "通用伺服器被排擠"], stage: { name: "放量期", basis: "ODM 月營收連三月年增" } },
  provenance: { one_liner: AI, analogy: AI, origin: AI, second_order: [AI, REVIEWED], stage: ME },
});

test("the preview lists every field that goes into the final, tags the ones this page does not show, and counts what you review", () => {
  const rows = C.previewRows(PREVIEW());
  same(rows.map((r) => [r.label, r.hidden, r.value, r.prov.by]), [
    ["一句話故事", true, "雲端廠把資本支出集中到 AI 伺服器", "ai:opus@v1"], ["白話類比", true, "沒有填", "ai:opus@v1"],
    ["起源", true, "消息先動 · 資料 item-3", "ai:opus@v1"], ["第二層效應 1", true, "液冷需求上升", "ai:opus@v1"],
    ["第二層效應 2", true, "通用伺服器被排擠", "ai:opus@v1"], ["階段", true, "放量期 · 依據：ODM 月營收連三月年增", "me"],
    ["因果鏈第 1 環", false, "需求 → 瓶頸：說明", "ai:opus@v1"], ["因果鏈第 2 環", false, "需求 → 範例電源 A：說明", "me"]]);
  const html = C.previewHtml(PREVIEW());
  assert.match(html, /<form method="dialog" class="pv"><h1 id="chain-pv-title">/);
  assert.match(html, /一句話故事<span class="hidden-tag">這頁沒顯示<\/span>/);
  assert.doesNotMatch(html, /因果鏈第 1 環<span class="hidden-tag">/);
  assert.match(html, /<span class="chip ai">AI・你確認過<\/span>/);
  assert.match(html, /共 8 個欄位：5 個 AI 寫的會標成你確認過，其中 4 個這頁沒顯示。/);
  assert.match(html, /<button class="btn sm ghost" value="cancel" autofocus>取消<\/button><button class="btn sm primary" value="publish">確認成定稿 v6<\/button>/);
  const mine = C.previewHtml(view([link({ provenance: ME })], { version: 1, fields: {}, provenance: { one_liner: ME } }));
  assert.match(mine, /共 5 個欄位，沒有要確認的 AI 欄位。/);
  const bad = C.previewHtml(view([], { fields: { one_liner: "<img src=x onerror=alert(1)>" }, provenance: {} }));
  assert.doesNotMatch(bad, /<img/);
});

function fakeDialogDoc() {
  const els = {};
  const doc = {
    addEventListener() {}, getElementById: (id) => els[id] || null,
    body: { appendChild(el) { els[el.id] = el; } },
    createElement: () => ({
      dataset: {}, attrs: {}, listeners: {}, returnValue: "", open: false, innerHTML: "",
      setAttribute(k, v) { this.attrs[k] = v; }, addEventListener(k, f) { this.listeners[k] = f; },
      showModal() { this.open = true; },
      close(value) { if (value !== undefined) this.returnValue = value; this.open = false; if (this.listeners.close) this.listeners.close(); },
    }),
  };
  return { doc, els };
}

test("publish opens the preview first; cancelling or Esc sends nothing, confirming publishes the version that was previewed", async () => {
  const { doc, els } = fakeDialogDoc();
  const { C, calls } = loadWith([{ ok: view([], { status: "final", version: 6 }) }], doc);
  Object.assign(C.state, { id: "E-x", status: "ready", view: PREVIEW(), editing: null, busy: false, conflict: null, note: "" });
  assert.match(C.viewHtml(C.state), /data-act="publish" aria-haspopup="dialog">確認成定稿…<\/button>/);
  await C.act("publish", null);
  const d = els["chain-pv"];
  same([d.open, d.attrs["aria-labelledby"], calls.length], [true, "chain-pv-title", 0]);
  assert.match(d.innerHTML, /確認成定稿 v6/);
  d.close("cancel");
  same([d.open, d.returnValue, calls.length], [false, "", 0]);
  await C.act("publish", null);
  d.close();  // Esc：沒有 returnValue
  assert.equal(calls.length, 0);
  await C.act("publish", null);
  C.state.view = Object.assign(PREVIEW(), { version: 9 });  // 預覽開著時畫面換了版本：送出的還是預覽的那一版
  d.close("publish");
  await new Promise((r) => setImmediate(r));
  same([calls.length, calls[0].method, calls[0].body.op, calls[0].body.base_version], [1, "POST", "publish", 5]);
  assert.equal(C.state.view.status, "final");
  C.state.view = PREVIEW();
  C.state.editing = { index: null, draft: C.blankDraft(), errors: {} };
  d.innerHTML = "";
  await C.act("publish", null);  // 有表單開著（按鈕停用）時不開預覽
  assert.equal(d.innerHTML, "");
});

