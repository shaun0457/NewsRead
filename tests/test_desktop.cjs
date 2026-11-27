const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { EventEmitter } = require("node:events");
const { test } = require("node:test");

async function desktop(platform = "darwin", lock = true, ready = true, argv = [], opts = {}) {
  const app = new EventEmitter();
  Object.assign(app, {
    setPath() {}, getPath: () => "/tmp", getLocale: () => "zh-CN", isPackaged: true,
    requestSingleInstanceLock: () => lock, whenReady: () => Promise.resolve(), isReady: () => true,
    setAsDefaultProtocolClient(scheme) { this.protocol = scheme; },
    quit() { this.quitCalled = true; this.emit("before-quit", { preventDefault() {} }); },
    relaunch() { this.relaunched = true; }, exit() { this.exited = true; },
    getLoginItemSettings(query) { return { openAtLogin: Boolean(this.loginSettings && this.loginSettings.openAtLogin && query.args[0] === this.loginSettings.args[0]) }; },
    setLoginItemSettings(settings) { this.loginSettings = settings; },
  });
  const windows = [], launches = [], menus = [], stages = [], handlers = new Map(), trays = [], errors = [], requests = [], probes = [];
  const ipcMain = new EventEmitter();
  ipcMain.handle = (name, fn) => handlers.set(name, fn);
  class Window extends EventEmitter {
    constructor() {
      super();
      this.webContents = new EventEmitter();
      this.webContents.setWindowOpenHandler = () => {};
      this.webContents.mainFrame = { url: "http://127.0.0.1:9876/" };
      this.webContents.isDestroyed = () => false;
      this.webContents.executeJavaScript = async (code) => {
        const match = String(code).match(/window\.location\.href = ("[^"]+")/);
        if (match) this.url = JSON.parse(match[1]);
      };
      this.webContents.send = channel => { queueMicrotask(() => ipcMain.emit("easyread:page-saved", { sender: this.webContents, senderFrame: this.webContents.mainFrame })); };
      windows.push(this);
    }
    static getAllWindows() { return windows.filter(w => !w.closed); }
    static fromWebContents(wc) { return windows.find(w => w.webContents === wc); }
    getBounds() { return { x: 0, y: 0, width: 1440, height: 960 }; }
    isFullScreen() { return false; }
    isMaximized() { return false; }
    getMinimumSize() { return [960, 680]; }
    setMinimumSize() {}
    setBounds() {}
    async loadURL(url) { this.url = url; }
    show() { this.shown = true; }
    hide() { this.shown = false; }
    focus() { this.focused = true; }
    isMinimized() { return false; }
    isDestroyed() { return Boolean(this.closed); }
    close() { this.closed = true; this.emit("closed"); }
  }
  class Tray extends EventEmitter {
    constructor(icon) {
      super();
      if (opts.trayFails) throw new Error("no tray");
      this.icon = icon;
      trays.push(this);
    }
    setToolTip(tip) { this.tip = tip; }
    setContextMenu(menu) { this.menu = menu; }
  }
  const Menu = {
    buildFromTemplate(items) { return { items, popup() { menus.push(items); } }; },
    setApplicationMenu(menu) { app.menu = menu; },
  };
  const childProcess = {
    execFileSync: () => "__PATH__/usr/bin:/bin__PATH__",
    spawn(command, args, options) {
      const child = new EventEmitter();
      child.stdout = new EventEmitter(); child.stderr = new EventEmitter();
      child.kill = () => { child.killed = true; child.emit("exit", 0, "SIGTERM"); };
      launches.push({ command, args, options, child });
      if (ready) queueMicrotask(() => child.stdout.emit("data", "NewsRead 已啟動：http://127.0.0.1:9876\n"));
      return child;
    },
  };
  const proc = new EventEmitter();
  Object.assign(proc, { platform, env: {}, resourcesPath: "/tmp/Resources", argv: ["EasyRead.exe", ...argv] });
  const fakeRequire = name => name === "electron" ? { app, BrowserWindow: Window, Menu, Tray, ipcMain, screen: { getDisplayMatching: () => ({ workArea: { x: 0, y: 0, width: 2000, height: 1000 } }) }, dialog: { showErrorBox(_title, message) { errors.push(message); }, showOpenDialog: async () => ({ canceled: false, filePaths: ["/tmp/chosen"] }) }, shell: {} }
    : name === "child_process" ? childProcess : name === "fs" ? { existsSync: () => true }
    : name === "http" ? { request(url, options, callback) {
      requests.push(url.pathname);
      const req = new EventEmitter(); req.destroy = () => { req.destroyed = true; };
      req.setTimeout = (ms, onTimeout) => { req.timeoutMs = ms; req.onTimeout = onTimeout; };
      if (url.pathname === "/api/version") {
        const reply = opts.version || "ok";
        req.end = () => queueMicrotask(() => {
          if (reply === "hang") { probes.push(req.timeoutMs); return void req.onTimeout(); }
          if (reply === "refused") return void req.emit("error", new Error("ECONNREFUSED"));
          const res = new EventEmitter(); res.statusCode = reply === "404" ? 404 : 200; res.setEncoding = () => {}; callback(res);
          res.emit("data", reply === "big" ? "x".repeat(5000) : JSON.stringify(reply === "other" ? { ok: true } : { api: 1, version: "1.5.2" }));
          res.emit("end");
        });
        return req;
      }
      req.end = () => queueMicrotask(() => {
        const res = new EventEmitter(); res.statusCode = 200; res.setEncoding = () => {}; callback(res);
        res.emit("data", JSON.stringify(url.pathname === "/api/library" ? { token: "test-token" } : { ok: true }));
        res.emit("end");
        if (url.pathname === "/api/shutdown") launches[launches.length - 1].child.kill();
      }); return req;
    } }
    : name === "./startup-feedback.cjs" ? { ...require("../electron/startup-feedback.cjs"), mark(_app, stage) { stages.push(stage); }, loginShellPath: async () => "/usr/bin:/bin" }
    : name === "./desktop-updates.cjs" ? { registerUpdates() {} }
    : name === "./desktop-tabs.cjs" ? require("../electron/desktop-tabs.cjs")
    : name === "./deep-link.cjs" ? require("../electron/deep-link.cjs")
    : name === "./tray.cjs" ? require("../electron/tray.cjs")
    : name === "electron-updater" ? { autoUpdater: {} }
    : name === "./window-state.cjs" ? { options: () => ({ opts: { width: 1440, height: 960 }, maximized: false }), track() {} }
    : require(name);
  const source = fs.readFileSync(path.join(__dirname, "../electron/main.cjs"), "utf8");
  vm.runInNewContext(source, { require: fakeRequire, process: proc, __dirname: "/tmp/electron", setTimeout, clearTimeout, console });
  const settled = async () => {
    // createWindow awaits several microtask turns: loading screen, backend
    // readiness, and the final navigation.  Drain them so assertions observe
    // the same stable state on every runner.
    for (let i = 0; i < 4; i += 1) await new Promise(resolve => setImmediate(resolve));
  };
  await settled();
  return { app, windows, launches, menus, handlers, stages, settled, trays, errors, requests, ipcMain, probes };
}

test("macOS keeps native editing roles and offers input context actions", async () => {
  const d = await desktop();
  assert.deepEqual(Array.from(d.app.menu.items, x => x.role), ["appMenu", "editMenu", "windowMenu"]);
  d.windows[0].webContents.emit("context-menu", {}, { isEditable: true, selectionText: "", editFlags: { canPaste: true } });
  assert.ok(d.menus[0].some(x => x.role === "paste" && x.enabled));
  d.app.quit();
});

test("reopening a macOS window reuses one backend, even during repeated activation", async () => {
  const d = await desktop();
  d.windows[0].close();
  d.app.emit("activate"); d.app.emit("activate");
  await d.settled();
  assert.equal(d.launches.length, 1);
  assert.equal(d.windows.length, 2);
  d.app.emit("second-instance");
  assert.equal(d.windows[1].focused, true);
  d.app.quit();
  await d.settled();
  assert.equal(d.launches[0].child.killed, true);
});

test("a second app instance exits before starting a backend", async () => {
  const d = await desktop("darwin", false);
  assert.equal(d.app.quitCalled, true);
  assert.equal(d.launches.length, 0);
});

test("Windows retains its existing menu behavior", async () => {
  const d = await desktop("win32");
  assert.equal(d.app.menu, null);
  d.app.quit();
});

test("the startup window is visible while the backend is still starting", async () => {
  const d = await desktop("darwin", true, false);
  assert.equal(d.windows.length, 1);
  assert.equal(d.windows[0].shown, true);
  assert.match(d.windows[0].url, /^data:text\/html/);
  assert.ok(d.stages.indexOf("startup-window-visible") < d.stages.indexOf("backend-spawn"));
  d.launches[0].child.stdout.emit("data", "NewsRead 已啟動：http://127.0.0.1:9876\n");
  await d.settled();
  assert.equal(d.windows[0].url, "http://127.0.0.1:9876/web/tabs.html");
  assert.ok(d.stages.includes("library-loaded"));
  d.app.quit(); await d.settled();
});

test("login shell discovery yields without blocking and tolerates shell errors", async () => {
  const { loginShellPath } = require("../electron/startup-feedback.cjs");
  let callback;
  const pending = loginShellPath("darwin", "/bin/zsh", (_shell, _args, options, done) => {
    assert.equal(options.timeout, 5000); callback = done;
  });
  assert.ok(pending instanceof Promise);
  callback(null, "noise\n__PATH__/usr/local/bin:/usr/bin__PATH__\n");
  assert.equal(await pending, "/usr/local/bin:/usr/bin");
  assert.equal(await loginShellPath("darwin", "/bin/zsh", (_s, _a, _o, done) => done(new Error("timeout"))), "");
  assert.equal(await loginShellPath("win32", "", () => { throw new Error("unexpected shell"); }), "");
});


test("cloud library IPC restricts folder picking and relaunch to the local main frame", async () => {
  const d = await desktop();
  const sender = d.windows[0].webContents;
  const event = { sender, senderFrame: sender.mainFrame };
  assert.equal(await d.handlers.get("easyread:pick-folder")(event), "/tmp/chosen");
  await assert.rejects(d.handlers.get("easyread:pick-folder")({ sender: {}, senderFrame: sender.mainFrame }), /Untrusted/);
  await assert.rejects(d.handlers.get("easyread:pick-folder")({ sender, senderFrame: { url: "https://example.com" } }), /Untrusted/);
  await d.handlers.get("easyread:relaunch")(event);
  assert.equal(d.launches[0].child.killed, true);
  assert.equal(d.app.relaunched, true);
  assert.equal(d.app.exited, true);
});

const SHA = "a".repeat(64);

test("paper links open the paper once the backend is ready", async () => {
  const d = await desktop("win32", true, true, [`easyread://open?sha256=${SHA}&block=p3-2`]);
  await d.settled();
  assert.equal(d.app.protocol, "paperread");
  assert.equal(d.windows[0].url, `http://127.0.0.1:9876/web/tabs.html?open=%2Fopen%3Fsha256%3D${SHA}%26block%3Dp3-2`);
  d.app.quit();
});

test("a link from a second instance reuses the open window", async () => {
  const d = await desktop("win32");
  await d.settled();
  d.app.emit("second-instance", {}, ["EasyRead.exe", "easyread://open?id=abc123def456"]);
  await d.settled();
  assert.equal(d.windows.length, 1);
  assert.equal(d.windows[0].url, "http://127.0.0.1:9876/web/tabs.html?open=%2Fopen%3Fid%3Dabc123def456");
  assert.equal(d.windows[0].focused, true);
  d.app.quit();
});

test("macOS open-url links are handled and unknown links ignored", async () => {
  const d = await desktop();
  await d.settled();
  d.app.emit("open-url", { preventDefault() {} }, "easyread://other?id=abc123def456");
  assert.equal(d.windows[0].url, "http://127.0.0.1:9876/web/tabs.html");
  d.app.emit("open-url", { preventDefault() {} }, `easyread://open?sha256=${SHA}&block=<x>`);
  await d.settled();
  assert.equal(d.windows[0].url, `http://127.0.0.1:9876/web/tabs.html?open=%2Fopen%3Fsha256%3D${SHA}`);
  d.app.quit();
});

/* ---------- ticket 66：系統匣、接手已經在跑的服務、開機啟動 ---------- */
const trayLib = require("../electron/tray.cjs");
const trayItem = (d, label) => d.trays[0].menu.items.find(x => x.label === label);

test("Windows closes to the tray: the backend keeps running until Quit", async () => {
  const d = await desktop("win32");
  assert.equal(d.trays.length, 1);
  assert.equal(d.trays[0].tip, "NewsRead");
  const event = { prevented: false, preventDefault() { this.prevented = true; } };
  d.windows[0].emit("close", event);
  assert.equal(event.prevented, true);
  assert.equal(d.windows[0].shown, false);
  assert.equal(d.app.quitCalled, undefined);
  assert.equal(d.launches[0].child.killed, undefined);
  d.trays[0].emit("click");
  assert.equal(d.windows[0].shown, true);
  assert.equal(d.windows[0].focused, true);
  trayItem(d, trayLib.LABELS.quit).click();
  await d.settled();
  assert.equal(d.app.quitCalled, true);
  assert.deepEqual(d.requests, ["/api/library", "/api/shutdown"]);
  assert.equal(d.launches[0].child.killed, true);
});

test("a second launch shows the hidden window and starts no second backend", async () => {
  const d = await desktop("win32");
  d.windows[0].emit("close", { preventDefault() {} });
  d.app.emit("second-instance", {}, ["NewsRead.exe"]);
  await d.settled();
  assert.equal(d.windows.length, 1);
  assert.equal(d.launches.length, 1);
  assert.equal(d.windows[0].shown, true);
  d.app.emit("second-instance", {}, ["NewsRead.exe", trayLib.HIDDEN_ARG]);  // 開機啟動又跑一次：不跳出視窗
  d.windows[0].hide();
  d.app.emit("second-instance", {}, ["NewsRead.exe", trayLib.HIDDEN_ARG]);
  assert.equal(d.windows[0].shown, false);
  d.app.quit(); await d.settled();
});

test("starting at login stays in the tray with the backend running", async () => {
  const d = await desktop("win32", true, true, [trayLib.HIDDEN_ARG]);
  d.windows[0].emit("ready-to-show");
  assert.equal(d.launches.length, 1);
  assert.equal(d.windows[0].shown, undefined);
  assert.equal(d.windows[0].url, "http://127.0.0.1:9876/web/tabs.html");
  assert.ok(d.stages.includes("startup-hidden"));
  trayItem(d, trayLib.LABELS.open).click();
  assert.equal(d.windows[0].shown, true);
  d.app.quit(); await d.settled();
});

test("without a tray (macOS) the hidden flag is ignored and closing quits as before", async () => {
  const d = await desktop("darwin", true, true, [trayLib.HIDDEN_ARG]);
  assert.equal(d.trays.length, 0);
  assert.equal(d.windows[0].shown, true);
  const l = await desktop("linux");
  const event = { prevented: false, preventDefault() { this.prevented = true; } };
  l.windows[0].emit("close", event);
  await l.settled();
  assert.equal(event.prevented, true);
  assert.equal(l.app.quitCalled, true);
  d.app.quit(); await d.settled();
});

test("a broken tray falls back to closing the app", async () => {
  const d = await desktop("win32", true, true, [trayLib.HIDDEN_ARG], { trayFails: true });
  assert.equal(d.trays.length, 0);
  assert.equal(d.windows[0].shown, true);  // 沒有系統匣就不能藏起來
  d.windows[0].emit("close", { preventDefault() {} });
  await d.settled();
  assert.equal(d.app.quitCalled, true);
});

const RUNNING_LINE = "NewsRead 已經在執行：http://127.0.0.1:8123，不再啟動第二個。要重新啟動請先 easyread stop，或結束那個程序。\n";

test("an already running service is adopted, and quitting leaves it running", async () => {
  const d = await desktop("win32", true, false);
  const child = d.launches[0].child;
  child.stdout.emit("data", RUNNING_LINE);
  child.emit("exit", 3, null);
  child.emit("close", 3, null);
  await d.settled();
  assert.equal(d.windows[0].url, "http://127.0.0.1:8123/web/tabs.html");
  assert.ok(d.stages.includes("backend-adopted"));
  assert.deepEqual(d.errors, []);
  const sender = d.windows[0].webContents;
  sender.mainFrame.url = "http://127.0.0.1:8123/web/tabs.html";
  assert.deepEqual(await d.handlers.get("easyread:login-item")({ sender, senderFrame: sender.mainFrame }), { supported: true, enabled: false });
  let saved = 0;
  sender.send = () => { saved += 1; queueMicrotask(() => d.ipcMain.emit("easyread:page-saved", { sender, senderFrame: sender.mainFrame })); };
  trayItem(d, trayLib.LABELS.quit).click();
  await d.settled();
  assert.equal(saved, 1);  // 頁面照樣先存檔
  assert.deepEqual(d.requests, ["/api/version"]);  // 只確認過它是 NewsRead，不去關別人開的服務
  assert.equal(d.launches.length, 1);
});

test("the running line is read even when it arrives after the exit event", async () => {
  const d = await desktop("win32", true, false);
  const child = d.launches[0].child;
  child.emit("exit", 3, null);
  child.stdout.emit("data", RUNNING_LINE);
  child.emit("close", 3, null);
  await d.settled();
  assert.equal(d.windows[0].url, "http://127.0.0.1:8123/web/tabs.html");
  d.app.quit(); await d.settled();
});

test("waiting for the backend output after exit code 3 is bounded", async () => {
  const d = await desktop("win32", true, false);
  const child = d.launches[0].child;
  child.stdout.emit("data", RUNNING_LINE);
  const started = Date.now();
  child.emit("exit", 3, null);  // 管線一直沒關
  while (!String(d.windows[0].url).startsWith("http://") && Date.now() - started < 5000) {
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  assert.equal(d.windows[0].url, "http://127.0.0.1:8123/web/tabs.html");
  assert.ok(Date.now() - started >= 900);
  d.app.quit(); await d.settled();
});

test("exit code 3 without a local address is an error, not an adoption", async () => {
  for (const line of ["NewsRead 已經在執行，不再啟動第二個。\n", "NewsRead 已經在執行：http://192.168.1.5:8123，不再啟動第二個。\n",
    "NewsRead 已經在執行：http://127.0.0.1:8123@evil.example，不再啟動第二個。\n"]) {
    const d = await desktop("win32", true, false);
    const child = d.launches[0].child;
    child.stdout.emit("data", line);
    child.emit("exit", 3, null);
    child.emit("close", 3, null);
    await d.settled();
    assert.match(d.errors[0], /讀不到它在這台電腦上的位址/);
    assert.equal(d.app.quitCalled, true);
    assert.doesNotMatch(String(d.windows[0].url), /8123/);
  }
});

test("runningUrl only accepts a loopback address with a valid port", () => {
  assert.equal(trayLib.runningUrl(RUNNING_LINE), "http://127.0.0.1:8123");
  assert.equal(trayLib.runningUrl("NewsRead 已经在执行：http://127.0.0.1:65535，不再启动第二个。"), "http://127.0.0.1:65535");
  for (const bad of ["", null, "NewsRead 已經在執行：http://127.0.0.1:0，", "NewsRead 已經在執行：http://127.0.0.1:65536，",
    "NewsRead 已經在執行：http://localhost:8123，", "NewsRead 已經在執行：http://127.0.0.1:8123/x，",
    "NewsRead 已經在執行：http://127.0.0.1:123456，", "NewsRead 已啟動：http://127.0.0.1:8123"]) {
    assert.equal(trayLib.runningUrl(bad), "", String(bad));
  }
  const far = RUNNING_LINE + "x".repeat(trayLib.OUTPUT_MAX);  // 只看最後 OUTPUT_MAX 個字
  assert.equal(trayLib.runningUrl(far), "");
});

test("the login item is set through trusted IPC, only in the Windows installer", async () => {
  const d = await desktop("win32");
  const sender = d.windows[0].webContents;
  const event = { sender, senderFrame: sender.mainFrame };
  assert.deepEqual(await d.handlers.get("easyread:login-item")(event), { supported: true, enabled: false });
  assert.deepEqual(await d.handlers.get("easyread:set-login-item")(event, true), { supported: true, enabled: true });
  assert.deepEqual(d.app.loginSettings, { openAtLogin: true, args: [trayLib.HIDDEN_ARG] });
  await assert.rejects(d.handlers.get("easyread:set-login-item")(event, "yes"), /boolean/);
  await assert.rejects(d.handlers.get("easyread:set-login-item")({ sender: {}, senderFrame: sender.mainFrame }, false), /Untrusted/);
  await assert.rejects(d.handlers.get("easyread:login-item")({ sender, senderFrame: { url: "https://example.com" } }), /Untrusted/);
  assert.equal(d.app.loginSettings.openAtLogin, true);
  d.app.quit(); await d.settled();

  const mac = await desktop("darwin");
  const m = mac.windows[0].webContents;
  assert.deepEqual(await mac.handlers.get("easyread:login-item")({ sender: m, senderFrame: m.mainFrame }), { supported: false, enabled: false });
  await assert.rejects(mac.handlers.get("easyread:set-login-item")({ sender: m, senderFrame: m.mainFrame }, true), /Windows installer/);
  mac.app.quit(); await mac.settled();
  const dev = trayLib.loginItem({ isPackaged: false }, "win32");
  assert.deepEqual(dev.get(), { supported: false, enabled: false });
});

test("an address that is not a live NewsRead is not adopted", async () => {
  for (const version of ["refused", "404", "other", "big", "hang"]) {
    const d = await desktop("win32", true, false, [], { version });
    const child = d.launches[0].child;
    child.stdout.emit("data", RUNNING_LINE);
    child.emit("exit", 3, null);
    child.emit("close", 3, null);
    await d.settled();
    assert.match(d.errors[0] || "", /讀不到它在這台電腦上的位址/, version);
    assert.doesNotMatch(String(d.windows[0].url), /8123/, version);
    assert.equal(d.stages.includes("backend-adopted"), false, version);
    if (version === "hang") assert.deepEqual(d.probes, [3000]);  // 確認那個服務最多等 3 秒
  }
});

test("exit code 3 with no address fails once the output wait runs out", async () => {
  const d = await desktop("win32", true, false);
  const child = d.launches[0].child;
  const started = Date.now();
  child.emit("exit", 3, null);  // 管線一直沒關，也沒有位址
  while (!d.errors.length && Date.now() - started < 5000) await new Promise(resolve => setTimeout(resolve, 50));
  assert.match(d.errors[0], /讀不到它在這台電腦上的位址/);
  assert.ok(Date.now() - started >= 900);
  assert.equal(child.listenerCount("close"), 0);  // 逾時也把 close 的 listener 拿掉
});

test("a link clicked while starting hidden opens the window once the backend is ready", async () => {
  const d = await desktop("win32", true, false, [trayLib.HIDDEN_ARG]);
  d.app.emit("second-instance", {}, ["NewsRead.exe", "easyread://open?id=abc123def456"]);
  assert.equal(d.windows[0].shown, undefined);
  d.launches[0].child.stdout.emit("data", "NewsRead 已啟動：http://127.0.0.1:9876\n");
  await d.settled();
  assert.equal(d.windows[0].url, "http://127.0.0.1:9876/web/tabs.html?open=%2Fopen%3Fid%3Dabc123def456");
  assert.equal(d.windows[0].shown, true);
  d.app.quit(); await d.settled();
});

test("opening from the tray before the hidden window is ready shows it, and later ready-to-show is harmless", async () => {
  const d = await desktop("win32", true, false, [trayLib.HIDDEN_ARG]);
  trayItem(d, trayLib.LABELS.open).click();
  assert.equal(d.windows[0].shown, true);
  d.windows[0].emit("ready-to-show");
  d.launches[0].child.stdout.emit("data", "NewsRead 已啟動：http://127.0.0.1:9876\n");
  await d.settled();
  assert.equal(d.windows[0].shown, true);
  assert.equal(d.windows.length, 1);
  d.app.quit(); await d.settled();
});

test("quitting from the tray saves detached windows too", async () => {
  const d = await desktop("win32");
  const sender = d.windows[0].webContents;
  await d.handlers.get("easyread:detach-window")({ sender, senderFrame: sender.mainFrame }, "tok");
  const detached = d.windows[1];
  let saved = 0;
  detached.webContents.send = () => { saved += 1; queueMicrotask(() => d.ipcMain.emit("easyread:page-saved", { sender: detached.webContents, senderFrame: detached.webContents.mainFrame })); };
  d.windows[0].emit("close", { preventDefault() {} });
  trayItem(d, trayLib.LABELS.quit).click();
  await d.settled();
  assert.equal(saved, 1);
  assert.equal(d.launches[0].child.killed, true);
});
