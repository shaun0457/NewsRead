const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

function setup(confirm = true) {
  const calls = [], s = { tab: "cloud", cloud: { path: "C:/library", papers: 3, bytes: 1024, candidates: [] } };
  const PR = {
    settingsState: s, settingsTabs: {}, settingsRender() {}, toast() {}, icon: () => "",
    t: (text, vars = {}) => text.replace(/\{(\w+)\}/g, (_, k) => vars[k]),
    esc: (text) => String(text).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll('"', "&quot;"),
    confirm: async (args) => { calls.push(["confirm", args]); return confirm; },
    migrateDialog: async (args) => { calls.push(["confirm", args]); return confirm; },
    api: async (url, opts) => {
      calls.push([url, opts]);
      if (url.endsWith("location")) return s.cloud;
      if (url.endsWith("inspect")) return { path: "D:/sync/EasyRead", papers: 2, writable: true };
      if (url.endsWith("move")) return { ok: true, old_path: "C:/library", message: "Restart" };
    },
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../easyread/web/js/library/settings-cloud.js"), "utf8"), { window: { PR } });
  PR.libraryLocationNotice = (data) => calls.push(["notice", data]);
  const click = (action) => PR.settingsTabs.cloud.click({ target: { closest: () => ({ dataset: { cloud: action, path: "D:/sync/EasyRead" } }) } }, s);
  return { PR, s, calls, click };
}

test("cloud destinations offer copy for empty folders and use/merge for existing papers", () => {
  const { PR, s } = setup();
  s.cloud.candidates = [{ path: "D:/empty", papers: 0, writable: true }, { path: "D:/existing", papers: 2, writable: true }];
  const html = PR.settingsTabs.cloud.render(s);
  assert.match(html, /data-cloud="copy" data-path="D:\/empty"/);
  assert.match(html, /data-cloud="use" data-path="D:\/existing"/);
  assert.match(html, /data-cloud="merge" data-path="D:\/existing"/);
  s.cloud.temp = true;
  assert.match(PR.settingsTabs.cloud.render(s), /data-cloud="copy"[^>]*disabled/);
});

test("cloud merge requires confirmation and locks further changes until restart", async () => {
  const { PR, s, calls, click } = setup();
  await click("merge");
  const move = calls.find(([url]) => url.endsWith("/move"));
  assert.equal(move[1].body.mode, "merge");
  assert.equal(move[1].body.path, "D:/sync/EasyRead");
  assert.ok(calls.findIndex(([url]) => url === "confirm") < calls.indexOf(move));
  assert.equal(s.cloud.restart_required, true);
  assert.match(PR.settingsTabs.cloud.render(s), /Close|请关掉 EasyRead/);
  await click("copy");
  assert.equal(calls.filter(([url]) => url.endsWith("/move")).length, 1);
});

test("cancelled confirmation never changes the library location", async () => {
  const { calls, click } = setup(false);
  await click("use");
  assert.equal(calls.filter(([url]) => url.endsWith("/move")).length, 0);
});

test("cloud settings say where the library is now and keep other drives one click away", () => {
  const { PR, s } = setup();
  for (const candidates of [[], [{ label: "OneDrive", root_path: "D:/OneDrive", path: "D:/OneDrive/EasyRead", papers: 0, writable: true }]]) {
    s.cloud.candidates = candidates;
    const html = PR.settingsTabs.cloud.render(s);
    assert.match(html, /在本机，不会同步/);
    assert.match(html, /坚果云、Google Drive 等：选它们的同步文件夹/);
    assert.match(html, /data-cloud="custom"/);
  }
  s.cloud.path = String.raw`D:\OneDrive\EasyRead`;
  assert.match(PR.settingsTabs.cloud.render(s), /在 OneDrive 里，会自动同步/);
});
