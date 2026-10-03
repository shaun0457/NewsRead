const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { EventEmitter } = require("node:events");
const { test } = require("node:test");

async function desktop(platform = "darwin", lock = true, ready = true) {
  const app = new EventEmitter();
  Object.assign(app, {
    setPath() {}, getPath: () => "/tmp", getLocale: () => "zh-CN", isPackaged: true,
    requestSingleInstanceLock: () => lock, whenReady: () => Promise.resolve(),
    quit() { this.quitCalled = true; this.emit("before-quit", { preventDefault() {} }); },
    relaunch() { this.relaunched = true; }, exit() { this.exited = true; },
  });
  const windows = [], launches = [], menus = [], stages = [], handlers = new Map();
  const ipcMain = { handle(name, fn) { handlers.set(name, fn); } };
  class Window extends EventEmitter {
    constructor() { super(); this.webContents = new EventEmitter(); this.webContents.setWindowOpenHandler = () => {}; this.webContents.mainFrame = { url: "http://127.0.0.1:9876/" }; windows.push(this); }
    static getAllWindows() { return windows.filter(w => !w.closed); }
    async loadURL(url) { this.url = url; }
    show() { this.shown = true; }
    focus() { this.focused = true; }
    isMinimized() { return false; }
    close() { this.closed = true; this.emit("closed"); }
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
      if (ready) queueMicrotask(() => child.stdout.emit("data", "EasyRead 已启动：http://127.0.0.1:9876\n"));
      return child;
    },
  };
  const proc = new EventEmitter();
  Object.assign(proc, { platform, env: {}, resourcesPath: "/tmp/Resources" });
  const fakeRequire = name => name === "electron" ? { app, BrowserWindow: Window, Menu, ipcMain, dialog: { showErrorBox() {}, showOpenDialog: async () => ({ canceled: false, filePaths: ["/tmp/chosen"] }) }, shell: {} }
    : name === "child_process" ? childProcess : name === "fs" ? { existsSync: () => true }
    : name === "http" ? { request(url, options, callback) {
      const req = new EventEmitter(); req.setTimeout = () => {}; req.end = () => queueMicrotask(() => {
        const res = new EventEmitter(); res.statusCode = 200; res.setEncoding = () => {}; callback(res);
        res.emit("data", JSON.stringify(url.pathname === "/api/library" ? { token: "test-token" } : { ok: true }));
        res.emit("end");
        if (url.pathname === "/api/shutdown") launches[launches.length - 1].child.kill();
      }); return req;
    } }
    : name === "./startup-feedback.cjs" ? { ...require("../electron/startup-feedback.cjs"), mark(_app, stage) { stages.push(stage); }, loginShellPath: async () => "/usr/bin:/bin" }
    : name === "./desktop-updates.cjs" ? { registerUpdates() {} }
    : name === "electron-updater" ? { autoUpdater: {} }
    : name === "./window-state.cjs" ? { options: () => ({ opts: { width: 1440, height: 960 }, maximized: false }), track() {} }
    : require(name);
  const source = fs.readFileSync(path.join(__dirname, "../electron/main.cjs"), "utf8");
  vm.runInNewContext(source, { require: fakeRequire, process: proc, __dirname: "/tmp/electron", setTimeout, clearTimeout, console });
  const settled = () => new Promise(resolve => setImmediate(resolve));
  await settled();
  return { app, windows, launches, menus, handlers, stages, settled };
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
  d.launches[0].child.stdout.emit("data", "EasyRead 已启动：http://127.0.0.1:9876\n");
  await d.settled();
  assert.equal(d.windows[0].url, "http://127.0.0.1:9876");
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
