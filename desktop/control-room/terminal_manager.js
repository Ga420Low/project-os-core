const os = require("os");
const path = require("path");
const pty = require("node-pty");

const POWERSHELL = process.platform === "win32" ? "powershell.exe" : process.env.SHELL || "bash";

function buildPresets(repoRoot, pythonCommand) {
  const desktopScript = path.join(repoRoot, "scripts", "project_os_desktop_control_room.py");
  const openClawLog = path.join(os.homedir(), "AppData", "Local", "Temp", "openclaw", `openclaw-${new Date().toISOString().slice(0, 10)}.log`);
  return {
    master_codex: {
      roleId: "master_codex",
      title: "Codex",
      command: "codex",
      cwd: repoRoot,
      persistent: true
    },
    gateway_live: {
      roleId: "gateway_live",
      title: "Gateway",
      command: `${pythonCommand} "${desktopScript}" startup-status --limit 4`,
      cwd: repoRoot,
      persistent: false
    },
    logs_live: {
      roleId: "logs_live",
      title: "Logs",
      command: `if (Test-Path "${openClawLog}") { Get-Content "${openClawLog}" -Tail 40 -Wait } else { Write-Host "OpenClaw log introuvable: ${openClawLog}" }`,
      cwd: repoRoot,
      persistent: false
    },
    git_tools: {
      roleId: "git_tools",
      title: "Git",
      command: "git status",
      cwd: repoRoot,
      persistent: false
    },
    test_runner: {
      roleId: "test_runner",
      title: "Tests",
      command: `${pythonCommand} -m pytest tests/unit/test_desktop_control_room.py`,
      cwd: repoRoot,
      persistent: false
    },
    special_run: {
      roleId: "special_run",
      title: "Special Run",
      command: "",
      cwd: repoRoot,
      persistent: false
    }
  };
}

class TerminalManager {
  constructor({ repoRoot, pythonCommand, onData, onExit }) {
    this.repoRoot = repoRoot;
    this.pythonCommand = pythonCommand;
    this.onData = onData;
    this.onExit = onExit;
    this.sessions = new Map();
    this.presets = buildPresets(repoRoot, pythonCommand);
  }

  list() {
    return Array.from(this.sessions.values()).map((session) => session.meta);
  }

  ensurePersistentPanels(panels = []) {
    const desired = Array.isArray(panels) && panels.length > 0 ? panels : [this.presets.master_codex];
    desired.forEach((panel) => {
      const roleId = panel.role_id || panel.roleId || panel.kind || "special_run";
      const existing = this.findByRole(roleId);
      if (!existing) {
        this.create({ roleId, title: panel.title, command: panel.command, cwd: panel.cwd, persistent: panel.persistent !== false });
      }
    });
  }

  findByRole(roleId) {
    return Array.from(this.sessions.values()).find((session) => session.meta.roleId === roleId);
  }

  create({ roleId = "special_run", title, command, cwd, persistent } = {}) {
    const preset = this.presets[roleId] || this.presets.special_run;
    if (roleId === "master_codex") {
      const existing = this.findByRole("master_codex");
      if (existing) {
        return existing.meta;
      }
    }
    const meta = {
      terminalId: `terminal_${Date.now()}_${Math.random().toString(16).slice(2, 8)}`,
      roleId,
      title: title || preset.title,
      command: command !== undefined ? command : preset.command,
      cwd: cwd || preset.cwd || this.repoRoot,
      persistent: persistent !== undefined ? persistent : preset.persistent,
      status: "running"
    };
    const shellArgs = this.buildShellArgs(meta.command);
    const ptyProcess = pty.spawn(POWERSHELL, shellArgs, {
      name: "xterm-color",
      cols: 140,
      rows: 22,
      cwd: meta.cwd,
      env: process.env
    });
    ptyProcess.onData((data) => {
      this.onData({ terminalId: meta.terminalId, data });
    });
    ptyProcess.onExit((event) => {
      meta.status = "exited";
      meta.exitCode = event.exitCode;
      meta.signal = event.signal;
      this.onExit({ terminalId: meta.terminalId, exitCode: event.exitCode, signal: event.signal });
    });
    this.sessions.set(meta.terminalId, { meta, ptyProcess });
    return meta;
  }

  write(terminalId, data) {
    const session = this.sessions.get(terminalId);
    if (!session) {
      return false;
    }
    session.ptyProcess.write(data);
    return true;
  }

  resize(terminalId, cols, rows) {
    const session = this.sessions.get(terminalId);
    if (!session) {
      return false;
    }
    session.ptyProcess.resize(Math.max(40, cols || 80), Math.max(10, rows || 24));
    return true;
  }

  close(terminalId) {
    const session = this.sessions.get(terminalId);
    if (!session) {
      return false;
    }
    session.ptyProcess.kill();
    this.sessions.delete(terminalId);
    return true;
  }

  buildShellArgs(command) {
    if (process.platform === "win32") {
      if (command) {
        return ["-NoLogo", "-NoExit", "-Command", command];
      }
      return ["-NoLogo"];
    }
    if (command) {
      return ["-lc", command];
    }
    return ["-l"];
  }
}

module.exports = { TerminalManager, buildPresets };
