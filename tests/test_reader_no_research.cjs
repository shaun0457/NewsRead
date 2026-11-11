// Tickets 03 + 04: the research workspace is gone; the reader and the task monitor only use /api/reader.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const WEB = path.join(__dirname, "../easyread/web");
const MONITOR = "/web/js/common/research-task-monitor.js";

function pageScripts(page) {
  const html = fs.readFileSync(path.join(WEB, page), "utf8");
  return [...html.matchAll(/<script src="(\/web\/js\/[^"]+\.js)"/g)].map((m) => m[1]);
}

test("reader and library scripts do not reference the research workspace, Zotero migration or bulk import", () => {
  const scripts = [...new Set([...pageScripts("reader.html"), ...pageScripts("library.html")])];
  assert.ok(scripts.length > 20);
  assert.ok(scripts.includes(MONITOR));
  for (const src of scripts) {
    const code = fs.readFileSync(path.join(WEB, "..", src), "utf8");
    assert.doesNotMatch(code, /\/api\/research|\/api\/zotero|\/api\/migrate|["'`]\/research[?"'`]/, src);
  }
  assert.ok(!fs.existsSync(path.join(WEB, "research.html")));
  assert.ok(!fs.existsSync(path.join(WEB, "js/library/bulk-import.js")));
});

test("reader exports and mind map go through /api/reader", () => {
  const read = (name) => fs.readFileSync(path.join(WEB, "js/reader", name), "utf8");
  assert.match(read("export.js"), /"\/api\/reader\/export\/obsidian"/);
  assert.match(read("export.js"), /"\/api\/reader\/export\/zip"/);
  assert.match(read("export.js"), /"\/api\/reader\/vault"/);
  assert.match(read("chat-export.js"), /"\/api\/reader\/export\/obsidian"/);
  assert.match(read("planner.js"), /API = "\/api\/reader"/);
  assert.doesNotMatch(read("export.js"), /deep_analysis|deep-analysis/);
});

function loadMonitor(pathname, readerTasks = [], modal = null) {
  const calls = [];
  const listeners = {};
  const created = [];
  const stored = {};
  const node = () => ({ hidden: true, innerHTML: "", dataset: {}, firstElementChild: {}, appendChild() {}, querySelector: () => null, querySelectorAll: () => [], focus() {}, addEventListener() {}, contains: () => false });
  const PR = {
    t: (s) => s, esc: (s) => String(s), $: (sel) => (sel === "#pr-research-task-modal" ? modal : null), $$: () => [], el: () => { const n = node(); created.push(n); return n; }, emit() {}, toast() {},
    api: async (url, options) => {
      calls.push([url, options?.method || "GET", options?.body]);
      if (url === "/api/library") return { token: "t" };
      if (url === "/api/reader/tasks") return { scope_id: "s1", tasks: readerTasks };
      return { task: null, tasks: [] };
    },
  };
  const context = {
    window: { PR }, PR, location: { pathname, protocol: "http:", href: "" },
    document: { body: { appendChild() {} }, hidden: false, addEventListener: (type, fn) => { listeners[type] = fn; }, activeElement: null },
    localStorage: { getItem: (k) => stored[k] ?? null, setItem: (k, v) => { stored[k] = v; } }, setTimeout: () => 0, clearTimeout() {}, Notification: undefined,
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(WEB, "js/common/research-task-monitor.js"), "utf8"), context);
  return { PR, calls, created, stored };
}

test("on the reader page the task monitor polls only /api/reader/tasks", async () => {
  const { calls } = loadMonitor("/read/p1");
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
  const urls = calls.map(([url]) => url);
  assert.ok(urls.includes("/api/reader/tasks"), urls.join(","));
  assert.equal(urls.filter((url) => url.startsWith("/api/research")).length, 0, urls.join(","));
});

test("on the library page the task monitor also polls only /api/reader/tasks", async () => {
  const { calls } = loadMonitor("/");
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
  const urls = calls.map(([url]) => url);
  assert.ok(urls.includes("/api/reader/tasks"), urls.join(","));
  assert.equal(urls.filter((url) => url.startsWith("/api/research")).length, 0, urls.join(","));
});

for (const [page, pathname] of [["reader", "/read/p1"], ["library", "/"]]) {
  test(`on the ${page} page a finished mind map task is acknowledged through the reader API`, async () => {
    const done = { id: "m1", kind: "mindmap", state: "completed", paper_id: "p1", key: "p1" };
    const { calls } = loadMonitor(pathname, [done]);
    for (let i = 0; i < 4; i += 1) await new Promise((resolve) => setImmediate(resolve));
    assert.ok(calls.some(([url, method]) => url === "/api/reader/paper/p1/mindmap/tasks/m1/ack" && method === "POST"), calls.join(" | "));
    assert.equal(calls.filter(([url]) => /\/api\/research\/v2\/[^ ]*mindmap/.test(url)).length, 0);
  });
}

test("a mind map task without a paper id is not acknowledged at a broken URL", async () => {
  const { calls } = loadMonitor("/read/p1", [{ id: "m2", kind: "mindmap", state: "completed" }]);
  for (let i = 0; i < 4; i += 1) await new Promise((resolve) => setImmediate(resolve));
  assert.equal(calls.filter(([url]) => url.includes("/ack")).length, 0, calls.join(" | "));
});

test("cancelling a running mind map task from the dialog posts to the reader API", async () => {
  const buttons = { "[data-task-cancel]": {} };
  const modal = { hidden: true, dataset: {}, innerHTML: "", querySelector: (sel) => buttons[sel] || null, querySelectorAll: () => [], focus() {}, contains: () => false };
  const { PR, calls } = loadMonitor("/read/p1", [], modal);
  await new Promise((resolve) => setImmediate(resolve));
  PR.researchTaskMonitor.track({ id: "m9", kind: "mindmap", state: "running", paper_id: "p1" }, true);
  assert.equal(typeof buttons["[data-task-cancel]"].onclick, "function");
  buttons["[data-task-cancel]"].onclick();
  assert.ok(calls.some(([url, method]) => url === "/api/reader/paper/p1/mindmap/tasks/m9/cancel" && method === "POST"), calls.join(" | "));
});

test("tasks of removed kinds are ignored by the monitor", async () => {
  const modal = { hidden: true, dataset: {}, innerHTML: "", querySelector: () => null, querySelectorAll: () => [], focus() {}, contains: () => false };
  const { PR, calls, created } = loadMonitor("/", [{ id: "x1", kind: "reading-path", state: "completed" }], modal);
  for (let i = 0; i < 4; i += 1) await new Promise((resolve) => setImmediate(resolve));
  PR.researchTaskMonitor.track({ id: "x2", kind: "deep-analysis", state: "running" }, true);
  assert.equal(calls.filter(([, method]) => method === "POST").length, 0, calls.join(" | "));
  assert.equal(modal.hidden, true, "no dialog for a removed kind");
  assert.ok(created.every((n) => n.hidden !== false), "no task entry shown for a removed kind");
});

test("cancelling a running smart-annotate task posts to the paper's cancel endpoint", async () => {
  const buttons = { "[data-task-cancel]": {} };
  const modal = { hidden: true, dataset: {}, innerHTML: "", querySelector: (sel) => buttons[sel] || null, querySelectorAll: () => [], focus() {}, contains: () => false };
  const { PR, calls } = loadMonitor("/read/p1", [], modal);
  await new Promise((resolve) => setImmediate(resolve));
  PR.researchTaskMonitor.track({ id: "j7", kind: "smart-annotate", state: "running", paper_id: "p1" }, true);
  buttons["[data-task-cancel]"].onclick();
  const posted = calls.find(([url, method]) => url === "/api/p/p1/smart-annotate-cancel" && method === "POST");
  assert.ok(posted, calls.join(" | "));
  assert.equal(JSON.stringify(posted[2]), JSON.stringify({ job: "j7" }));
});

test("a finished smart-annotate task is acknowledged only in the browser, under the old ack key", async () => {
  const { calls, stored } = loadMonitor("/read/p1", [{ id: "j8", kind: "smart-annotate", state: "completed", paper_id: "p1" }]);
  for (let i = 0; i < 4; i += 1) await new Promise((resolve) => setImmediate(resolve));
  assert.equal(calls.filter(([, method]) => method === "POST").length, 0, calls.join(" | "));
  assert.deepEqual(Object.keys(stored), ["paperread:research-task-acks:s1"]);
  assert.deepEqual(JSON.parse(stored["paperread:research-task-acks:s1"]), ["j8"]);
});
