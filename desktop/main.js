// HAVOC desktop app. One window, one tray icon, and two background processes:
//   * the brain:  <HAVOC_HOME>\venv python -m havoc run   (FastAPI on 127.0.0.1:7777)
//   * WhatsApp:   whatsapp-bridge/index.js on Electron's own Node (ELECTRON_RUN_AS_NODE)
// Your config, keys and data live in HAVOC_HOME (%LOCALAPPDATA%\HAVOC), never in the install
// folder, so updating or reinstalling the app keeps everything.

const { app, BrowserWindow, Menu, Tray, ipcMain, nativeImage, nativeTheme, shell } = require("electron");
const { spawn, execFile } = require("node:child_process");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");

const IS_WIN = process.platform === "win32";
const PORT = 7777;
const URL = `http://127.0.0.1:${PORT}/`;
const RESTART_CODE = 3;

const HOME = process.env.HAVOC_HOME || path.join(process.env.LOCALAPPDATA || app.getPath("appData"), "HAVOC");
const BACKEND = app.isPackaged ? path.join(process.resourcesPath, "backend") : path.resolve(__dirname, "..");
const PYTHON = process.env.HAVOC_PYTHON || (IS_WIN ? path.join(HOME, "venv", "Scripts", "python.exe") : path.join(HOME, "venv", "bin", "python"));
const LOG = path.join(HOME, "logs", "desktop.log");

fs.mkdirSync(path.dirname(LOG), { recursive: true });
const log = (...args) => fs.appendFileSync(LOG, `[${new Date().toISOString()}] ${args.join(" ")}\n`);

let win = null;
let tray = null;
let quitting = false;
const children = { brain: null, bridge: null };
const failures = { brain: 0, bridge: 0 };

nativeTheme.themeSource = "dark";
if (!app.requestSingleInstanceLock()) app.quit();
app.on("second-instance", () => showWindow());

function childEnv(extra = {}) {
  return { ...process.env, HAVOC_HOME: HOME, PYTHONUTF8: "1", PYTHONPATH: BACKEND, ...extra };
}

function pipeLogs(name, child) {
  child.stdout?.on("data", (d) => log(`[${name}]`, String(d).trimEnd()));
  child.stderr?.on("data", (d) => log(`[${name}!]`, String(d).trimEnd()));
}

function killTree(child) {
  if (!child || child.exitCode !== null) return;
  if (IS_WIN) execFile("taskkill", ["/pid", String(child.pid), "/T", "/F"], () => {});
  else child.kill("SIGTERM");
}

// ---------------------------------------------------------------- background processes
function startBrain() {
  const child = spawn(PYTHON, ["-m", "havoc", "run", "--no-window"], {
    cwd: BACKEND, env: childEnv(), windowsHide: true,
  });
  children.brain = child;
  pipeLogs("brain", child);
  child.on("exit", (code) => {
    log("brain exited", code);
    children.brain = null;
    if (quitting) return;
    if (code === RESTART_CODE) {
      failures.brain = 0;
      return startBrain(); // "Restart now" in Connections
    }
    const delay = Math.min(30000, 2000 * 2 ** failures.brain++);
    setTimeout(startBrain, delay);
  });
}

function startBridge() {
  const script = path.join(BACKEND, "whatsapp-bridge", "index.js");
  if (!fs.existsSync(script)) return log("bridge missing at", script);
  const child = spawn(process.execPath, [script], {
    cwd: path.dirname(script), env: childEnv({ ELECTRON_RUN_AS_NODE: "1" }), windowsHide: true,
  });
  children.bridge = child;
  pipeLogs("whatsapp", child);
  child.on("exit", (code) => {
    log("bridge exited", code);
    children.bridge = null;
    if (!quitting) setTimeout(startBridge, Math.min(30000, 2000 * 2 ** failures.bridge++));
  });
}

function ensureOllama() {
  // The Ollama Windows app normally runs from the tray; start the server if it isn't up.
  http.get("http://127.0.0.1:11434/api/version", () => {}).on("error", () => {
    const exe = IS_WIN ? path.join(process.env.LOCALAPPDATA || "", "Programs", "Ollama", "ollama.exe") : "ollama";
    try {
      spawn(IS_WIN && fs.existsSync(exe) ? exe : "ollama", ["serve"], { detached: true, stdio: "ignore", windowsHide: true }).unref();
    } catch (e) {
      log("could not start ollama", e);
    }
  });
}

function waitForBrain(timeoutMs = 180000) {
  const started = Date.now();
  return new Promise((resolve, reject) => {
    const ping = () => {
      http.get(`${URL}api/me`, (res) => {
        res.resume();
        res.statusCode === 200 ? resolve() : retry();
      }).on("error", retry);
    };
    const retry = () => (Date.now() - started > timeoutMs ? reject(new Error("timeout")) : setTimeout(ping, 700));
    ping();
  });
}

