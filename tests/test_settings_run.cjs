/* Ticket 66：設定頁「背景執行」區（版本、安裝版的開機自動啟動）。 */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

function load() {
  const PR = {
    t: (s) => s,
    esc: (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"),
    $: () => null,
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../easyread/web/js/settings/run.js"), "utf8"),
    { window: { PR }, document: { addEventListener() {} } });
  return PR.settingsRun;
}
const R = load();
const same = (a, b) => assert.equal(JSON.stringify(a), JSON.stringify(b));  // vm 裡的物件跨 realm，用 JSON 比

test("the installer shows a real switch for starting at login", () => {
  const on = R.html({ version: "1.5.2", kind: "installer", login: { supported: true, enabled: true } });
  assert.match(on, /<input type="checkbox" class="switch" role="switch" id="f-autostart" checked>/);
  assert.match(on, /開機自動啟動/);
  assert.match(on, /NewsRead 1\.5\.2 · Windows 安裝版/);
  const busy = R.html({ version: "1.5.2", kind: "installer", login: { supported: true, enabled: false } }, true);
  assert.match(busy, /id="f-autostart" disabled>/);
});

test("other versions explain where autostart lives instead of showing a switch", () => {
  const src = R.html({ version: "1.5.2", kind: "browser", login: null });
  assert.doesNotMatch(src, /checkbox/);
  assert.match(src, /easyread autostart on/);
  assert.match(src, /NewsRead 1\.5\.2 · 原始碼版/);
  const mac = R.html({ version: "", kind: "desktop", login: { supported: false, enabled: false } });
  assert.match(mac, /Windows 安裝版才有這個開關/);
  assert.match(mac, /<span data-no-i18n>桌面版<\/span>/);
  assert.match(R.html({ version: "<b>", kind: "browser", login: null }), /NewsRead &lt;b&gt;/);
});

test("read() uses the backend version and the desktop bridge when present", async () => {
  const api = async (p) => { assert.equal(p, "/api/version"); return { api: 1, version: "1.5.2" }; };
  same(await R.read(api, undefined), { version: "1.5.2", kind: "browser", login: null });
  same(await R.read(api, { loginItem: async () => ({ supported: true, enabled: false }) }),
    { version: "1.5.2", kind: "installer", login: { supported: true, enabled: false } });
  same(await R.read(async () => { throw new Error("down"); }, { loginItem: async () => { throw new Error("ipc"); } }),
    { version: "", kind: "desktop", login: null });
  same(await R.read(api, { loginItem: async () => ({ supported: "yes" }) }),
    { version: "1.5.2", kind: "desktop", login: null });
});

test("toggle() returns the confirmed state, or null when the main process refuses", async () => {
  const calls = [];
  const bridge = { setLoginItem: async (on) => { calls.push(on); return { supported: true, enabled: on }; } };
  same(await R.toggle(bridge, true), { supported: true, enabled: true });
  assert.deepEqual(calls, [true]);
  assert.equal(await R.toggle({ setLoginItem: async () => { throw new Error("no"); } }, true), null);
  assert.equal(await R.toggle({ setLoginItem: async () => ({}) }, false), null);
});

test("the settings page draws the clicked state while waiting and reverts on failure", async () => {
  const listeners = {}, view = { innerHTML: "", addEventListener(type, fn) { listeners[type] = fn; } };
  let ready, answer;
  const PR = {
    t: (s) => s, esc: (s) => String(s), toasts: [],
    $: (sel) => (sel === "#run-view" ? view : null),
    api: async () => ({ api: 1, version: "1.5.2" }),
    toast(msg) { this.toasts.push(msg); },
  };
  const bridge = { loginItem: async () => ({ supported: true, enabled: false }), setLoginItem: () => new Promise((resolve) => { answer = resolve; }) };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../easyread/web/js/settings/run.js"), "utf8"),
    { window: { PR, easyreadDesktop: bridge }, document: { addEventListener(_t, fn) { ready = fn; } } });
  ready();
  await new Promise((resolve) => setImmediate(resolve));
  assert.doesNotMatch(view.innerHTML, / checked/);
  const pending = listeners.change({ target: { id: "f-autostart", checked: true } });
  assert.match(view.innerHTML, /id="f-autostart" checked disabled>/);  // 不閃回去
  answer(null);  // 主程序沒確認
  await pending;
  assert.doesNotMatch(view.innerHTML, / checked/);
  assert.deepEqual(PR.toasts, ["沒有改成功，請再試一次。"]);
});
