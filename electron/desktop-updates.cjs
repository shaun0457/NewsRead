// Windows NSIS updates. The renderer never supplies a feed URL or installer path.
function registerUpdates({ app, ipcMain, updater, trustedWindow, getWindow, prepareInstall, recover }) {
  const supported = app.isPackaged && process.platform === "win32";
  let state = { supported, phase: "idle", version: "", percent: 0, error: "" };
  let busy = false;
  const publish = (patch) => {
    state = { ...state, ...patch };
    const win = getWindow();
    if (win && !win.isDestroyed()) win.webContents.send("easyread:update-state", state);
  };
  if (supported) {
    updater.autoDownload = false;
    updater.autoInstallOnAppQuit = false;
    updater.allowDowngrade = false;
    updater.setFeedURL({ provider: "github", owner: "Edwardxlai", repo: "easyread" });
    updater.on("error", error => publish({ phase: "error", error: error.message }));
    updater.on("download-progress", progress => publish({ phase: "downloading", percent: progress.percent }));
    updater.on("update-downloaded", info => publish({ phase: "downloaded", version: info.version, percent: 100 }));
  }
  ipcMain.handle("easyread:update-state", event => { trustedWindow(event); return state; });
  ipcMain.handle("easyread:update-download", async event => {
    trustedWindow(event);
    if (!supported || busy || state.phase === "downloaded") return state;
    busy = true;
    try {
      publish({ phase: "checking", error: "", percent: 0 });
      const result = await updater.checkForUpdates();
      if (!result || !result.isUpdateAvailable) {
        publish({ phase: "current" });
      } else {
        publish({ phase: "downloading", version: result.updateInfo.version });
        await updater.downloadUpdate();
      }
    } catch (error) { publish({ phase: "error", error: error.message }); }
    finally { busy = false; }
    return state;
  });
  ipcMain.handle("easyread:update-install", async event => {
    trustedWindow(event);
    if (!supported || busy || state.phase !== "downloaded") return state;
    busy = true;
    try {
      publish({ phase: "installing", error: "" });
      await prepareInstall();
      updater.quitAndInstall(true, true);
      if (state.phase === "error") await recover();
    } catch (error) {
      publish({ phase: "downloaded", error: error.message });
      await recover();
    } finally { busy = false; }
    return state;
  });
}

module.exports = { registerUpdates };
