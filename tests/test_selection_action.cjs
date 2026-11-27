// 選取文字之後的浮動條（ticket 76）：劃線、筆記、提問、論文筆記，以及按鈕和快捷鍵兩個入口。
// main.js 的快捷鍵（1–4、n、q）直接呼叫 PR.selectionAction(kind, color)，這裡用同樣的呼叫釘住。
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

function setup() {
  const calls = { save: [], start: [], paperNote: 0, sources: [] };
  const docListeners = {};
  const barListeners = {};
  const classes = new Set();
  const bar = {
    classList: { add: (c) => classes.add(c), remove: (c) => classes.delete(c), contains: (c) => classes.has(c) },
    innerHTML: "", offsetWidth: 200, style: {},
    addEventListener: (type, fn) => (barListeners[type] = barListeners[type] || []).push(fn),
  };
  const blk = { dataset: { id: "p1" } };
  const el = {
    classList: { contains: () => false }, dataset: { key: "p1" },
    closest: (sel) => (sel.includes(".zh") ? el : sel === ".blk" ? blk : null),
    contains: (node) => node === text, querySelector: () => null,
  };
  const text = { nodeType: 3, data: "Chip stocks rallied today.", parentElement: el };
  const range = { startContainer: text, startOffset: 5, endContainer: text, endOffset: 19, intersectsNode: () => false,
    getBoundingClientRect: () => ({ left: 10, top: 200, width: 50, bottom: 220 }) };
  let selected = true;
  const selection = { get isCollapsed() { return !selected; }, get rangeCount() { return selected ? 1 : 0; },
    getRangeAt: () => range, removeAllRanges: () => { selected = false; }, toString: () => (selected ? "stocks rallied" : "") };
  const PR = {
    state: { reader: { notes: {} } }, blockById: {}, prefs: { pen: "marker", penColors: {} }, keysOn: true,
    HL_COLORS: [["yellow", "黃"], ["green", "綠"], ["blue", "藍"], ["pink", "粉"]],
    $: (sel) => (sel === "#selbar" ? bar : null), $$: () => [],
    t: (s) => s, icon: () => "", feature: () => true, canChat: () => false, debounce: (fn) => fn,
    hideBlockbar() {}, zhOfEl: (x) => x, isEnEl: () => false, applyPrefs() {}, toast() {}, markNote() {},
    uid: (p) => p + "1", nowIso: () => "2026-11-12T00:00:00Z",
    saveNote: (n) => calls.save.push(n), startNote: (n) => calls.start.push(n),
    openPaperNote: () => { calls.paperNote += 1; },
    paperNoteEditor: { insertSources: (parts) => calls.sources.push(parts) },
  };
  const document = {
    addEventListener: (type, fn) => (docListeners[type] = docListeners[type] || []).push(fn),
    getElementById: () => null,
    createTreeWalker: (root, what, filter) => {
      const nodes = [text].filter((n) => root.contains(n) && filter.acceptNode(n) === 1);
      let i = 0;
      return { nextNode: () => nodes[i++] || null };
    },
  };
  const ctx = { PR, document, NodeFilter: { SHOW_TEXT: 4, FILTER_ACCEPT: 1, FILTER_REJECT: 2 }, innerWidth: 1000,
    setTimeout: (fn) => fn(), getSelection: () => selection, navigator: {} };
  ctx.window = ctx;
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../easyread/web/js/reader/anchor.js"), "utf8"), ctx);
  const select = () => { selected = true; (docListeners.mouseup || []).forEach((fn) => fn({ target: el })); };
  const click = (target) => barListeners.click.forEach((fn) => fn({ target }));
  return { PR, calls, select, click, bar, classes, docListeners };
}

test("selecting text opens the bar with the paper-note button", () => {
  const { select, bar, classes } = setup();
  select();
  assert.ok(classes.has("open"));
  assert.match(bar.innerHTML, /data-s="paper-note"/);
  assert.match(bar.innerHTML, /data-s="question"/);
});

test("colour shortcut highlights the selection in that colour and remembers it", () => {
  const { PR, calls, select, classes } = setup();
  select();
  PR.selectionAction("highlight", "green");
  assert.equal(calls.save.length, 1);
  const note = calls.save[0];
  assert.deepEqual([note.kind, note.color, note.anchor, note.key, note.quote], ["highlight", "green", "p1", "p1", "stocks rallied"]);
  assert.equal(note.prefix, "Chip ");
  assert.equal(PR.prefs.penColors.marker, "green");
  assert.equal(classes.has("open"), false);
  PR.selectionAction("highlight", "blue");  // 選區用掉了，再按不會多一筆
  assert.equal(calls.save.length, 1);
});

test("n and q start a note or a question on the selection", () => {
  for (const kind of ["note", "question"]) {
    const { PR, calls, select } = setup();
    select();
    PR.selectionAction(kind);
    assert.equal(calls.save.length, 0);
    assert.equal(calls.start.length, 1);
    assert.equal(calls.start[0].kind, kind);
    assert.equal(calls.start[0].quote, "stocks rallied");
  }
});

test("bar buttons: colour dot, pen and note go through the same action", () => {
  const { calls, select, click, PR } = setup();
  const button = (dataset) => ({ closest: (sel) => (sel === "button[data-s]" && dataset.s ? { dataset } : sel === "[data-pen]" && dataset.pen ? { dataset } : null) });
  select();
  click(button({ s: "highlight", color: "pink" }));
  assert.equal(calls.save[0].color, "pink");
  select();
  click(button({ pen: "underline" }));
  assert.equal(PR.prefs.pen, "underline");
  assert.equal(calls.save[1].style, "underline");
  select();
  click(button({ s: "note" }));
  assert.equal(calls.start[0].kind, "note");
});

test("the paper-note button quotes the selection into the paper note", () => {
  const { PR, calls, select } = setup();
  select();
  PR.selectionAction("paper-note");
  assert.equal(calls.paperNote, 1);
  assert.deepEqual(JSON.parse(JSON.stringify(calls.sources)), [[{ anchor: "p1", quote: "stocks rallied" }]]);
  assert.equal(calls.start.length, 0);  // 不會變成一則 kind 是 paper-note 的筆記
  assert.equal(calls.save.length, 0);
});

test("selection listeners are registered once", () => {
  const { docListeners } = setup();
  assert.equal(docListeners.mouseup.length, 1);
  assert.equal(docListeners.keyup.length, 1);
  assert.equal(docListeners.selectionchange.length, 1);
});
