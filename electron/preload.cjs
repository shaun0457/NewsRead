const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("easyreadDesktop", {
  isElectron: true,
  platform: process.platform,
  pickFolder: () => ipcRenderer.invoke("easyread:pick-folder"),
  relaunch: () => ipcRenderer.invoke("easyread:relaunch"),
});
