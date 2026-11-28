const { app, BrowserWindow, dialog, Menu, shell, ipcMain, Tray } = require("electron");
const { execFileSync, spawn } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");
const windowState = require("./window-state.cjs");
const { URL } = require("url");
const http = require("http");
const startup = require("./startup-feedback.cjs");
const { registerUpdates } = require("./desktop-updates.cjs");
const deepLink = require("./deep-link.cjs");
const desktopTabs = require("./desktop-tabs.cjs");
const tray = require("./tray.cjs");

// 新版使用 PaperRead 資料夾；第一次升級時把舊版 EasyRead 的桌面偏好
// 搬到新位置，避免改名後像是全新安裝。搬移失敗時保留舊資料，不覆蓋任何內容。
const appData = app.getPath("appData");
const paperReadUserData = path.join(appData, "PaperRead");
const legacyUserData = path.join(appData, "EasyRead");
if (!fs.existsSync(paperReadUserData) && fs.existsSync(legacyUserData)) {
  try { fs.renameSync(legacyUserData, paperReadUserData); } catch (_) { /* legacy data remains recoverable */ }
}
app.setPath("userData", paperReadUserData);
startup.mark(app, "electron-entry");

// 桌面版自己的幾句報錯跟系統語言走（介面語言由後端決定，見 easyread/i18n.py）
const isZh = () => true; // NewsRead desktop defaults to Traditional Chinese.
let backend;
let mainWindow;
let backendReady;
let windowOpening = false;
let backendUrl;
let quitting = false;
let pendingOpen = deepLink.fromArgv(process.argv);
const detachedWindows = new Set();
let trayIcon;  // 要一直留著參考，不然會被回收、從系統匣消失
let hideAtStart = process.argv.includes(tray.HIDDEN_ARG);  // 開機啟動：先不開視窗，只在系統匣
const login = tray.loginItem(app, process.platform);
const PIPE_WAIT = 1000;  // 後端以代碼 3 結束後，最多等這麼久讓輸出讀完
const PROBE_WAIT = 3000;  // 接手前確認那個服務：最多等這麼久
const PROBE_MAX = 4096;   // /api/version 的回應最多讀這麼多 bytes
const NO_ADDRESS = "NewsRead 已經在執行，但讀不到它在這台電腦上的位址。請先結束那個 NewsRead（easyread stop），再打開桌面版。";
/* 接手的服務（start.cmd 或 easyread serve 開的，ticket 105）：結束時一起停掉；中途掉線要讓使用者知道 */
let adopted = false;
let watchTimer;
const WATCH_EVERY = 15000;  // 每隔這麼久確認接手的服務還在
const WATCH_MISSES = 2;     // 連續確認不到這麼多次才算掉線（偶爾一次慢回應不算）
const STOP_POLL = 200;      // 結束時送出 shutdown 後，每隔這麼久看它關了沒
const STOP_TRIES = 40;      // 最多看這麼多次（約 8 秒，每次確認本身最多 PROBE_WAIT）
const ADOPTED_LOST = "桌面版接手的 NewsRead 服務已經停了：畫面上的資料不會再更新，背景的排程也停了。請結束 NewsRead 再重新打開。";
const ADOPTED_KEPT = "接手的 NewsRead 服務沒有停：";

/* 接手之前先確認那個埠號上真的是活著的 NewsRead：.server.json 可能是上次當掉留下的舊位址，
   埠號也可能被別的程式拿走。對了才接手，那個網頁才拿得到桌面版的功能（存檔、選資料夾…）。 */
function probeNewsRead(url) {
  return new Promise(resolve => {
    let done = false, size = 0, body = "";
    const end = ok => { if (!done) { done = true; resolve(ok); } };
    let req;
    try {
      req = http.request(new URL("/api/version", url), { method: "GET" }, res => {
        if (res.statusCode !== 200) { end(false); req.destroy(); return; }
        res.setEncoding("utf8");
        res.on("data", part => {
          size += part.length;  // 已經解成字串：用字數算，上限一樣有效
          if (size > PROBE_MAX) { end(false); req.destroy(); return; }
          body += part;
        });
        res.on("end", () => {
          try {
            const data = JSON.parse(body);
            end(Boolean(data) && typeof data.api === "number" && typeof data.version === "string");
          } catch (_) { end(false); }
        });
        res.on("error", () => end(false));
      });
    } catch (_) { return void end(false); }
    req.setTimeout(PROBE_WAIT, () => { end(false); req.destroy(); });
    req.on("error", () => end(false));
    req.end();
  });
}

