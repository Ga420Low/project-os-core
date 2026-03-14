const DEFAULT_PROJECT_OS_REPO_ROOT = "D:/ProjectOS/project-os-core";
const DEFAULT_PYTHON_COMMAND = process.platform === "win32" ? "py" : "python3";
const DEFAULT_CHANNELS = new Set(["discord", "webchat"]);
const DEFAULT_OPERATOR_POLLING_INTERVAL_MS = 8000;

function detachTimer(handle) {
  if (handle && typeof handle.unref === "function") {
    handle.unref();
  }
}

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
  const discordAccountId =
    typeof raw.discordAccountId === "string" && raw.discordAccountId.trim()
      ? raw.discordAccountId.trim()
      : undefined;
  const operatorTargets =
    raw.operatorTargets && typeof raw.operatorTargets === "object"
      ? Object.fromEntries(
          Object.entries(raw.operatorTargets)
            .map(([key, value]) => [String(key).trim(), typeof value === "string" ? value.trim() : ""])
            .filter(([key, value]) => key && value)
        )
      : {};
  const operatorPollingIntervalMs =
    typeof raw.operatorPollingIntervalMs === "number" &&
    Number.isFinite(raw.operatorPollingIntervalMs) &&
    raw.operatorPollingIntervalMs > 0
      ? Math.floor(raw.operatorPollingIntervalMs)
      : DEFAULT_OPERATOR_POLLING_INTERVAL_MS;
  const enablePolling = raw.enablePolling !== false;
  const suppressNativeDiscordReplies = raw.suppressNativeDiscordReplies !== false;

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
    discordAccountId,
    operatorTargets,
    operatorPollingIntervalMs,
    enablePolling,
    suppressNativeDiscordReplies,
  };
}

