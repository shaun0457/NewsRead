// 貼連結匯入的入口（ticket 11）：「＋ 貼網址」按鈕、不在輸入框時 Ctrl+V 貼網址會打開匯入；在輸入框裡照常貼上。
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

function fakeElement(tag) {
  const el = {
    tagName: tag.toUpperCase(), children: [], dataset: {}, listeners: {}, className: "", id: "", innerHTML: "", textContent: "",
    classList: { set: new Set(), add(c) { this.set.add(c); }, remove(c) { this.set.delete(c); }, contains(c) { return this.set.has(c); } },
    addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); },
    appendChild(child) { this.children.push(child); child.parent = this; return child; },
    insertBefore(child) { this.children.unshift(child); child.parent = this; return child; },
    after(child) { this.children.push(child); child.parent = this; },
    querySelector(sel) {
      for (const part of sel.split(",").map((s) => s.trim())) {
        const found = part === "[data-ingest-open]" ? this.children.find((c) => "ingestOpen" in c.dataset)
          : part.startsWith("#") ? this.children.find((c) => c.id === part.slice(1)) : null;
        if (found) return found;
      }
      return null;
    },
    closest(sel) { return this.editable && /input|textarea/.test(sel) ? this : null; },
  };
  return el;
}

function setup() {
  const listeners = {};
  const bar = fakeElement("header");
  const importBtn = fakeElement("button");
  importBtn.id = "importBtn";
  bar.children.push(importBtn);
  const body = fakeElement("body");
  const opened = [];
  const calls = [];
  const document = {
    readyState: "complete", body, activeElement: body,
    addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
    querySelector(sel) { return sel.includes("topbar") ? bar : null; },
    createElement: fakeElement,
  };
  const PR = { t: (s) => s, esc: String, lang: "zh-TW", emit() {}, api: async (url, opts) => { calls.push([url, opts]); return { status: "created", id: "w1" }; } };
  const ctx = { window: { PR, addEventListener() {} }, document, URL, PR };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../easyread/web/js/common/ingest.js"), "utf8"), ctx);
  const realOpen = PR.openIngest;
  PR.openIngest = (url) => opened.push(url);
  const paste = (text, target) => {
    let prevented = false;
    const e = { target: target || body, clipboardData: { getData: () => text }, preventDefault() { prevented = true; } };
    listeners.paste.forEach((fn) => fn(e));
    return prevented;
  };
  return { PR, bar, importBtn, opened, paste, document, realOpen, calls };
}

test("news URLs are recognised; papers, PDFs and plain text are not", () => {
  const { PR } = setup();
  for (const ok of ["https://news.example.com/a/b?x=1", "http://example.com/story"]) assert.equal(PR.isNewsUrl(ok), true, ok);
  for (const no of ["", "hello world", "https://arxiv.org/abs/2411.00640", "https://doi.org/10.1/x", "https://example.com/report.pdf",
    "ftp://example.com/x", "https://example.com/a b", "https://example.com/" + "a".repeat(2001), "javascript:alert(1)"]) {
    assert.equal(PR.isNewsUrl(no), false, no);
  }
});

test("the paste-URL button is added to the top bar once, before the paper import button", () => {
  const { bar, importBtn } = setup();
  const buttons = bar.children.filter((c) => "ingestOpen" in c.dataset);
  assert.equal(buttons.length, 1);
  assert.ok(bar.children.indexOf(buttons[0]) < bar.children.indexOf(importBtn));
  assert.equal(buttons[0].textContent, "＋ 貼網址");
});

test("Ctrl+V of a news URL outside inputs opens ingest", () => {
  const { paste, opened } = setup();
  assert.equal(paste("  https://news.example.com/x  "), true);
  assert.deepEqual(opened, ["https://news.example.com/x"]);
});

