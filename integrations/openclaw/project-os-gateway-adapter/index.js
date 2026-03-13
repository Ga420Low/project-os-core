const DEFAULT_PROJECT_OS_REPO_ROOT = "D:/ProjectOS/project-os-core";
const DEFAULT_PYTHON_COMMAND = process.platform === "win32" ? "py" : "python3";
const DEFAULT_CHANNELS = new Set(["discord", "webchat"]);

function resolveConfig(api) {
  const raw = api.pluginConfig && typeof api.pluginConfig === "object" ? api.pluginConfig : {};
  const projectOsRepoRoot =
    typeof raw.projectOsRepoRoot === "string" && raw.projectOsRepoRoot.trim()
      ? raw.projectOsRepoRoot.trim()
      : DEFAULT_PROJECT_OS_REPO_ROOT;
  const configPath =
    typeof raw.projectOsConfigPath === "string" && raw.projectOsConfigPath.trim()
      ? raw.projectOsConfigPath.trim()
      : `${projectOsRepoRoot}/config/storage_roots.local.json`;
  const policyPath =
    typeof raw.projectOsPolicyPath === "string" && raw.projectOsPolicyPath.trim()
      ? raw.projectOsPolicyPath.trim()
      : `${projectOsRepoRoot}/config/runtime_policy.local.json`;
  const pythonCommand =
    typeof raw.pythonCommand === "string" && raw.pythonCommand.trim()
      ? raw.pythonCommand.trim()
      : DEFAULT_PYTHON_COMMAND;
  const defaultTargetProfile =
    typeof raw.defaultTargetProfile === "string" && raw.defaultTargetProfile.trim()
      ? raw.defaultTargetProfile.trim()
      : "core";
  const defaultRequestedWorker =
    typeof raw.defaultRequestedWorker === "string" && raw.defaultRequestedWorker.trim()
      ? raw.defaultRequestedWorker.trim()
      : undefined;
  const defaultRiskClass =
    typeof raw.defaultRiskClass === "string" && raw.defaultRiskClass.trim()
      ? raw.defaultRiskClass.trim()
      : undefined;
  const enabledChannels = Array.isArray(raw.enabledChannels)
    ? new Set(raw.enabledChannels.map((item) => String(item).toLowerCase()))
    : DEFAULT_CHANNELS;
  const sendAckReplies = raw.sendAckReplies === true;
  const timeoutMs =
    typeof raw.timeoutMs === "number" && Number.isFinite(raw.timeoutMs) && raw.timeoutMs > 0
      ? Math.floor(raw.timeoutMs)
      : 45000;
  return {
    projectOsRepoRoot,
    configPath,
    policyPath,
    pythonCommand,
    defaultTargetProfile,
    defaultRequestedWorker,
    defaultRiskClass,
    enabledChannels,
    sendAckReplies,
    timeoutMs,
  };
}

function buildPayload(event, ctx, config) {
  const metadata = event.metadata && typeof event.metadata === "object" ? event.metadata : {};
  return {
    source: "openclaw",
    surface: typeof metadata.surface === "string" && metadata.surface ? metadata.surface : ctx.channelId,
    event_type: "message.received",
    event: {
      from: event.from,
      content: event.content,
      timestamp: event.timestamp,
      metadata,
    },
    context: {
      channelId: ctx.channelId,
      accountId: ctx.accountId,
      conversationId: ctx.conversationId,
    },
    config: {
      target_profile: config.defaultTargetProfile,
      requested_worker: config.defaultRequestedWorker,
      risk_class: config.defaultRiskClass,
      metadata: {
        ingress: "openclaw_plugin",
        openclaw_channel_id: ctx.channelId,
        openclaw_account_id: ctx.accountId,
        openclaw_conversation_id: ctx.conversationId,
      },
    },
  };
}

function buildCommandArgs(config) {
  return [
    config.pythonCommand,
    `${config.projectOsRepoRoot}/scripts/project_os_entry.py`,
    "--config-path",
    config.configPath,
    "--policy-path",
    config.policyPath,
    "gateway",
    "ingest-openclaw-event",
    "--stdin",
  ];
}

async function dispatchToProjectOs(api, payload, config) {
  const result = await api.runtime.system.runCommandWithTimeout(buildCommandArgs(config), {
    timeoutMs: config.timeoutMs,
    cwd: config.projectOsRepoRoot,
    input: JSON.stringify(payload),
    env: process.env,
  });
  const stdout = (result.stdout || "").trim();
  let parsed = null;
  if (stdout) {
    try {
      parsed = JSON.parse(stdout);
    } catch (error) {
      api.logger.warn(`[project-os-gateway-adapter] Failed to parse Project OS stdout as JSON: ${String(error)}`);
    }
  }
  return { result, parsed };
}

async function maybeSendDiscordAck(api, event, ctx, parsed) {
  if (!parsed?.operator_reply?.summary) {
    return;
  }
  const metadata = event.metadata && typeof event.metadata === "object" ? event.metadata : {};
  const senderId = typeof metadata.senderId === "string" && metadata.senderId ? metadata.senderId : event.from;
  const messageId = typeof metadata.messageId === "string" ? metadata.messageId : undefined;
  const isGroup = Boolean(metadata.guildId || metadata.threadId || metadata.channelName);
  const target = isGroup
    ? ctx.conversationId
      ? `channel:${ctx.conversationId}`
      : undefined
    : senderId
      ? `user:${senderId}`
      : undefined;
  if (!target) {
    api.logger.warn("[project-os-gateway-adapter] Cannot resolve Discord ack target");
    return;
  }
  await api.runtime.channel.discord.sendMessageDiscord(target, parsed.operator_reply.summary, {
    cfg: api.config,
    accountId: ctx.accountId,
    replyTo: messageId,
  });
}

const plugin = {
  id: "project-os-gateway-adapter",
  name: "Project OS Gateway Adapter",
  description: "Forward operator channel events from OpenClaw into Project OS",
  register(api) {
    api.registerHook("message_received", async (event, ctx) => {
      const config = resolveConfig(api);
      if (!config.enabledChannels.has(String(ctx.channelId || "").toLowerCase())) {
        return;
      }
      const payload = buildPayload(event, ctx, config);
      try {
        const { result, parsed } = await dispatchToProjectOs(api, payload, config);
        if (result.code !== 0 && !parsed) {
          api.logger.warn(
            `[project-os-gateway-adapter] Project OS dispatch failed with code ${String(result.code)}: ${result.stderr || "no stderr"}`
          );
          return;
        }
        if (parsed) {
          api.logger.info(`CLI_STDOUT_JSON:${JSON.stringify(parsed)}`);
        }
        api.logger.info(
          `[project-os-gateway-adapter] forwarded ${ctx.channelId}:${ctx.conversationId || "no-conversation"} to Project OS`
        );
        if (config.sendAckReplies && String(ctx.channelId).toLowerCase() === "discord") {
          await maybeSendDiscordAck(api, event, ctx, parsed);
        }
      } catch (error) {
        api.logger.warn(`[project-os-gateway-adapter] ${String(error)}`);
      }
    });
  },
};

export default plugin;
