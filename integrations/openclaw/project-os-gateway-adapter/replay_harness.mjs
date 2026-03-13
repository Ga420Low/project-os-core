import fs from "node:fs";
import { spawn } from "node:child_process";
import process from "node:process";

import plugin from "./index.js";

function parseArgs(argv) {
  const result = {};
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith("--")) {
      continue;
    }
    const key = token.slice(2);
    const value = argv[index + 1];
    result[key] = value;
    index += 1;
  }
  return result;
}

function runCommandWithInput(commandArgs, options) {
  return new Promise((resolve, reject) => {
    const child = spawn(commandArgs[0], commandArgs.slice(1), {
      cwd: options.cwd,
      env: options.env,
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
    });
    let stdout = "";
    let stderr = "";
    let settled = false;
    const timeoutMs = Number(options.timeoutMs || 45000);
    const timer = setTimeout(() => {
      if (settled) {
        return;
      }
      settled = true;
      child.kill();
      reject(new Error(`Command timeout after ${timeoutMs}ms`));
    }, timeoutMs);

    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });
    child.on("error", (error) => {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timer);
      reject(error);
    });
    child.on("close", (code) => {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timer);
      resolve({
        code: typeof code === "number" ? code : 1,
        stdout,
        stderr,
      });
    });

    if (options.input) {
      child.stdin.write(options.input);
    }
    child.stdin.end();
  });
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const fixturePath = args.fixture;
  if (!fixturePath) {
    throw new Error("Missing --fixture");
  }
  const fixture = JSON.parse(fs.readFileSync(fixturePath, "utf-8"));
  const warnings = [];
  const infos = [];
  let registeredHandler = null;
  let ackSent = false;

  const pluginConfig = {
    projectOsRepoRoot: args["repo-root"],
    projectOsConfigPath: args["config-path"],
    projectOsPolicyPath: args["policy-path"],
    pythonCommand: args["python-command"] || "py",
    defaultTargetProfile: fixture.pluginConfig?.defaultTargetProfile,
    defaultRequestedWorker: fixture.pluginConfig?.defaultRequestedWorker,
    defaultRiskClass: fixture.pluginConfig?.defaultRiskClass,
    enabledChannels: fixture.pluginConfig?.enabledChannels || ["discord", "webchat"],
    sendAckReplies: fixture.pluginConfig?.sendAckReplies === true,
    timeoutMs: Number(args["timeout-ms"] || 45000),
  };

  const api = {
    pluginConfig,
    config: {},
    logger: {
      info(message) {
        infos.push(String(message));
      },
      warn(message) {
        warnings.push(String(message));
      },
    },
    registerHook(name, handler) {
      if (name === "message_received") {
        registeredHandler = handler;
      }
    },
    runtime: {
      system: {
        async runCommandWithTimeout(commandArgs, options = {}) {
          return runCommandWithInput(commandArgs, options);
        },
      },
      channel: {
        discord: {
          async sendMessageDiscord() {
            ackSent = true;
            return { ok: true };
          },
        },
      },
    },
  };

  plugin.register(api);
  if (typeof registeredHandler !== "function") {
    throw new Error("message_received hook was not registered by the plugin");
  }

  const event = fixture.event;
  const context = fixture.context;
  await registeredHandler(event, context);

  const lastInfo = infos[infos.length - 1] || "";
  const commandResultMatch = warnings.find((entry) => entry.includes("Project OS dispatch failed"));
  let parsedDispatch = null;
  if (infos.length || warnings.length || lastInfo || commandResultMatch) {
    // no-op, just keep logs in result
  }

  for (const line of infos) {
    const marker = "CLI_STDOUT_JSON:";
    if (line.startsWith(marker)) {
      parsedDispatch = JSON.parse(line.slice(marker.length));
      break;
    }
  }

  const result = {
    fixture_id: fixture.fixture_id,
    description: fixture.description || null,
    warnings,
    infos,
    ack_sent: ackSent,
    dispatch_result: parsedDispatch,
  };
  process.stdout.write(JSON.stringify(result));
}

main().catch((error) => {
  process.stderr.write(String(error.stack || error.message || error));
  process.exit(1);
});
