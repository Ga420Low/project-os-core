const { app, BrowserWindow, ipcMain } = require("electron");
const { execFile } = require("child_process");
const fs = require("fs");
const path = require("path");
const { TerminalManager } = require("./terminal_manager");

const repoRoot = path.resolve(__dirname, "..", "..");
const desktopScript = path.join(repoRoot, "scripts", "project_os_desktop_control_room.py");
const appIcon = path.join(__dirname, "build", "icon.png");
let mainWindow = null;
let terminalManager = null;

function configureLiveReload() {
  if (app.isPackaged) {
    return;
  }
  const electronBinary = process.platform === "win32"
    ? path.join(__dirname, "node_modules", ".bin", "electron.cmd")
    : path.join(__dirname, "node_modules", ".bin", "electron");
  try {
    const options = {
      awaitWriteFinish: {
        stabilityThreshold: 300,
        pollInterval: 100,
      },
      hardResetMethod: "exit",
    };
    if (fs.existsSync(electronBinary)) {
      options.electron = electronBinary;
    }
    require("electron-reload")(__dirname, options);
  } catch (error) {
    // Dev live reload should not block the shell if the watcher package is missing.
    console.warn("electron-reload unavailable", error);
  }
}

function pickPythonCommand() {
  return process.platform === "win32" ? "py" : "python3";
}

function runDesktopCommand(command, payload) {
  return new Promise((resolve, reject) => {
    const args = [desktopScript, command];
    if (command === "save-workspace") {
      args.push("--payload", JSON.stringify(payload || {}));
    } else if (command === "screen-payload" && payload && payload.screen) {
      args.push("--screen", String(payload.screen));
    } else if (command === "action" && payload && payload.action) {
      args.push("--action", String(payload.action));
    }
    execFile(pickPythonCommand(), args, { cwd: repoRoot, maxBuffer: 1024 * 1024 * 4 }, (error, stdout, stderr) => {
      if (error) {
        reject(new Error(stderr || error.message));
        return;
      }
      try {
        resolve(JSON.parse(stdout));
      } catch (parseError) {
        reject(new Error(parseError.message));
      }
    });
  });
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1600,
    height: 980,
    minWidth: 1180,
    minHeight: 760,
    backgroundColor: "#07111a",
    autoHideMenuBar: true,
    title: "Project OS Control Room",
    icon: appIcon,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false
    }
  });
  mainWindow.loadFile(path.join(__dirname, "renderer", "index.html"));
  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

function bindTerminalManager() {
  terminalManager = new TerminalManager({
    repoRoot,
    pythonCommand: pickPythonCommand(),
    onData: (payload) => {
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send("terminals:data", payload);
      }
    },
    onExit: (payload) => {
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send("terminals:exit", payload);
      }
    }
  });
}

async function restorePersistentPanels() {
  const workspace = await runDesktopCommand("load-workspace");
  terminalManager.ensurePersistentPanels(workspace.persistent_panels || []);
}

ipcMain.handle("desktop:startup-status", () => runDesktopCommand("startup-status"));
ipcMain.handle("desktop:runtime-payload", () => runDesktopCommand("runtime-payload"));
ipcMain.handle("desktop:screen-payload", (_event, screen) => runDesktopCommand("screen-payload", { screen }));
ipcMain.handle("desktop:load-workspace", () => runDesktopCommand("load-workspace"));
ipcMain.handle("desktop:save-workspace", (_event, payload) => runDesktopCommand("save-workspace", payload));
ipcMain.handle("desktop:action", (_event, action) => runDesktopCommand("action", { action }));
ipcMain.handle("terminals:list", () => terminalManager.list());
ipcMain.handle("terminals:create", (_event, payload) => terminalManager.create(payload || {}));
ipcMain.handle("terminals:write", (_event, terminalId, data) => terminalManager.write(terminalId, data));
ipcMain.handle("terminals:resize", (_event, terminalId, cols, rows) => terminalManager.resize(terminalId, cols, rows));
ipcMain.handle("terminals:close", (_event, terminalId) => terminalManager.close(terminalId));
ipcMain.handle("terminals:presets", () => terminalManager.presets);

app.whenReady().then(() => {
  app.setAppUserModelId("com.projectos.controlroom");
  configureLiveReload();
  bindTerminalManager();
  createWindow();
  restorePersistentPanels().catch(() => {});
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
