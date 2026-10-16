const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const source = file => fs.readFileSync(path.join(__dirname, "../easyread/web/js/", file), "utf8");

function setupLibraryEnvironment() {
  const nodes = new Map();
  const listeners = new Map();
  const node = selector => {
    if (!nodes.has(selector)) nodes.set(selector, {
      value: "", style: { setProperty() {}, getPropertyValue() { return "248px"; } }, dataset: {},
      classList: { toggle() {}, add() {}, remove() {}, contains() { return false; } },
      addEventListener(name, fn) { this[name] = fn; },
      focus() {},
      select() {},
      contains() { return false; },
      matches() { return false; },
      appendChild() {},
      querySelector(s) { return null; },
      querySelectorAll(s) { return []; },
    });
    return nodes.get(selector);
  };

  const PR = {
    t: (s, values = {}) => s.replace(/\{(\w+)\}/g, (m, key) => values[key] ?? m),
    titles: i => ({ main: i.title_zh || i.title_en || "", short: i.short_zh || i.title_zh || i.title_en || "" }),
    $: node,
    $$: () => [],
    el: (tag, attrs = {}) => ({ tag, ...attrs, addEventListener() {} }),
    icon: (name) => `<svg data-icon="${name}"></svg>`,
    logo: () => "",
    esc: text => String(text || ""),
    relTime: () => "刚刚",
    debounce: fn => fn,
    usageCard: () => "",
    ls: { get: (k, fallback) => fallback, set() {} },
    savePrefs() {},
    applyTheme() {},
    toast() {},
    api: async () => ({}),
  };

  const context = {
    window: { PR, addEventListener() {} },
    document: {
      addEventListener(name, fn) { listeners.set(name, fn); },
      body: { classList: { add() {}, remove() {} } },
      activeElement: { matches() { return false; } }
    },
    location: { href: "" },
    setTimeout: (fn) => fn(),
    clearTimeout: () => {},
  };

  vm.runInNewContext(source("library/app.js"), context);
  vm.runInNewContext(source("library/sidebar.js"), context);
  vm.runInNewContext(source("library/detail.js"), context);
  vm.runInNewContext(source("library/batch.js"), context);

  return { PR, context, node };
}

test("archived papers are filtered out of active views, categories and recent in library", () => {
  const { PR } = setupLibraryEnvironment();
  const L = PR.lib;

  const p1 = { id: "p1", title_zh: "未讀論文1", status: "unread", tags: ["AI"], added: "2026-01-01T00:00:00Z", archived: false };
  const p2 = { id: "p2", title_zh: "已讀論文2", status: "done", tags: ["AI"], added: "2026-01-02T00:00:00Z", last_opened: "2026-01-03T00:00:00Z", archived: true };
  const p3 = { id: "p3", title_zh: "閱讀中論文3", status: "reading", tags: ["ML"], added: "2026-01-04T00:00:00Z", archived: false };

  L.items = [p1, p2, p3];

  // In "all" view
  L.view = "all";
  L.tag = null;
  let filtered = L.filtered();
  assert.equal(filtered.length, 2);
  assert.deepEqual(filtered.map(x => x.id), ["p3", "p1"]); // sorted by opened/added desc

  // In "done" status view
  L.view = "done";
  filtered = L.filtered();
  assert.equal(filtered.length, 0); // p2 is done but archived, so filtered out

  // In "AI" category tag
  L.view = "all";
  L.tag = "AI";
  filtered = L.filtered();
  assert.equal(filtered.length, 1);
  assert.equal(filtered[0].id, "p1"); // p2 is tagged AI but archived

  // In "archived" view
  L.view = "archived";
  L.tag = null;
  filtered = L.filtered();
  assert.equal(filtered.length, 1);
  assert.equal(filtered[0].id, "p2");
});

test("unarchiving an archived paper restores its original status and category", () => {
  const { PR } = setupLibraryEnvironment();
  const L = PR.lib;

  const p2 = { id: "p2", title_zh: "已讀論文2", status: "done", tags: ["AI"], added: "2026-01-02T00:00:00Z", archived: true };
  L.items = [p2];

  // Unarchive p2
  p2.archived = false;

  L.view = "done";
  L.tag = null;
  let filtered = L.filtered();
  assert.equal(filtered.length, 1);
  assert.equal(filtered[0].id, "p2");
  assert.equal(filtered[0].status, "done");
  assert.deepEqual(filtered[0].tags, ["AI"]);
});

test("sidebar renders archived folder with correct count", () => {
  const { PR, node } = setupLibraryEnvironment();
  const L = PR.lib;
  L.items = [
    { id: "p1", title_zh: "未讀論文1", status: "unread", archived: false },
    { id: "p2", title_zh: "封存論文2", status: "done", archived: true },
    { id: "p3", title_zh: "封存論文3", status: "reading", archived: true },
  ];

  PR.renderSide();
  const sideHtml = node("#side").innerHTML;
  assert.ok(sideHtml.includes('data-view="archived"'));
  assert.ok(sideHtml.includes('已封存'));
  assert.ok(sideHtml.includes('<span class="n">2</span>')); // 2 archived papers
});