function shouldSuppressNativeDiscordReply(event, ctx, config) {
  const channelId = String(ctx.channelId || event?.metadata?.channel || "").toLowerCase();
  if (channelId !== "discord") {
    return false;
  }
  if (!config.suppressNativeDiscordReplies || !config.enabledChannels.has("discord")) {
    return false;
  }
  const accountId = String(ctx.accountId || event?.metadata?.accountId || "").trim();
  if (config.discordAccountId && accountId && accountId !== config.discordAccountId) {
    return false;
  }
  const target = typeof event?.to === "string" ? event.to.trim().toLowerCase() : "";
  if (target.startsWith("user:")) {
    return false;
  }
  return true;
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

function buildCommandArgs(config, extraArgs) {
  return [
    config.pythonCommand,
    `${config.projectOsRepoRoot}/scripts/project_os_entry.py`,
    "--config-path",
    config.configPath,
    "--policy-path",
    config.policyPath,
    ...(Array.isArray(extraArgs) ? extraArgs : []),
  ];
}

async function dispatchToProjectOs(api, payload, config) {
  const result = await api.runtime.system.runCommandWithTimeout(
    buildCommandArgs(config, ["gateway", "ingest-openclaw-event", "--stdin"]),
    {
      timeoutMs: config.timeoutMs,
      cwd: config.projectOsRepoRoot,
      input: JSON.stringify(payload),
      env: process.env,
    }
  );
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

async function runProjectOsJsonCommand(api, config, extraArgs, input) {
  const result = await api.runtime.system.runCommandWithTimeout(buildCommandArgs(config, extraArgs), {
    timeoutMs: config.timeoutMs,
    cwd: config.projectOsRepoRoot,
    input,
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

  const conversationId = typeof ctx.conversationId === "string" ? ctx.conversationId.trim() : "";
  const target = isGroup
    ? (conversationId || undefined)
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

async function pullOperatorDeliveries(api, config) {
  const { result, parsed } = await runProjectOsJsonCommand(
    api,
    config,
    ["api-runs", "pull-operator-deliveries", "--status", "pending", "--limit", "10"],
    undefined
  );
  if (result.code !== 0) {
    throw new Error(result.stderr || "Project OS operator delivery poll failed");
  }
  return Array.isArray(parsed?.deliveries) ? parsed.deliveries : [];
}

async function ackOperatorDelivery(api, config, deliveryId, status, error, metadata) {
  const args = ["api-runs", "ack-operator-delivery", "--delivery-id", deliveryId, "--status", status];
  if (typeof error === "string" && error) {
    args.push("--error", error);
  }
  if (metadata && typeof metadata === "object") {
    args.push("--metadata", JSON.stringify(metadata));
  }
  const { result } = await runProjectOsJsonCommand(api, config, args, undefined);
  if (result.code !== 0) {
    throw new Error(result.stderr || `Failed to ack operator delivery ${deliveryId}`);
  }
}

function resolveOperatorTarget(config, channelHint) {
  if (!channelHint) {
    return config.operatorTargets.default;
  }
  return config.operatorTargets[channelHint] || config.operatorTargets.default;
}

async function flushOperatorDeliveries(api, config) {
  if (!config.discordAccountId) {
    return;
  }
  if (!config.operatorTargets || Object.keys(config.operatorTargets).length === 0) {
    return;
  }

  const deliveries = await pullOperatorDeliveries(api, config);
  for (const delivery of deliveries) {
    const deliveryId = typeof delivery.delivery_id === "string" ? delivery.delivery_id : "";
    if (!deliveryId) {
      continue;
    }

    const payload = delivery.payload && typeof delivery.payload === "object" ? delivery.payload : {};
    const channelHint = typeof delivery.channel_hint === "string" ? delivery.channel_hint : "runs_live";
    const target = resolveOperatorTarget(config, channelHint);

    if (!target) {
      await ackOperatorDelivery(api, config, deliveryId, "skipped", "discord_target_not_configured", {
        channel_hint: channelHint,
      });
      continue;
    }

    const text = typeof payload.text === "string" && payload.text.trim() ? payload.text.trim() : `[Project OS] ${channelHint}`;

    try {
      await api.runtime.channel.discord.sendMessageDiscord(target, text, {
        cfg: api.config,
        accountId: config.discordAccountId,
      });
      await ackOperatorDelivery(api, config, deliveryId, "delivered", undefined, {
        channel_hint: channelHint,
        target,
      });
    } catch (error) {
      await ackOperatorDelivery(api, config, deliveryId, "pending", String(error), {
        channel_hint: channelHint,
        target,
      });
    }
  }
}

function startOperatorDeliveryPolling(api) {
  let busy = false;

  const tick = async () => {
    if (busy) {
      return;
    }
    busy = true;
    try {
      const config = resolveConfig(api);
      await flushOperatorDeliveries(api, config);
    } catch (error) {
      api.logger.warn(`[project-os-gateway-adapter] operator delivery polling failed: ${String(error)}`);
    } finally {
      busy = false;
    }
  };

  const config = resolveConfig(api);
  if (!config.discordAccountId || !config.operatorTargets || Object.keys(config.operatorTargets).length === 0) {
    api.logger.info("[project-os-gateway-adapter] operator delivery polling disabled (missing discordAccountId/operatorTargets)");
    return;
  }

  const initialTick = setTimeout(() => {
    void tick();
  }, 1500);
  const recurringTick = setInterval(() => {
    void tick();
  }, config.operatorPollingIntervalMs);

  if (!api._projectOsIntervals) {
    api._projectOsIntervals = [];
  }
  api._projectOsIntervals.push(initialTick, recurringTick);

  detachTimer(initialTick);
  detachTimer(recurringTick);
}

function startSchedulerPolling(api) {
  let busy = false;

  const tick = async () => {
    if (busy) {
      return;
    }
    busy = true;
    try {
      const config = resolveConfig(api);
      const { result } = await runProjectOsJsonCommand(api, config, ["scheduler", "tick"], undefined);
      if (result.code !== 0) {
        api.logger.warn(`[project-os-gateway-adapter] scheduler tick failed: ${result.stderr || "no stderr"}`);
      }
    } catch (error) {
      api.logger.warn(`[project-os-gateway-adapter] scheduler tick error: ${String(error)}`);
    } finally {
      busy = false;
    }
  };

  const initialTick = setTimeout(() => {
    void tick();
  }, 2500);
  const recurringTick = setInterval(() => {
    void tick();
  }, 60000);

  if (!api._projectOsIntervals) {
    api._projectOsIntervals = [];
  }
  api._projectOsIntervals.push(initialTick, recurringTick);

  detachTimer(initialTick);
  detachTimer(recurringTick);
}

const plugin = {
  id: "project-os-gateway-adapter",
  name: "Project OS Gateway Adapter",
  description: "Forward operator channel events from OpenClaw into Project OS",
  register(api) {
    const config = resolveConfig(api);

    if (config.enablePolling) {
      startOperatorDeliveryPolling(api);
      startSchedulerPolling(api);
    } else {
      api.logger.info("[project-os-gateway-adapter] polling disabled (enablePolling=false)");
    }

    const handleMessageReceived = async (event, ctx) => {
      const runtimeConfig = resolveConfig(api);
      const liveChannelId = String(ctx.channelId || "").toLowerCase();

      api.logger.info(
        `[project-os-gateway-adapter] inbound message_received channel=${liveChannelId || "unknown"} account=${String(ctx.accountId || "unknown")} conversation=${String(ctx.conversationId || "unknown")}`
      );

      if (!runtimeConfig.enabledChannels.has(liveChannelId)) {
        api.logger.info(
          `[project-os-gateway-adapter] skipped inbound message_received for channel=${liveChannelId || "unknown"} enabledChannels=${Array.from(runtimeConfig.enabledChannels).join(",") || "none"}`
        );
        return;
      }

      const payload = buildPayload(event, ctx, runtimeConfig);

      try {
        const { result, parsed } = await dispatchToProjectOs(api, payload, runtimeConfig);

        if (result.code !== 0 && !parsed) {
          api.logger.warn(
            `[project-os-gateway-adapter] Project OS dispatch failed with code ${String(result.code)}: ${result.stderr || "no stderr"}`
          );
          return { handled: true };
        }

        if (parsed) {
          api.logger.info(`CLI_STDOUT_JSON:${JSON.stringify(parsed)}`);
        }

        api.logger.info(
          `[project-os-gateway-adapter] forwarded ${ctx.channelId}:${ctx.conversationId || "no-conversation"} to Project OS`
        );

        if (runtimeConfig.sendAckReplies && String(ctx.channelId).toLowerCase() === "discord") {
          await maybeSendDiscordAck(api, event, ctx, parsed);
        }

        return { handled: true };
      } catch (error) {
        api.logger.warn(
          `[project-os-gateway-adapter] ${error?.stack || error?.message || String(error)}`
        );
        return { handled: true };
      }
    };

    const handleMessageSending = async (event, ctx) => {
      const runtimeConfig = resolveConfig(api);
      if (!shouldSuppressNativeDiscordReply(event, ctx, runtimeConfig)) {
        return;
      }

      const target = typeof event?.to === "string" ? event.to : "unknown";
      api.logger.info(
        `[project-os-gateway-adapter] suppressed native OpenClaw Discord reply account=${String(ctx.accountId || "unknown")} target=${target}`
      );
      return { cancel: true };
    };

    if (typeof api.on === "function") {
      api.on("message_received", handleMessageReceived, {
        priority: 0,
      });
    } else {
      api.registerHook("message_received", handleMessageReceived, {
        name: "project-os-gateway-adapter.message_received",
        description: "Forward inbound operator channel messages to the Project OS gateway.",
      });
    }

    // message_sending must use registerHook — api.on() does not support it in all versions
    if (typeof api.registerHook === "function") {
      api.registerHook("message_sending", handleMessageSending, {
        name: "project-os-gateway-adapter.message_sending",
        description: "Suppress native OpenClaw Discord auto-replies so Project OS remains the only operator voice.",
      });
    } else if (typeof api.on === "function") {
      api.on("message_sending", handleMessageSending, {
        priority: 100,
      });
    }
  },
};

export default plugin;