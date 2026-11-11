// 沒有 PDF 的資料（ticket 08）：閱讀器關掉原頁面板，PDF 照舊。
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

function load(kind, features) {
  const PR = {
    ls: { get: (key) => (key === "easyread-ui" ? { features: features || {} } : {}), set() {} },
    t: (s) => s, emit() {}, on() {},
    state: { paper: { meta: kind ? { kind } : {} } },
  };
  const code = fs.readFileSync(path.join(__dirname, "../easyread/web/js/common/features.js"), "utf8");
  vm.runInNewContext(code, { window: { PR }, Object, Set, document: { addEventListener() {} } });
  return PR;
}

test("a text item has no original-page panel", () => {
  const PR = load("text");
  assert.equal(PR.noPdf(), true);
  assert.equal(PR.feature("pages"), false);
  assert.equal(PR.feature("chat"), true);  // 其他功能照舊
  assert.equal(PR.feature("edit"), true);
});

test("a PDF keeps the panel and the user's switch still applies", () => {
  assert.equal(load(undefined).feature("pages"), true);
  assert.equal(load("pdf").feature("pages"), true);
  assert.equal(load(undefined, { pages: false }).feature("pages"), false);
  assert.equal(load("text", { pages: true }).feature("pages"), false);
});

test("pages outside the reader (no paper loaded) are not treated as text", () => {
  const PR = load(undefined);
  PR.state = undefined;
  assert.equal(PR.noPdf(), false);
  assert.equal(PR.feature("pages"), true);
});