function projectRoot() {
  return path.resolve(__dirname, "..");
}

function packagedBackend() {
  const name = process.platform === "win32" ? "easyread-backend.exe" : "easyread-backend";
  return path.join(process.resourcesPath, "backend", name);
}

function backendCommand() {
  if (app.isPackaged) {
    const executable = packagedBackend();
    if (!fs.existsSync(executable)) {
      throw new Error(isZh() ? `找不到打包後的 NewsRead 後端：${executable}` : `Bundled NewsRead backend not found: ${executable}`);
    }
    return { command: executable, args: ["serve", "--port", "0"], cwd: os.homedir() };
  }

  const root = projectRoot();
  const python = process.platform === "win32"
    ? path.join(root, ".venv", "Scripts", "python.exe")
    : path.join(root, ".venv", "bin", "python");
  const command = fs.existsSync(python) ? python : (process.platform === "win32" ? "python" : "python3");
  return { command, args: ["-m", "easyread", "serve", "--port", "0"], cwd: root };
}

// macOS / Linux 從啟動臺、桌面圖示開啟時，拿不到終端裡配的 PATH（Homebrew、npm 全域性目錄），
// 後端會找不到 claude / codex。向使用者的登入 shell 要一份 PATH 補上。
function startBackend() {
  // On macOS an app can stay alive after its last window closes. Reopening
  // the window must reuse that backend, rather than orphaning the old one.
  if (backendReady) return backendReady;
  backendReady = (async () => {
  const launch = backendCommand();
  const env = { ...process.env, PYTHONUTF8: "1", EASYREAD_SYSTEM_LANG: app.getLocale() };  // 後端按它決定介面語言
  startup.mark(app, "shell-path-start");
  const shellPath = await startup.loginShellPath(process.platform);
  startup.mark(app, "shell-path-ready");
  if (quitting) throw new Error(isZh() ? "啟動已取消" : "Startup cancelled");
  if (shellPath) {
    env.PATH = [...new Set([...shellPath.split(":"), ...(env.PATH || "").split(":")].filter(Boolean))].join(":");
  }
  if (process.platform !== "win32") {
    const fallback = [path.join(os.homedir(), ".local", "bin"), "/opt/homebrew/bin", "/usr/local/bin"];
    env.PATH = [...new Set([...(env.PATH || "").split(":"), ...fallback.filter(p => fs.existsSync(p))].filter(Boolean))].join(":");
  }

  return new Promise((resolve, reject) => {
    let settled = false;
    let output = "";
    const finish = (fn, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      fn(value);
    };
    const timer = setTimeout(() => {
      finish(reject, new Error((isZh() ? "NewsRead 後端啟動超時。" : "NewsRead backend timed out while starting. ") + output.slice(-500)));
      stopBackend();
    }, 30000);

    startup.mark(app, "backend-spawn");
    backend = spawn(launch.command, launch.args, {
      cwd: launch.cwd,
      env,
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    });
    backend.stdout.on("data", (chunk) => {
      output = (output + chunk.toString()).slice(-65536);
      const match = output.match(/NewsRead\s+已(?:启动|啟動)：\s*(http:\/\/127\.0\.0\.1:\d+)/);
      if (match && !settled) { startup.mark(app, "backend-http-ready"); backendUrl = match[1]; finish(resolve, match[1]); }
    });
    backend.stderr.on("data", (chunk) => {
      output = (output + chunk.toString()).slice(-65536);
    });
    backend.once("error", (error) => finish(reject, error));
    const child = backend;
    backend.once("exit", (code, signal) => {
      backend = undefined;
      const done = () => {
        // 已經有一個 NewsRead 服務在跑（start.cmd 或 easyread serve 開的）：接手它，不開第二個。
        // 只關視窗時它照樣在背景跑；從系統匣按「結束」時一起停掉（stopAdopted，ticket 105）。
        const running = !settled && code === 3 ? tray.runningUrl(output) : "";
        if (running) {
          probeNewsRead(running).then(ok => {
            if (!ok || settled) return void fail();
            startup.mark(app, "backend-adopted");
            backendUrl = running;
            adopted = true;
            watchAdopted(running);
            finish(resolve, running);
          });
          return;
        }
        fail();
      };
      const fail = () => {
        if (!settled) {
          finish(reject, new Error(code === 3
            ? NO_ADDRESS
            : (isZh() ? `NewsRead 後端退出（code=${code}, signal=${signal}）。` : `NewsRead backend exited (code=${code}, signal=${signal}). `) + output.slice(-500)));
        }
        backendReady = undefined;
        backendUrl = undefined;
        adopted = false;
      };
      if (settled || code !== 3) return void done();
      // 「已經在執行」那句可能還在管線裡：等輸出關掉再看，最多 PIPE_WAIT 毫秒
      let waited = false;
      const once = () => {
        if (waited) return;
        waited = true;
        clearTimeout(pipeTimer);
        child.removeListener("close", once);
        done();
      };
      const pipeTimer = setTimeout(once, PIPE_WAIT);
      child.once("close", once);
    });
  });
  })();
  backendReady.catch(() => { backendReady = undefined; });
  return backendReady;
}