test("pasting inside an input or textarea is left alone", () => {
  const { paste, opened, document } = setup();
  const input = fakeElement("input");
  input.editable = true;
  assert.equal(paste("https://news.example.com/x", input), false);
  document.activeElement = input;  // 焦點在輸入框、事件目標是 body 也一樣
  assert.equal(paste("https://news.example.com/x"), false);
  assert.deepEqual(opened, []);
});

test("pasting text that is not a news URL is left alone", () => {
  const { paste, opened } = setup();
  assert.equal(paste("2411.00640"), false);
  assert.equal(paste("just some words"), false);
  assert.deepEqual(opened, []);
});

/* 對話框的行為：用一個小型的假 DOM（每個 #id 是一個固定的槽，shell() 重畫時清空），不解析 HTML */
function dialogSetup(api) {
  const listeners = {};
  const winListeners = {};
  const slots = {};
  let document = null;
  const el = (extra) => {
    const base = {
      hidden: false, inert: false, disabled: false, attrs: {}, isConnected: true, html: "", listeners: {},
      classList: { set: new Set(), add(c) { this.set.add(c); }, remove(c) { this.set.delete(c); }, contains(c) { return this.set.has(c); } },
      addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); },
      setAttribute(k, v) { this.attrs[k] = v; },
      getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; },
      focus() { document.activeElement = this; },
      blur() { if (document.activeElement === this) document.activeElement = document.body; },
      closest() { return null; },
      querySelectorAll() { return []; },
    };
    Object.defineProperty(base, "innerHTML", { get() { return this.html; }, set(v) { this.html = v; }, configurable: true });
    return Object.assign(base, extra || {});
  };
  const slot = (id) => slots[id] || (slots[id] = el({ id, querySelector(sel) { return sel === "form" && this.html.includes("<form") ? {} : null; } }));
  const inner = el({
    querySelector(sel) { return sel.startsWith("#") ? slot(sel.slice(1)) : null; },
    contains(x) { return Object.values(slots).includes(x) || x === inner; },
  });
  Object.defineProperty(inner, "innerHTML", {
    get() { return this.html; },
    set(v) { Object.values(slots).forEach((s) => { s.html = ""; }); this.html = v; slot("ingestUrl").value = ""; },
  });
  const box = el({ querySelector: () => inner, contains: (x) => inner.contains(x) });
  const body = el({ appendChild() {} });
  const opener = el({});
  document = {
    readyState: "complete", body, activeElement: opener,
    addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
    querySelector: () => null,
    createElement: () => box,
  };
  const PR = { t: (s) => s, esc: String, lang: "zh-TW", emit() {}, api };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../easyread/web/js/common/ingest.js"), "utf8"), { window: { PR, addEventListener(type, fn, capture) { (winListeners[type] = winListeners[type] || []).push([fn, capture]); } }, document, URL, PR });
  const click = (act) => box.listeners.click.forEach((fn) => fn({ target: { closest: () => ({ dataset: { act } }) } }));
  const submitManual = (fields) => {
    const elements = Object.fromEntries(["title", "publisher", "published_at", "url", "text"].map((k) => [k, { value: fields[k] || "" }]));
    box.listeners.submit.forEach((fn) => fn({ preventDefault() {}, target: { closest: () => ({ dataset: { form: "manual" }, elements }) } }));
  };
  const keydown = (key) => {
    const e = { key, stopped: false, preventDefault() {}, stopPropagation() { this.stopped = true; } };
    winListeners.keydown.forEach(([fn, capture]) => { assert.equal(capture, true, "listens in the capture phase"); fn(e); });
    return e;
  };
  return { PR, box, inner, slot, opener, document, click, submitManual, keydown };
}
const tick = () => new Promise((r) => setImmediate(r));
const fail = (kind, error) => Promise.reject(Object.assign(new Error(error), { data: { kind, error } }));

