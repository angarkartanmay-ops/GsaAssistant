// Only the setup and splash screens use this; the HUD itself needs nothing from Electron.
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("havocDesktop", {
  onSetupLog: (fn) => ipcRenderer.on("setup-log", (_e, line) => fn(line)),
  onSetupFailed: (fn) => ipcRenderer.on("setup-failed", () => fn()),
  onSplashError: (fn) => ipcRenderer.on("splash-error", (_e, msg) => fn(msg)),
  retrySetup: () => ipcRenderer.invoke("setup-retry"),
});