function backendJson(endpoint, token) {
  return new Promise((resolve, reject) => {
    const req = http.request(new URL(endpoint, backendUrl), {
      method: token ? "POST" : "GET",
      headers: token ? { "X-Token": token, "Content-Type": "application/json", "Content-Length": 2 } : {},
    }, res => {
      let body = "";
      res.setEncoding("utf8");
      res.on("data", part => { body += part; });
      res.on("end", () => {
        try {
          const data = JSON.parse(body);
          if (res.statusCode !== 200) return reject(Object.assign(new Error(data.error || `HTTP ${res.statusCode}`), { status: res.statusCode }));
          resolve(data);
        } catch (error) { reject(error); }
      });
    });
    req.setTimeout(8000, () => req.destroy(new Error(isZh() ? "後端關閉超時，請稍後重試" : "Backend shutdown timed out. Try again later.")));
    req.on("error", reject);
    req.end(token ? "{}" : undefined);
  });
}

async function stopBackendGracefully() {
  const child = backend;
  if (!child) return;
  const info = await backendJson("/api/library");
  await backendJson("/api/shutdown", info.token);
  // 後端清掉佔用標記、關閉 HTTP 服務後才啟動新程序。
  if (backend !== child) return;
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => { child.removeListener("exit", exited); reject(new Error(isZh() ? "後端尚未退出，請稍後重試" : "The backend has not exited yet. Try again later.")); }, 8000);
    function exited() { clearTimeout(timer); resolve(); }
    child.once("exit", exited);
  });
}

function watchAdopted(url) {
  let misses = 0;
  const schedule = () => {
    watchTimer = setTimeout(check, WATCH_EVERY);
    if (watchTimer && typeof watchTimer.unref === "function") watchTimer.unref();
  };
  const check = () => {
    watchTimer = undefined;
    probeNewsRead(url).then(ok => {
      if (quitting || !adopted || backendUrl !== url) return;
      misses = ok ? 0 : misses + 1;
      if (misses < WATCH_MISSES) return void schedule();
      startup.mark(app, "adopted-lost");
      dialog.showErrorBox("NewsRead", ADOPTED_LOST);  // 只說一次，不再確認
    });
  };
  schedule();
}

function stopWatch() {
  clearTimeout(watchTimer);
  watchTimer = undefined;
}

/* 結束時停掉接手的服務：跟 easyread stop 一樣走 /api/shutdown，再確認它真的關了（有上限） */
async function stopAdopted() {
  stopWatch();
  const url = backendUrl;
  try {
    const info = await backendJson("/api/library");
    await backendJson("/api/shutdown", info.token);
  } catch (error) {
    // 服務回了錯誤（例如正在翻譯）才是「沒有停」；連不上而且確認也沒回應，就是它已經停了（例如先跑了 easyread stop）
    if (error.status || await probeNewsRead(url)) dialog.showErrorBox("NewsRead", ADOPTED_KEPT + error.message);
    return;  // 服務留著，桌面版照樣結束
  }
  for (let i = 0; i < STOP_TRIES; i += 1) {
    if (!(await probeNewsRead(url))) return;
    await new Promise(resolve => setTimeout(resolve, STOP_POLL));
  }
}

