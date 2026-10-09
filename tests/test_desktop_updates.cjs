const { test } = require("node:test");
const assert = require("node:assert/strict");
const { EventEmitter } = require("node:events");
const { registerUpdates } = require("../electron/desktop-updates.cjs");

function fixture() {
  const handlers = {};
  const updater = new EventEmitter();
  const calls = [];
  const feeds = [];
  updater.setFeedURL = value => feeds.push(value);
  updater.checkForUpdates = async () => ({ isUpdateAvailable: true, updateInfo: { version: "1.3.2" } });
  updater.downloadUpdate = async () => { calls.push("download"); updater.emit("update-downloaded", { version: "1.3.2" }); };
  updater.quitAndInstall = (...args) => calls.push(["install", ...args]);
  registerUpdates({
    app: { isPackaged: true }, updater,
    ipcMain: { handle: (name, fn) => { handlers[name] = fn; } },
    trustedWindow: event => { if (event !== "trusted") throw Error("Untrusted"); },
    repository: "example/research-os",
    getWindow: () => null,
    prepareInstall: async () => { calls.push("shutdown"); },
    recover: async () => { calls.push("recover"); },
  });
  return { updater, calls, feeds, run: (name, event = "trusted") => handlers[`easyread:update-${name}`](event) };
}

test("download waits for user to install, and stops backend before silent relaunch", { skip: process.platform !== "win32" }, async () => {
  const f = fixture();
  assert.equal(f.updater.autoDownload, false);
  assert.equal(f.updater.autoInstallOnAppQuit, false);
  assert.equal((await f.run("download")).phase, "downloaded");
  assert.deepEqual(f.calls, ["download"]);
  await f.run("install");
  assert.deepEqual(f.calls, ["download", "shutdown", ["install", true, true]]);
});

test("failed download can retry", { skip: process.platform !== "win32" }, async () => {
  const f = fixture();
  const download = f.updater.downloadUpdate;
  f.updater.downloadUpdate = async () => { throw Error("offline"); };
  assert.equal((await f.run("download")).phase, "error");
  f.updater.downloadUpdate = download;
  assert.equal((await f.run("download")).phase, "downloaded");
});

test("no available update does not download; install without download does nothing", async () => {
  const f = fixture();
  f.updater.checkForUpdates = async () => ({ isUpdateAvailable: false });
  await f.run("download");
  await f.run("install");
  assert.deepEqual(f.calls, []);
});

test("unconfigured fork leaves desktop auto-update disabled", async () => {
  const handlers = {};
  const updater = new EventEmitter();
  updater.setFeedURL = () => assert.fail("must not configure an upstream feed");
  registerUpdates({ app: { isPackaged: true }, updater,
    ipcMain: { handle: (name, fn) => { handlers[name] = fn; } },
    trustedWindow: () => {}, getWindow: () => null, prepareInstall: async () => {}, recover: async () => {} });
  const state = await handlers["easyread:update-state"]("trusted");
  assert.equal(state.supported, false);
  assert.equal((await handlers["easyread:update-download"]("trusted")).phase, "idle");
});

test("configured repository is the only desktop update feed", () => {
  const f = fixture();
  if (process.platform === "win32") {
    assert.deepEqual(f.feeds[0], { provider: "github", owner: "example", repo: "research-os" });
  } else {
    // Desktop auto-update is intentionally Windows-only; other platforms
    // must not configure an electron-updater feed at all.
    assert.deepEqual(f.feeds, []);
  }
});

test("untrusted renderer cannot invoke update operations", async () => {
  const f = fixture();
  assert.throws(() => f.run("state", "foreign"), /Untrusted/);
  await assert.rejects(f.run("download", "foreign"), /Untrusted/);
  await assert.rejects(f.run("install", "foreign"), /Untrusted/);
});

test("concurrent downloads are coalesced", { skip: process.platform !== "win32" }, async () => {
  const f = fixture();
  await Promise.all([f.run("download"), f.run("download")]);
  assert.deepEqual(f.calls, ["download"]);
});