// ---------------------------------------------------------------- first run
function runSetup() {
  return new Promise((resolve) => {
    const setup = new BrowserWindow({
      width: 760, height: 560, backgroundColor: "#0c0d10", autoHideMenuBar: true, resizable: false,
      icon: path.join(__dirname, "icon.png"), title: "Setting up HAVOC",
      webPreferences: { preload: path.join(__dirname, "preload.js") },
    });
    setup.loadFile(path.join(__dirname, "setup.html"));
    setup.webContents.once("did-finish-load", () => {
      const script = path.join(BACKEND, "setup-backend.ps1");
      const child = spawn("powershell", ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script,
        "-HavocHome", HOME, "-Backend", BACKEND], { windowsHide: true, env: childEnv() });
      const send = (line) => !setup.isDestroyed() && setup.webContents.send("setup-log", line);
      child.stdout.on("data", (d) => String(d).split(/\r?\n/).filter(Boolean).forEach(send));
      child.stderr.on("data", (d) => String(d).split(/\r?\n/).filter(Boolean).forEach((l) => send(`! ${l}`)));
      child.on("exit", (code) => {
        log("setup exited", code);
        if (code === 0 && fs.existsSync(PYTHON)) {
          send("Done. Starting HAVOC...");
          setTimeout(() => (setup.destroy(), resolve(true)), 1200);
        } else {
          send(`Setup stopped (code ${code}). Fix the line marked with ! above, then press Retry.`);
          if (!setup.isDestroyed()) setup.webContents.send("setup-failed");
        }
      });
    });
    ipcMain.removeHandler("setup-retry");
    ipcMain.handle("setup-retry", () => {
      setup.destroy();
      runSetup().then(resolve);
    });
    setup.on("closed", () => resolve(false));
  });
}

// ---------------------------------------------------------------- window + tray
function createWindow() {
  win = new BrowserWindow({
    width: 1440, height: 900, minWidth: 380, minHeight: 560, show: false,
    backgroundColor: "#0c0d10", autoHideMenuBar: true, title: "HAVOC",
    icon: path.join(__dirname, "icon.png"),
    webPreferences: { contextIsolation: true, sandbox: true, preload: path.join(__dirname, "preload.js") },
  });
  win.loadFile(path.join(__dirname, "splash.html"));
  win.once("ready-to-show", () => win.show());
  // Links (Gmail, Discord developer portal...) open in the normal browser.
  win.webContents.setWindowOpenHandler(({ url }) => (shell.openExternal(url), { action: "deny" }));
  win.webContents.on("will-navigate", (e, url) => {
    if (!url.startsWith(URL) && !url.startsWith("file:")) {
      e.preventDefault();
      shell.openExternal(url);
    }
  });
  // The PC microphone is HAVOC's own voice loop; the page never needs the browser mic here.
  win.webContents.session.setPermissionRequestHandler((_wc, permission, cb) => cb(permission === "clipboard-sanitized-write"));
  win.on("close", (e) => {
    if (!quitting) {
      e.preventDefault();
      win.hide(); // keep listening in the background; quit from the tray
    }
  });
}

function showWindow() {
  if (!win) return;
  if (win.isMinimized()) win.restore();
  win.show();
  win.focus();
}

function createTray() {
  tray = new Tray(nativeImage.createFromPath(path.join(__dirname, "icon.png")).resize({ width: 16, height: 16 }));
  tray.setToolTip("HAVOC");
  const menu = () =>
    Menu.buildFromTemplate([
      { label: "Open HAVOC", click: showWindow },
      { type: "separator" },
      {
        label: "Start with Windows", type: "checkbox", checked: app.getLoginItemSettings().openAtLogin,
        click: (item) => app.setLoginItemSettings({ openAtLogin: item.checked, args: ["--hidden"] }),
      },
      { label: "Open data folder", click: () => shell.openPath(HOME) },
      { label: "Open log", click: () => shell.openPath(LOG) },
      { type: "separator" },
      { label: "Quit HAVOC", click: () => ((quitting = true), app.quit()) },
    ]);
  tray.setContextMenu(menu());
  tray.on("click", showWindow);
}

// ---------------------------------------------------------------- lifecycle
app.whenReady().then(async () => {
  log("starting; home", HOME, "backend", BACKEND);
  if (!fs.existsSync(PYTHON)) {
    const ok = await runSetup();
    if (!ok) return app.quit();
  }
  createWindow();
  createTray();
  if (process.argv.includes("--hidden")) win.once("ready-to-show", () => win.hide());
  ensureOllama();
  startBridge();
  startBrain();
  try {
    await waitForBrain();
    win.loadURL(URL);
  } catch {
    win.webContents.send?.("splash-error", `HAVOC didn't start. The log is at ${LOG}`);
  }
});

app.on("before-quit", () => {
  quitting = true;
  killTree(children.brain);
  killTree(children.bridge);
});
app.on("window-all-closed", () => {
  /* stay in the tray */
});