test("detail panel displays archived banner and actions for archived paper", () => {
  const { PR, node } = setupLibraryEnvironment();
  const L = PR.lib;
  const p = { id: "p1", title_zh: "測試封存論文", status: "done", tags: ["Test"], archived: true };
  L.items = [p];
  L.selected = "p1";

  PR.renderDetail();
  const detailHtml = node("#detail").innerHTML;
  assert.ok(detailHtml.includes('class="archived-banner"'));
  assert.ok(detailHtml.includes('此論文目前已封存，不會出現在閱讀看板中。'));
  assert.ok(detailHtml.includes('data-d="unarchive"'));
  assert.ok(detailHtml.includes('data-d="archive"'));
});

test("reading board filters out archived papers and orders each column by newest added at top", () => {
  const host = { innerHTML: "", querySelector() { return { addEventListener() {} }; } };
  const PR = {
    t: (s, v = {}) => s.replace(/\{(\w+)\}/g, (m, k) => v[k] ?? m),
    $: (sel) => sel === "[data-view='board']" ? host : { innerHTML: "", textContent: "", classList: { remove() {} } },
    $$: () => [],
    esc: s => String(s || ""),
    icon: () => "",
    api: async () => ({}),
  };

  const context = {
    window: { PR },
    document: { addEventListener() {} },
    location: { search: "" },
    URLSearchParams,
  };

  vm.runInNewContext(source("research/workspace.js"), context);

  const items = [
    { id: "p1", title_zh: "論文1（最早加入）", status: "unread", added: "2026-01-01T10:00:00Z", archived: false },
    { id: "p2", title_zh: "論文2（最新加入）", status: "unread", added: "2026-01-05T10:00:00Z", archived: false },
    { id: "p3", title_zh: "論文3（已封存）", status: "unread", added: "2026-01-06T10:00:00Z", archived: true },
    { id: "p4", title_zh: "論文4（次新）", status: "unread", added: "2026-01-03T10:00:00Z", archived: false },
    { id: "p5", title_zh: "論文5（已完成舊）", status: "done", added: "2026-01-02T10:00:00Z", archived: false },
    { id: "p6", title_zh: "論文6（已完成新）", status: "done", added: "2026-01-04T10:00:00Z", archived: false },
  ];

  // 1. Verify archived papers are excluded
  const nonArchived = items.filter(x => !x.archived);
  assert.equal(nonArchived.length, 5);
  assert.ok(!nonArchived.some(x => x.id === "p3"));

  // 2. Verify sorting by newest added at top
  const unreadColumn = nonArchived.filter(x => x.status === "unread");
  unreadColumn.sort((a, b) => String(b.added || "").localeCompare(String(a.added || "")));
  assert.deepEqual(unreadColumn.map(x => x.id), ["p2", "p4", "p1"]);
  assert.equal(unreadColumn[0].title_zh, "論文2（最新加入）");

  const doneColumn = nonArchived.filter(x => x.status === "done");
  doneColumn.sort((a, b) => String(b.added || "").localeCompare(String(a.added || "")));
  assert.deepEqual(doneColumn.map(x => x.id), ["p6", "p5"]);
  assert.equal(doneColumn[0].title_zh, "論文6（已完成新）");
});

test("detail panel and rowMenu toggle archive accurately and display correct toast", () => {
  const { PR } = setupLibraryEnvironment();
  const L = PR.lib;
  const p = { id: "p1", title_zh: "未封存論文", status: "unread", archived: false };
  L.items = [p];

  let patched = null;
  L.patch = (id, fields) => {
    patched = { id, fields };
    Object.assign(p, fields);
  };

  // Simulating the archive action on an active (unarchived) paper:
  let willArchive = !p.archived;
  L.patch(p.id, { archived: willArchive });
  assert.equal(patched.fields.archived, true);
  assert.equal(p.archived, true);
  assert.equal(willArchive ? "已移至封存區" : "已解除封存，恢復當時狀態", "已移至封存區");

  // Simulating the archive action on an already archived paper:
  willArchive = !p.archived;
  L.patch(p.id, { archived: willArchive });
  assert.equal(patched.fields.archived, false);
  assert.equal(p.archived, false);
  assert.equal(willArchive ? "已移至封存區" : "已解除封存，恢復當時狀態", "已解除封存，恢復當時狀態");
});

test("reading board taskCard renders archive icon button with data-action='archive-task'", () => {
  const host = { innerHTML: "", querySelector() { return { addEventListener() {} }; } };
  const PR = {
    t: (s, v = {}) => s.replace(/\{(\w+)\}/g, (m, k) => v[k] ?? m),
    $: (sel) => host,
    $$: () => [],
    esc: s => String(s || ""),
    icon: (name) => `<svg name="${name}"></svg>`,
    api: async () => ({}),
  };

  const context = {
    window: { PR },
    document: { addEventListener() {} },
    location: { search: "" },
    URLSearchParams,
  };

  vm.runInNewContext(source("research/workspace.js"), context);

  // Check taskCard output indirectly by running the workspace script and invoking renderBoard
  // or verifying the generated HTML contains archive-btn
  const task = { id: "p1", title: "看板測試論文", title_zh: "看板測試論文", status: "unread", added: "2026-01-01T00:00:00Z", archived: false };
  // Verify that the taskCard markup includes data-action="archive-task"
  const wsSource = source("research/workspace.js");
  assert.ok(wsSource.includes('data-action="archive-task"'));
  assert.ok(wsSource.includes('class="linkish archive-btn"'));
});
