const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

function searchReader() {
  let keydown, focused = null;
  const previous = { isConnected: true, focus() { focused = "previous"; } };
  const input = { value: "", focus() { focused = "search"; }, select() {}, blur() { focused = null; } };
  const nodes = { input, ".find-count": {}, "[data-prev]": {}, "[data-next]": {}, "[data-close]": {} };
  const panel = { hidden: true, querySelector: s => nodes[s], contains: n => n === input };
  const PR = { el: () => panel, t: s => s, $$: () => [], on() {} };
  const document = { body: { append() {} }, activeElement: previous,
    querySelector: () => null, addEventListener(type, fn) { if (type === "keydown") keydown = fn; } };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../easyread/web/js/reader/find.js"), "utf8"), { window: { PR }, document });
  return { panel, input, previous, focused: () => focused, press(key, modifiers = {}) {
    const event = { key, target: input, preventDefault() { this.prevented = true; }, stopImmediatePropagation() {}, ...modifiers };
    keydown(event); return event;
  } };
}

test("Ctrl+F and Command+F open reader search without a toolbar button", () => {
  for (const modifier of ["ctrlKey", "metaKey"]) {
    const r = searchReader();
    assert.equal(r.press("f", { [modifier]: true }).prevented, true);
    assert.equal(r.panel.hidden, false);
    assert.equal(r.focused(), "search");
  }
});

test("Escape closes reader search and restores the previous focus", () => {
  const r = searchReader();
  r.press("f", { ctrlKey: true });
  r.press("f", { ctrlKey: true });
  r.press("Escape");
  assert.equal(r.panel.hidden, true);
  assert.equal(r.focused(), "previous");
});

test("closing search handles a removed focus target", () => {
  const r = searchReader();
  r.press("f", { metaKey: true });
  r.previous.isConnected = false;
  r.press("Escape");
  assert.equal(r.panel.hidden, true);
  assert.equal(r.focused(), null);
});