/* 退出前先让页面把没落盘的东西写回去再停后端；页面没应就照常退出 */
function savePageState() {
  const windows = [mainWindow, ...detachedWindows].filter(w => w && !w.isDestroyed() && w.webContents && !w.webContents.isDestroyed());
  if (!windows.length) return Promise.resolve();
  return Promise.all(windows.map(win => {
    const wc = win.webContents;
    if (!wc || (typeof wc.isDestroyed === "function" && wc.isDestroyed()) || typeof wc.send !== "function") return Promise.resolve();
  return new Promise(resolve => {
    let timer;
    function done() {
      clearTimeout(timer);
      if (ipcMain && typeof ipcMain.removeListener === "function") {
        ipcMain.removeListener("easyread:page-saved", saved);
      }
      resolve();
    }
    function saved(event) {
      if (event && event.sender === wc && event.senderFrame === wc.mainFrame) done();
    }
    const tabbed = (wc.getURL?.() || "").includes("/web/tabs.html");
    timer = setTimeout(done, tabbed ? 8000 : 1200);
    if (ipcMain && typeof ipcMain.on === "function") {
      ipcMain.on("easyread:page-saved", saved);
    }
    try {
      wc.send("easyread:before-quit");
    } catch {
      done();
    }
    });
  }));
}

function trustedWindow(event) {
  const isMain = mainWindow && event.sender === mainWindow.webContents && event.senderFrame === mainWindow.webContents.mainFrame;
  const isDetached = [...detachedWindows].some(win => win && !win.isDestroyed() && event.sender === win.webContents && event.senderFrame === win.webContents.mainFrame);
  if ((!isMain && !isDetached) ||
      !backendUrl || new URL(event.senderFrame.url).origin !== backendUrl) {
    throw new Error("Untrusted IPC sender");
  }
}

ipcMain.handle("easyread:pick-folder", async event => {
  trustedWindow(event);
  const result = await dialog.showOpenDialog(mainWindow, { properties: ["openDirectory", "createDirectory"] });
  return result.canceled ? null : result.filePaths[0] || null;
});
ipcMain.handle("easyread:save-file", async (event, options = {}) => {
  trustedWindow(event);
  const filename = typeof options.filename === "string" && options.filename.trim() ? options.filename.trim() : "NewsRead-export.md";
  const encoded = typeof options.contentBase64 === "string" ? options.contentBase64 : "";
  if (!encoded || encoded.length > 160 * 1024 * 1024) throw new Error("匯出內容無效或過大");
  const result = await dialog.showSaveDialog(mainWindow, {
    defaultPath: filename,
    filters: Array.isArray(options.filters) && options.filters.length ? options.filters : [{ name: "All files", extensions: ["*"] }],
  });
  if (result.canceled || !result.filePath) return { canceled: true };
  await fs.promises.writeFile(result.filePath, Buffer.from(encoded, "base64"));
  return { canceled: false, path: result.filePath };
});
ipcMain.handle("easyread:relaunch", async event => {
  trustedWindow(event);
  await stopBackendGracefully();
  app.relaunch();
  app.exit(0);
});
ipcMain.handle("easyread:detach-window", async (event, token, bounds = {}) => {
  trustedWindow(event);
  if (!backendUrl) throw new Error("Backend not ready");
  const { screen } = require("electron");
  const senderWin = BrowserWindow.fromWebContents(event.sender);
  const display = (senderWin && !senderWin.isDestroyed())
    ? screen.getDisplayMatching(senderWin.getBounds())
    : (screen.getDisplayNearestPoint({ x: bounds.x || 0, y: bounds.y || 0 }) || screen.getPrimaryDisplay());
  const workArea = display.workArea;
  const halfW = Math.floor(workArea.width / 2);
  const leftBounds = {
    x: workArea.x,
    y: workArea.y,
    width: halfW,
    height: workArea.height,
  };
  const rightBounds = {
    x: workArea.x + halfW,
    y: workArea.y,
    width: workArea.width - halfW,
    height: workArea.height,
  };

  // Snap the source window to the left half of the display for side-by-side dual view
  try {
    if (senderWin && !senderWin.isDestroyed()) {
      if (senderWin.isFullScreen()) senderWin.setFullScreen(false);
      const [curMinW, curMinH] = senderWin.getMinimumSize();
      if (curMinW > halfW) {
        senderWin.setMinimumSize(Math.min(500, halfW), Math.min(curMinH, 400));
      }
      if (senderWin.isMaximized()) {
        senderWin.unmaximize();
      }
      const applyBounds = () => {
        if (!senderWin.isDestroyed()) {
          senderWin.setBounds(leftBounds);
        }
      };
      applyBounds();
      setTimeout(applyBounds, 60);
      setTimeout(applyBounds, 180);
    }
  } catch (_) {}

  const win = new BrowserWindow({
    width: rightBounds.width,
    height: rightBounds.height,
    x: rightBounds.x,
    y: rightBounds.y,
    minWidth: Math.min(500, halfW),
    minHeight: 400,
    icon: path.join(__dirname, "assets", "paperread.ico"),
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, "preload.cjs"),
    },
  });
  win.webContents.setWindowOpenHandler(({ url: target }) => {
    if (/^https?:/i.test(target)) shell.openExternal(target);
    if (/^obsidian:/i.test(target)) shell.openExternal(target);
    return { action: "deny" };
  });
  desktopTabs.bindShortcuts(win);
  detachedWindows.add(win);
  win.on("closed", () => {
    detachedWindows.delete(win);
  });
  await win.loadURL(desktopTabs.detachedShellUrl(backendUrl, token));
  return true;
});
ipcMain.handle("easyread:login-item", async event => {
  trustedWindow(event);
  return login.get();
});
ipcMain.handle("easyread:set-login-item", async (event, on) => {
  trustedWindow(event);
  return login.set(on);
});
ipcMain.handle("easyread:close-current-window", async (event) => {
  trustedWindow(event);
  try {
    const win = BrowserWindow.fromWebContents(event.sender);
    if (win && !win.isDestroyed()) {
      win.close();
    }
  } catch (_) {}
  return true;
});

