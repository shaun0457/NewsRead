// Ticket 03: the reader no longer calls the research workspace API; it uses /api/reader instead.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const WEB = path.join(__dirname, "../easyread/web");
const MONITOR = "/web/js/common/research-task-monitor.js";

function readerScripts() {
  const html = fs.readFileSync(path.join(WEB, "reader.html"), "utf8");
  return [...html.matchAll(/<script src="(\/web\/js\/[^"]+\.js)"/g)].map((m) => m[1]);
}

test("reader scripts do not reference the research workspace API or page", () => {
  const scripts = readerScripts();
  assert.ok(scripts.length > 10);
  for (const src of scripts) {
    if (src === MONITOR) continue; // shared with the library page; covered by the behavioural test below
    const code = fs.readFileSync(path.join(WEB, "..", src), "utf8");
    assert.doesNotMatch(code, /\/api\/research|["'`]\/research[?"'`]/, src);
  }
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

function loadMonitor(pathname, readerTasks = []) {
  const calls = [];
  const listeners = {};
  const node = () => ({ hidden: true, innerHTML: "", appendChild() {}, querySelector: () => null, querySelectorAll: () => [], focus() {}, addEventListener() {} });
  const PR = {
    t: (s) => s, esc: (s) => String(s), $: () => null, $$: () => [], el: node, emit() {}, toast() {},
    api: async (url, options) => {
      calls.push([url, options?.method || "GET"]);
      if (url === "/api/library") return { token: "t" };
      if (url === "/api/reader/tasks" || url === "/api/research/v1/monitor") return { scope_id: "s1", tasks: readerTasks };
      return { task: null, tasks: [] };
    },
  };
  const context = {
    window: { PR }, PR, location: { pathname, protocol: "http:", href: "" },
    document: { body: { appendChild() {} }, hidden: false, addEventListener: (type, fn) => { listeners[type] = fn; }, activeElement: null },
    localStorage: { getItem: () => null, setItem() {} }, setTimeout: () => 0, clearTimeout() {}, Notification: undefined,
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(WEB, "js/common/research-task-monitor.js"), "utf8"), context);
  return { PR, calls };
}

test("on the reader page the task monitor polls only /api/reader/tasks", async () => {
  const { calls } = loadMonitor("/read/p1");
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
  const urls = calls.map(([url]) => url);
  assert.ok(urls.includes("/api/reader/tasks"), urls.join(","));
  assert.equal(urls.filter((url) => url.startsWith("/api/research")).length, 0, urls.join(","));
});

test("on the library page the task monitor still polls the research monitor (removed in ticket 04)", async () => {
  const { calls } = loadMonitor("/");
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
  assert.ok(calls.some(([url]) => url === "/api/research/v1/monitor"));
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

test("cancel uses the same reader URL builder as ack", () => {
  const code = fs.readFileSync(path.join(WEB, "js/common/research-task-monitor.js"), "utf8");
  assert.match(code, /type === "mindmap" \? readerMindmapUrl\(pid, task\.id, "cancel"\)/);
});
