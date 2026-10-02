const { app, BrowserWindow, dialog, Menu, shell } = require("electron");
const { execFileSync, spawn } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");
const windowState = require("./window-state.cjs");

// 窗口缓存等放 %APPDATA%\EasyRead（默认会用 package.json 的 name，叫 easyread-desktop）。
// 论文和设置不放这里：打包后的后端默认用 ~/EasyRead，和 pip 安装版同一个位置，用户找得到、好备份。
app.setPath("userData", path.join(app.getPath("appData"), "EasyRead"));

// 桌面版自己的几句报错跟系统语言走（界面语言由后端决定，见 easyread/i18n.py）
const isZh = () => app.getLocale().toLowerCase().startsWith("zh");
let backend;
let mainWindow;
let backendReady;
let windowOpening = false;

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
      throw new Error(isZh() ? `找不到打包后的 EasyRead 后端：${executable}` : `Bundled EasyRead backend not found: ${executable}`);
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

// macOS / Linux 从启动台、桌面图标打开时，拿不到终端里配的 PATH（Homebrew、npm 全局目录），
// 后端会找不到 claude / codex。向用户的登录 shell 要一份 PATH 补上。
function loginShellPath() {
  if (process.platform === "win32") return "";
  try {
    const out = execFileSync(process.env.SHELL || "/bin/zsh", ["-ilc", 'printf "__PATH__%s__PATH__" "$PATH"'],
      { encoding: "utf8", timeout: 5000, stdio: ["ignore", "pipe", "ignore"] });
    const m = out.match(/__PATH__(.*)__PATH__/);
    return m ? m[1] : "";
  } catch (_) {
    return "";
  }
}

function startBackend() {
  // On macOS an app can stay alive after its last window closes. Reopening
  // the window must reuse that backend, rather than orphaning the old one.
  if (backendReady) return backendReady;
  const launch = backendCommand();
  const env = { ...process.env, PYTHONUTF8: "1", EASYREAD_SYSTEM_LANG: app.getLocale() };  // 后端按它决定界面语言
  const shellPath = loginShellPath();
  if (shellPath) {
    env.PATH = [...new Set([...shellPath.split(":"), ...(env.PATH || "").split(":")].filter(Boolean))].join(":");
  }
  if (process.platform !== "win32") {
    const fallback = [path.join(os.homedir(), ".local", "bin"), "/opt/homebrew/bin", "/usr/local/bin"];
    env.PATH = [...new Set([...(env.PATH || "").split(":"), ...fallback.filter(p => fs.existsSync(p))].filter(Boolean))].join(":");
  }

  backendReady = new Promise((resolve, reject) => {
    let settled = false;
    let output = "";
    const finish = (fn, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      fn(value);
    };
    const timer = setTimeout(() => {
      finish(reject, new Error((isZh() ? "EasyRead 后端启动超时。" : "EasyRead backend timed out while starting. ") + output.slice(-500)));
      stopBackend();
    }, 30000);

    backend = spawn(launch.command, launch.args, {
      cwd: launch.cwd,
      env,
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    });
    backend.stdout.on("data", (chunk) => {
      output = (output + chunk.toString()).slice(-65536);
      const match = output.match(/EasyRead\s+已启动：\s*(http:\/\/127\.0\.0\.1:\d+)/);
      if (match) finish(resolve, match[1]);
    });
    backend.stderr.on("data", (chunk) => {
      output = (output + chunk.toString()).slice(-65536);
    });
    backend.once("error", (error) => finish(reject, error));
    backend.once("exit", (code, signal) => {
      if (!settled) finish(reject, new Error((isZh() ? `EasyRead 后端退出（code=${code}, signal=${signal}）。` : `EasyRead backend exited (code=${code}, signal=${signal}). `) + output.slice(-500)));
      backend = undefined;
      backendReady = undefined;
    });
  });
  return backendReady;
}

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

async function createWindow() {
  if (windowOpening || mainWindow) return;
  windowOpening = true;
  let url;
  try {
    url = await startBackend();
  } catch (error) {
    windowOpening = false;
    dialog.showErrorBox(isZh() ? "EasyRead 启动失败" : "EasyRead failed to start", error.message);
    app.quit();
    return;
  }

  const state = windowState.options();
  mainWindow = new BrowserWindow({
    ...state.opts,
    minWidth: 960,
    minHeight: 680,
    icon: path.join(__dirname, "assets", "icon.ico"),
    show: false,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, "preload.cjs"),
    },
  });
  mainWindow.webContents.setWindowOpenHandler(({ url: target }) => {
    if (/^https?:/i.test(target)) shell.openExternal(target);
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
  mainWindow.once("ready-to-show", () => {
    if (state.maximized) mainWindow.maximize();
    mainWindow.show();
  });
  mainWindow.on("closed", () => { mainWindow = undefined; });
  try {
    await mainWindow.loadURL(url);
  } finally {
    windowOpening = false;
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
  app.whenReady().then(createWindow);
  app.on("before-quit", stopBackend);
  app.on("window-all-closed", () => {
    if (process.platform !== "darwin") app.quit();
  });
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
  app.on("second-instance", () => {
    if (!mainWindow) return void createWindow();
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
  });
  process.on("exit", stopBackend);
}