function stopBackend() {
  backendReady = undefined;
  if (backend && !backend.killed) {
    if (process.platform === "win32") {
      // PyInstaller's one-file launcher creates a child process. Killing only
      // the launcher would leave the local HTTP service running after exit.
      try {
        execFileSync("taskkill", ["/pid", String(backend.pid), "/t", "/f"], {
          windowsHide: true,
          stdio: "ignore",
        });
      } catch (_) {
        // The process may already have exited while the window was closing.
      }
    } else {
      backend.kill();
    }
    backend = undefined;
  }
}

// 打開主視窗：從系統匣、第二次打開、外部連結都走這裡
function showMain() {
  hideAtStart = false;
  if (!mainWindow) return void createWindow();
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.show();
  mainWindow.focus();
}

// 視窗還在啟動時先記下，後端就緒後 createWindow 直接開啟這篇
function openLink(target) {
  if (!target) return;
  hideAtStart = false;
  if (!mainWindow || windowOpening || !backendUrl) {
    pendingOpen = target;
    if (!mainWindow && app.isReady()) createWindow();
    return;
  }
  showMain();
  desktopTabs.openPaper(mainWindow, target).then(opened => {
    if (!opened && mainWindow) return mainWindow.loadURL(desktopTabs.shellUrl(backendUrl, target));
  }).catch(error => dialog.showErrorBox("NewsRead", error.message));
}

async function createWindow() {
  if (windowOpening || mainWindow) return;
  windowOpening = true;
  const startedHidden = hideAtStart;
  const state = windowState.options();
  mainWindow = new BrowserWindow({
    ...state.opts,
    minWidth: 960,
    minHeight: 680,
    icon: path.join(__dirname, "assets", "paperread.ico"),
    show: false,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, "preload.cjs"),
    },
  });
  mainWindow.webContents.setWindowOpenHandler(({ url: target }) => {
    if (/^https?:/i.test(target)) shell.openExternal(target);
    if (/^obsidian:/i.test(target)) shell.openExternal(target);
    return { action: "deny" };
  });
  // A native context menu is separate from the application Edit menu.
  // Electron does not emit this event when the page prevents contextmenu,
  // so the library's and reader's custom menus keep working.
  mainWindow.webContents.on("context-menu", (_event, params) => {
    const flags = params.editFlags || {};
    const items = params.isEditable
      ? [{ role: "undo", enabled: flags.canUndo }, { role: "redo", enabled: flags.canRedo },
         { type: "separator" }, { role: "cut", enabled: flags.canCut }, { role: "copy", enabled: flags.canCopy },
         { role: "paste", enabled: flags.canPaste }, { type: "separator" }, { role: "selectAll" }]
      : params.selectionText.trim() ? [{ role: "copy" }] : [];
    if (items.length) Menu.buildFromTemplate(items).popup({ window: mainWindow });
  });
  windowState.track(mainWindow);
  desktopTabs.bindShortcuts(mainWindow);
  const openingWindow = mainWindow;
  mainWindow.once("ready-to-show", () => {
    if (mainWindow !== openingWindow || hideAtStart) return;
    if (state.maximized) openingWindow.maximize();
    openingWindow.show();
  });
  mainWindow.on("close", event => {
    if (quitting) return;
    if (trayIcon) {  // Windows：縮到系統匣，server 和排程繼續跑；從系統匣按「結束」才真的結束
      event.preventDefault();
      openingWindow.hide();
      return;
    }
    if (process.platform !== "darwin" && (backend || backendUrl)) {
      event.preventDefault();
      app.quit();  // before-quit saves while the renderer is still alive.
    }
  });
  mainWindow.on("closed", () => { mainWindow = undefined; });
  try {
    await openingWindow.loadURL(startup.loadingUrl(isZh()));
    if (mainWindow !== openingWindow || quitting) return;
    if (!hideAtStart) {  // maximize() 也會讓視窗出現，所以一起跳過
      if (state.maximized) openingWindow.maximize();
      openingWindow.show();
    }
    startup.mark(app, hideAtStart ? "startup-hidden" : "startup-window-visible");
    const url = await startBackend();
    if (mainWindow !== openingWindow || quitting) return;
    const first = desktopTabs.shellUrl(url, pendingOpen);
    pendingOpen = undefined;
    await openingWindow.loadURL(first);
    // 藏在系統匣啟動、後端還沒好時點了連結：openLink 只記下連結，這裡把視窗打開
    if (startedHidden && !hideAtStart && mainWindow === openingWindow) openingWindow.show();
    startup.mark(app, "library-loaded");
  } catch (error) {
    if (mainWindow !== openingWindow || quitting) return;
    startup.mark(app, "startup-failed");
    dialog.showErrorBox(isZh() ? "NewsRead 啟動失敗" : "NewsRead failed to start", error.message);
    app.quit();
  } finally {
    windowOpening = false;
    // 載入文獻庫期間又點了 easyread:// 連結，openLink 只記下了它，這裡補開
    if (pendingOpen && mainWindow === openingWindow && !quitting) openLink(pendingOpen);
  }
}

