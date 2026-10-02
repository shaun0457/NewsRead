const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

test("page limit options include a translated page unit and keep numeric values", () => {
  const PR = {
    settingsTabs: {}, esc: String, icon: () => "", $: () => ({ addEventListener() {} }),
    t: (key, args = {}) => key === "{n} 页" ? args.n + " pages" : key,
    opt: (items, selected) => items.map(([value, label]) => '<option value="' + value + '"' +
      (value === selected ? " selected" : "") + '>' + label + '</option>').join(""),
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../easyread/web/js/common/settings-chat.js"), "utf8"), { window: { PR } });
  const state = { pinned: true, transChecked: true, cfg: { engine: "claude", claude: {}, page_cap: 60 }, chat: { models: [] } };
  const html = PR.settingsTabs.chat.render(state);
  const options = html.match(/data-k="page_cap">([\s\S]*?)<\/select>/)[1];
  for (const limit of [30, 60, 100, 200]) {
    assert.match(options, new RegExp('value="' + limit + '"(?: selected)?>' + limit + ' pages<'));
  }
  assert.match(options, /value="60" selected/);
  assert.match(options, /value="0">/);
});
