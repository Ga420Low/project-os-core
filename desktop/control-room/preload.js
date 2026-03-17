const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("projectOSDesktop", {
  startupStatus: () => ipcRenderer.invoke("desktop:startup-status"),
  runtimePayload: () => ipcRenderer.invoke("desktop:runtime-payload"),
  screenPayload: (screen) => ipcRenderer.invoke("desktop:screen-payload", screen),
  loadWorkspace: () => ipcRenderer.invoke("desktop:load-workspace"),
  saveWorkspace: (payload) => ipcRenderer.invoke("desktop:save-workspace", payload),
  runAction: (action) => ipcRenderer.invoke("desktop:action", action),
  terminals: {
    list: () => ipcRenderer.invoke("terminals:list"),
    create: (payload) => ipcRenderer.invoke("terminals:create", payload),
    write: (terminalId, data) => ipcRenderer.invoke("terminals:write", terminalId, data),
    resize: (terminalId, cols, rows) => ipcRenderer.invoke("terminals:resize", terminalId, cols, rows),
    close: (terminalId) => ipcRenderer.invoke("terminals:close", terminalId),
    presets: () => ipcRenderer.invoke("terminals:presets"),
    onData: (callback) => {
      const listener = (_event, payload) => callback(payload);
      ipcRenderer.on("terminals:data", listener);
      return () => ipcRenderer.removeListener("terminals:data", listener);
    },
    onExit: (callback) => {
      const listener = (_event, payload) => callback(payload);
      ipcRenderer.on("terminals:exit", listener);
      return () => ipcRenderer.removeListener("terminals:exit", listener);
    }
  }
});