// Keep the web application's own header at the top of the content area. The
// default Electron File/Edit/View/Window strip would otherwise create a second
// toolbar row above it. The macOS menu is at the top of the screen and
// its Edit roles provide Cmd+C/V/X/A/Z.
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  Menu.setApplicationMenu(process.platform === "darwin"
    ? Menu.buildFromTemplate([{ role: "appMenu" }, { role: "editMenu" }, { role: "windowMenu" }])
    : null);
  // macOS 用 open-url 傳連結，可能早於 ready
  app.on("open-url", (event, link) => {
    event.preventDefault();
    openLink(deepLink.openPath(link));
  });
  app.whenReady().then(() => {
    deepLink.register(app, process);
    registerUpdates({
      app, ipcMain, updater: require("electron-updater").autoUpdater, trustedWindow,
      repository: process.env.EASYREAD_UPDATE_REPOSITORY || "",  // NewsRead 還沒有自己的發佈頁：不從 PaperRead 下載更新（ticket 06）
      getWindow: () => mainWindow,
      prepareInstall: stopBackendGracefully,
      recover: async () => {
        if (backend) return;  // 後端沒停（正在翻譯、拒絕關閉）：頁面別重新整理，彈窗留著顯示原因
        const url = await startBackend();
        if (mainWindow) await mainWindow.loadURL(desktopTabs.shellUrl(url));
      },
    });
    if (tray.enabled(process.platform)) {
      try {
        trayIcon = tray.create({ Tray, Menu, icon: path.join(__dirname, "assets", "paperread.ico"), onOpen: showMain, onQuit: () => app.quit() });
      } catch (_) {
        trayIcon = undefined;  // 系統匣建不起來：照舊，關掉視窗就結束
      }
    }
    if (!trayIcon) hideAtStart = false;  // 沒有系統匣就沒有地方打開，不能藏
    return createWindow();
  });
  app.on("before-quit", event => {
    if (quitting) return;
    quitting = true;
    if (!backend && !backendUrl) return;
    event.preventDefault();
    stopWatch();
    // 先讓頁面存檔；接手的服務也一起停掉（只關視窗、縮到系統匣時不會走到這裡）
    savePageState().then(() => adopted ? stopAdopted() : stopBackendGracefully()).catch(stopBackend).finally(() => app.quit());
  });
  app.on("window-all-closed", () => {
    if (process.platform !== "darwin") app.quit();
  });
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
  app.on("second-instance", (_event, argv) => {
    const target = deepLink.fromArgv(argv);
    if (target) return void openLink(target);
    if (Array.isArray(argv) && argv.includes(tray.HIDDEN_ARG)) return;  // 開機啟動時已經在跑：留在系統匣
    showMain();
  });
  process.on("exit", stopBackend);
}
