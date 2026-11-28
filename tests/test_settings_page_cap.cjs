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

test("the Claude Code form lists the extra arguments that no-tools work leaves out, escaped", () => {
  const PR = {
    settingsTabs: {}, esc: (s) => String(s).replace(/</g, "&lt;"), icon: () => "", $: () => ({ addEventListener() {} }),
    t: (key, args = {}) => key.replace(/\{(\w+)\}/g, (_, k) => args[k]),
    opt: () => "", cliModelSelect: () => "<select></select>", modelReasoningFields: () => "", cliModelOptions: () => [],
    cliPin: (s, e, m) => m,
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../easyread/web/js/common/settings-chat.js"), "utf8"), { window: { PR } });
  const base = { pinned: true, transChecked: true, cfg: { engine: "claude", claude: {}, page_cap: 60 }, chat: { models: [] },
    presets: [], editing: "new", form: { kind: "claude", model: "" } };
  const html = PR.settingsTabs.chat.render({ ...base, found: { claude: { found: true, no_tools_skipped: ["--mcp-config", "<x>"] } } });
  assert.match(html, /不會帶這些額外參數：--mcp-config &lt;x>/);
  const none = PR.settingsTabs.chat.render({ ...base, found: { claude: { found: true, no_tools_skipped: [] } } });
  assert.doesNotMatch(none, /額外參數/);
});
