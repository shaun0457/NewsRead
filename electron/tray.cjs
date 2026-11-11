/* 系統匣和開機啟動（ticket 66）。
   Windows 安裝版關掉視窗只是藏起來，後端的 server 和排程繼續跑；從系統匣按「結束」才停。
   Electron 的 Tray、Menu、app 都從外面傳進來，測試不用真的 Electron。 */

const HIDDEN_ARG = "--hidden";  // 開機啟動時帶這個參數：不開視窗，直接縮在系統匣
const LABELS = { open: "打開 NewsRead", quit: "結束", tooltip: "NewsRead" };
const OUTPUT_MAX = 65536;       // 只看後端輸出的最後這麼多字

// 只有 Windows 驗證過系統匣；macOS / Linux 維持上游的行為（關掉最後一個視窗就結束）
function enabled(platform) {
  return platform === "win32";
}

function create({ Tray, Menu, icon, onOpen, onQuit, labels = LABELS }) {
  const tray = new Tray(icon);
  tray.setToolTip(labels.tooltip);
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: labels.open, click: () => onOpen() },
    { type: "separator" },
    { label: labels.quit, click: () => onQuit() },
  ]));
  tray.on("click", () => onOpen());  // 左鍵直接打開；右鍵是上面的選單
  return tray;
}

/* 開機啟動用 Electron 的登入項目。只有打包過的 Windows 安裝版能設：
   開發時的 electron.exe 登記上去，開機會跑起一個空的 Electron。原始碼版用 `easyread autostart`。 */
function loginItem(app, platform) {
  const supported = Boolean(app.isPackaged) && platform === "win32";
  const query = { args: [HIDDEN_ARG] };  // Windows 要帶一樣的參數才查得到同一筆
  function get() {
    if (!supported) return { supported: false, enabled: false };
    return { supported: true, enabled: Boolean(app.getLoginItemSettings(query).openAtLogin) };
  }
  function set(on) {
    if (typeof on !== "boolean") throw new Error("openAtLogin must be a boolean");
    if (!supported) throw new Error("Login item is only available in the Windows installer");
    app.setLoginItemSettings({ openAtLogin: on, args: [HIDDEN_ARG] });
    return get();
  }
  return { get, set };
}

/* 後端因為已經有一個 NewsRead 服務在跑而退出（代碼 3）時，從它的輸出拿那個服務的位址。
   只接手這台電腦上的 http://127.0.0.1:埠號；別的位址（包括 .server.json 被改過的）一律不接。 */
const RUNNING = /NewsRead\s*已(?:經|经)在(?:執|执)行：\s*http:\/\/127\.0\.0\.1:(\d{1,5})(?![\w@.:/%-])/;

function runningUrl(output) {
  const match = String(output || "").slice(-OUTPUT_MAX).match(RUNNING);
  const port = match ? Number(match[1]) : 0;
  return port >= 1 && port <= 65535 ? `http://127.0.0.1:${port}` : "";
}

module.exports = { HIDDEN_ARG, LABELS, OUTPUT_MAX, enabled, create, loginItem, runningUrl };
