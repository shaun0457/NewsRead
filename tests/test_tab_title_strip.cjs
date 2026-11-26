// 分頁標題去掉「 · NewsRead」這類產品名後綴（ticket 06）；標題裡剛好有 newsreader 這種字不能被切掉。
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");

const src = fs.readFileSync(path.join(__dirname, "../easyread/web/js/tabs.js"), "utf8");
const found = src.split(/\r?\n/)
  .filter((line) => line.includes("(NewsRead|PaperRead|EasyRead)"))
  .map((line) => line.slice(line.indexOf(".replace(/") + ".replace(".length, line.indexOf("/i,") + 2));

test("both title-strip regexes in tabs.js keep words that start with the product name", () => {
  assert.equal(found.length, 2);
  for (const literal of found) {
    const re = new Function("return " + literal)();  // 來源是 repo 裡的 tabs.js
    const strip = (t) => t.replace(re, "");
    assert.equal(strip("Example story · NewsRead"), "Example story");
    assert.equal(strip("Old example · PaperRead"), "Old example");
    assert.equal(strip("Paper | EasyRead"), "Paper");
    assert.equal(strip("BBC – Newsreader quits after 30 years · NewsRead"), "BBC – Newsreader quits after 30 years");
  }
});
