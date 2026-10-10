const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "../easyread/web/js/reader/notespanel.js"), "utf8");

function loadReader({ notes, blocks, entries = [] }) {
  const noopNode = { addEventListener() {}, classList: { add() {}, remove() {} }, contains() { return false; } };
  const PR = {
    state: { paper: { meta: {}, blocks }, reader: { notes }, discussion: { entries } },
    ls: { get: (_key, fallback) => fallback, set() {} },
    $: () => noopNode,
    $$: () => [],
    on() {},
    t: (text, values) => values ? text.replace(/\{(\w+)\}/g, (_match, key) => values[key]) : text,
    myNotes: () => Object.values(notes).filter((note) => !note.deleted),
    anchorOfEntry: (entry) => entry.anchor || "head",
    order: {},
    blockById: Object.fromEntries(blocks.map((block) => [block.id, block])),
    editOf: () => null,
    plain: (text) => text || "",
    textFor: (id) => PR.blockById[id]?.zh || "",
    esc: (text) => String(text || ""),
    mdBlocks: (text) => text,
    HL_COLORS: [["yellow", "黃"], ["green", "綠"], ["blue", "藍"], ["pink", "紅"]],
    debounce: (fn) => { fn.flush = fn; fn.cancel = () => {}; return fn; },
  };
  vm.runInNewContext(source, { window: { PR }, document: { querySelector() { return noopNode; }, querySelectorAll() { return []; } } });
  return PR;
}

test("export includes Chinese quote for accepted smart highlights and legacy English highlights", () => {
  const blocks = [{
    id: "p1", type: "para", en: "We propose a method. It is fast.", zh: "我們提出一個方法。它很快。",
    sents: [[20, 9], [34, 15]],
  }];
  const PR = loadReader({ blocks, notes: {
    smart: { id: "smart", anchor: "p1", key: "p1", quote: "我們提出一個方法。", side: "zh", kind: "highlight", body: "提出可介接不同前端的解碼器。", ai_generated: true },
    legacy: { id: "legacy", anchor: "p1", key: "p1", quote: "It is fast.", kind: "highlight" },
  } });
  const markdown = PR.notesMarkdown({ paper: false, note: false, highlight: true, question: false, ai: false, chat: false, quote: true }, [], { order: ["highlight"], chat: [] });
  assert.match(markdown, /「我們提出一個方法。」/);
  assert.match(markdown, /「它很快。」/);
  assert.match(markdown, /引用（中文譯文）/);
  assert.match(markdown, /我的注記：\*\* 提出可介接不同前端的解碼器/);
});

test("page-side AI explanations do not gain a quote from the export checkbox", () => {
  const PR = loadReader({ blocks: [{ id: "p1", type: "para", en: "Original", zh: "譯文" }], notes: {}, entries: [
    { id: "answer", anchor: "p1", quote: "原文", body: "說明", kind: "reply" },
  ] });
  const markdown = PR.notesMarkdown({ paper: false, note: false, highlight: false, question: false, ai: true, chat: false, quote: true }, [], { order: ["ai"], chat: [] });
  assert.ok(!markdown.includes("「原文」"));
  assert.match(markdown, /說明/);
});
