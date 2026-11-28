/* Ticket 68：匯入後的自動翻譯在等額度時，文獻庫清單和詳情怎麼顯示。假的 DOM；說明文字本身在 test_quota_guard_ui.cjs 測。 */
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

const guard = (canWait) => ({ waitLabel: () => "等額度重置", waitText: () => "額度超過門檻，先等", waitCanWait: () => canWait });

test("a waiting translation shows its label in the list", () => {
  const { PR } = setupLibraryEnvironment();
  PR.quotaGuard = guard(true);
  const html = PR.lib.jobLine({ id: "p1", job: { state: "waiting", wait: { reason: "quota" } } });
  assert.equal(html, '<span class="stat wait" title="額度超過門檻，先等">等額度重置</span>');
});

test("the detail panel explains the wait and offers start now and not needed", () => {
  const { PR, node } = setupLibraryEnvironment();
  PR.quotaGuard = guard(true);
  const L = PR.lib;
  L.items = [{ id: "p1", title_zh: "Nvidia 下修 H20 出貨預期", status: "unread", pages: 12, done_pages: 0, todo: 12,
    job: { state: "waiting", wait: { reason: "quota", until: null }, translate: true } }];
  L.selected = "p1";
  PR.renderDetail();
  const html = node("#detail").innerHTML;
  assert.ok(html.includes('<div class="wait">額度超過門檻，先等</div>'), html);
  assert.ok(html.includes("不想等可以現在開始，會用掉額度。"));
  assert.ok(html.includes('data-d="translate"'));  // 「開始翻譯」= 現在翻譯（手動，照跑、先提醒）
  assert.ok(html.includes('data-d="cancel">不用了'));
});

test("a wait that needs the user does not promise to continue by itself", () => {
  const { PR, node } = setupLibraryEnvironment();
  PR.quotaGuard = guard(false);
  const L = PR.lib;
  L.items = [{ id: "p1", title_zh: "美光法說", status: "unread", pages: 3, done_pages: 0,
    job: { state: "waiting", wait: { reason: "subscription", until: null }, translate: true } }];
  L.selected = "p1";
  PR.renderDetail();
  const html = node("#detail").innerHTML;
  assert.ok(!html.includes("不想等可以現在開始"));
  assert.ok(html.includes('data-d="cancel">不用了'));
});

test("other job states have no wait line", () => {
  const { PR, node } = setupLibraryEnvironment();
  PR.quotaGuard = guard(true);
  const L = PR.lib;
  L.items = [{ id: "p1", title_zh: "台積電月營收", status: "unread", pages: 3, done_pages: 1, job: { state: "done" } }];
  L.selected = "p1";
  PR.renderDetail();
  const html = node("#detail").innerHTML;
  assert.ok(!html.includes('class="wait"'));
  assert.ok(!html.includes("不用了"));
});