test("a failed manual import keeps the pasted text and is titled by kind", async () => {
  const bodies = [];
  const { PR, slot, click, submitManual } = dialogSetup((url, opts) => { bodies.push(opts.body); return fail("bad_input", "fixed message"); });
  PR.openIngest("");
  click("manual");
  assert.match(slot("ingestManual").innerHTML, /<form/);
  submitManual({ text: "Example full text.", url: "https://news.example.com/x" });
  await tick();
  assert.match(slot("ingestManual").innerHTML, /<form/, "the manual form is still there");
  assert.match(slot("ingestMsg").innerHTML, /沒有匯入/);
  assert.doesNotMatch(slot("ingestMsg").innerHTML, /抓不到這頁|改成手動貼全文/);
  assert.doesNotMatch(slot("ingestMsg").innerHTML, /data-act="retry"/, "bad_input cannot be retried");
  assert.equal(bodies[0].text, "Example full text.");
});

test("retry resends the last request body", async () => {
  const bodies = [];
  const { PR, slot, click, submitManual } = dialogSetup((url, opts) => { bodies.push(opts.body); return fail("timeout", "fixed"); });
  PR.openIngest("https://news.example.com/x");
  await tick();
  assert.match(slot("ingestMsg").innerHTML, /抓不到這頁/);
  assert.match(slot("ingestMsg").innerHTML, /data-act="retry"/);
  click("retry");
  await tick();
  click("manual");
  submitManual({ text: "Example manual text." });
  await tick();
  click("retry");
  await tick();
  assert.deepEqual(bodies.map((b) => b.url || b.text),
    ["https://news.example.com/x", "https://news.example.com/x", "Example manual text.", "Example manual text."]);
});

test("a late response does not overwrite a newer one", async () => {
  const pending = [];
  const { PR, slot } = dialogSetup(() => new Promise((resolve) => pending.push(resolve)));
  PR.openIngest("https://news.example.com/old");
  PR.closeIngest();
  PR.openIngest("https://news.example.com/new");
  pending[1]({ status: "created", id: "wnew", title: "New example" });
  await tick();
  pending[0]({ status: "created", id: "wold", title: "Old example" });
  await tick();
  assert.match(slot("ingestOut").innerHTML, /New example/);
  assert.doesNotMatch(slot("ingestOut").innerHTML, /Old example/);
});

test("closing hides the dialog and gives focus back", () => {
  const { PR, box, slot, opener, document, keydown } = dialogSetup(async () => ({}));
  PR.openIngest("");
  assert.equal(box.hidden, false);
  assert.equal(document.activeElement, slot("ingestUrl"), "focus moves into the dialog");
  assert.equal(keydown("Enter").stopped, true, "page shortcuts do not see keys while the dialog is open");
  assert.match(box.className, /dialog-backdrop/, "pages see it as an open dialog");
  keydown("Escape");
  assert.equal(box.hidden, true);
  assert.equal(keydown("Enter").stopped, false, "keys reach the page again after closing");
  assert.equal(box.inert, true);
  assert.equal(document.activeElement, opener);
});

test("opening by paste moves focus into the dialog and marks it busy", () => {
  const { PR, inner, document } = dialogSetup(() => new Promise(() => {}));
  PR.openIngest("https://news.example.com/x");
  assert.equal(document.activeElement, inner);
  assert.equal(inner.getAttribute("aria-busy"), "true");
});

test("closing during a request and reopening leaves the dialog usable", async () => {
  const calls = [];
  const { PR, inner, slot } = dialogSetup((url, opts) => { calls.push(opts.body); return calls.length === 1 ? new Promise(() => {}) : Promise.resolve({ status: "created", id: "w2", title: "Second example" }); });
  PR.openIngest("https://news.example.com/slow");
  assert.equal(inner.getAttribute("aria-busy"), "true");
  PR.closeIngest();
  PR.openIngest("");
  assert.equal(inner.getAttribute("aria-busy"), "false");
  PR.openIngest("https://news.example.com/second");
  await tick();
  assert.match(slot("ingestOut").innerHTML, /Second example/);
  assert.equal(inner.getAttribute("aria-busy"), "false");
});
