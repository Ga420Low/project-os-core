import crypto from "node:crypto";

const DEFAULT_PROJECT_OS_REPO_ROOT = "D:/ProjectOS/project-os-core";
const DEFAULT_PYTHON_COMMAND = process.platform === "win32" ? "py" : "python3";
const DEFAULT_CHANNELS = new Set(["discord", "webchat"]);
const DEFAULT_OPERATOR_POLLING_INTERVAL_MS = 8000;
const INGRESS_DEDUP_TTL_MS = 10 * 60 * 1000;
const PENDING_DISCORD_REPLY_TTL_MS = 2 * 60 * 1000;
const SAFE_ENV_KEYS = new Set([
  "APPDATA",
  "COMSPEC",
  "HOME",
  "HOMEDRIVE",
  "HOMEPATH",
  "HTTPS_PROXY",
  "HTTP_PROXY",
  "LOCALAPPDATA",
  "NO_PROXY",
  "OS",
  "PATH",
  "PATHEXT",
  "PROGRAMDATA",
  "ProgramData",
  "ProgramFiles",
  "ProgramFiles(x86)",
  "PUBLIC",
  "SSL_CERT_DIR",
  "SSL_CERT_FILE",
  "SYSTEMDRIVE",
  "SYSTEMROOT",
  "SystemDrive",
  "SystemRoot",
  "TEMP",
  "TMP",
  "USERPROFILE",
  "WINDIR",
]);
const SAFE_ENV_PREFIXES = [
  "ANTHROPIC_",
  "GH_",
  "INFISICAL_",
  "OM_",
  "OPENAI_",
  "OPENCLAW_",
  "PROJECT_OS_",
  "PY_",
  "PYTHON",
  "REQUESTS_",
  "UV_",
];

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

function buildProjectOsEnv(baseEnv = process.env) {
  const filtered = {};
  for (const [key, value] of Object.entries(baseEnv || {})) {
    if (typeof value !== "string" || !value) {
      continue;
    }
    if (SAFE_ENV_KEYS.has(key) || SAFE_ENV_PREFIXES.some((prefix) => key.startsWith(prefix))) {
      filtered[key] = value;
    }
  }
  return filtered;
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
      env: buildProjectOsEnv(),
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

function resolveDiscordRestToken() {
  const token = typeof process.env.DISCORD_BOT_TOKEN === "string" ? process.env.DISCORD_BOT_TOKEN.trim() : "";
  return token || null;
}

function parseDiscordTarget(target) {
  const raw = typeof target === "string" ? target.trim() : "";
  if (!raw) {
    return null;
  }
  if (raw.startsWith("channel:")) {
    const channelId = raw.slice("channel:".length).trim();
    return channelId ? { kind: "channel", channelId } : null;
  }
  if (raw.startsWith("user:")) {
    const userId = raw.slice("user:".length).trim();
    return userId ? { kind: "user", userId } : null;
  }
  return /^\d+$/.test(raw) ? { kind: "channel", channelId: raw } : null;
}

async function resolveDiscordRestChannelId(target, token) {
  const parsed = parseDiscordTarget(target);
  if (!parsed) {
    throw new Error(`unsupported Discord target: ${String(target || "unknown")}`);
  }
  if (parsed.kind === "channel") {
    return parsed.channelId;
  }

  const response = await fetch("https://discord.com/api/v10/users/@me/channels", {
    method: "POST",
    headers: {
      Authorization: `Bot ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      recipient_id: parsed.userId,
    }),
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`discord dm open failed (${response.status}): ${body}`);
  }
  const payload = await response.json();
  const channelId = typeof payload?.id === "string" ? payload.id.trim() : "";
  if (!channelId) {
    throw new Error("discord dm open returned no channel id");
  }
  return channelId;
}

function normalizeDiscordComponents(components) {
  return Array.isArray(components) ? components : undefined;
}

async function sendDiscordMessageDirect(api, target, text, options = {}) {
  const token = resolveDiscordRestToken();
  if (!token) {
    throw new Error("DISCORD_BOT_TOKEN is not available in the gateway process environment");
  }

  const channelId = await resolveDiscordRestChannelId(target, token);
  const payload = {
    content: String(text || ""),
    allowed_mentions: {
      parse: [],
      replied_user: false,
    },
  };
  if (typeof options.replyTo === "string" && options.replyTo.trim()) {
    payload.message_reference = {
      message_id: options.replyTo.trim(),
      channel_id: channelId,
      fail_if_not_exists: false,
    };
  }
  const components = normalizeDiscordComponents(options.components);
  if (components) {
    payload.components = components;
  }

  const response = await fetch(`https://discord.com/api/v10/channels/${channelId}/messages`, {
    method: "POST",
    headers: {
      Authorization: `Bot ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`discord message send failed (${response.status}): ${body}`);
  }
  const result = await response.json();
  api.logger.info(
    `[project-os-gateway-adapter] sent Project OS Discord reply target=${target} message_id=${String(result?.id || "unknown")}`
  );
  return result;
}

async function runProjectOsJsonCommand(api, config, extraArgs, input) {
  const result = await api.runtime.system.runCommandWithTimeout(buildCommandArgs(config, extraArgs), {
    timeoutMs: config.timeoutMs,
    cwd: config.projectOsRepoRoot,
    input,
    env: buildProjectOsEnv(),
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

async function maybeSendDiscordImmediateReply(api, event, ctx, parsed, config) {
  const pendingKey = rememberPendingDiscordReply(api, ctx, parsed, config);
  const reply = parsed?.operator_reply;
  if (!reply?.summary) {
    return;
  }
  const replyKind = typeof reply.reply_kind === "string" ? reply.reply_kind.trim().toLowerCase() : "";
  if (replyKind === "ack" && !config.sendAckReplies) {
    return;
  }
  const target =
    typeof ctx?.conversationId === "string" && ctx.conversationId.trim()
      ? ctx.conversationId.trim()
      : typeof event?.metadata?.originatingTo === "string" && event.metadata.originatingTo.trim()
        ? event.metadata.originatingTo.trim()
        : null;
  if (!target) {
    api.logger.warn("[project-os-gateway-adapter] missing Discord target for direct Project OS reply");
    return;
  }
  const replyTo =
    typeof event?.metadata?.messageId === "string" && event.metadata.messageId.trim()
      ? event.metadata.messageId.trim()
      : undefined;
  try {
    await sendDiscordMessageDirect(api, target, String(reply.summary), {
      replyTo,
      components: reply.components,
    });
    forgetPendingDiscordReply(api, pendingKey);
  } catch (error) {
    api.logger.warn(`[project-os-gateway-adapter] direct Discord Project OS reply failed: ${String(error)}`);
  }
}

function pendingDiscordReplyCache(api) {
  if (!api._projectOsPendingDiscordReplies) {
    api._projectOsPendingDiscordReplies = new Map();
  }
  return api._projectOsPendingDiscordReplies;
}

function prunePendingDiscordReplyCache(api, now = Date.now()) {
  const cache = pendingDiscordReplyCache(api);
  for (const [key, entry] of cache.entries()) {
    if (now - Number(entry?.storedAt || 0) > PENDING_DISCORD_REPLY_TTL_MS) {
      cache.delete(key);
    }
  }
  return cache;
}

function buildPendingDiscordReplyKey(channelId, accountId, conversationId) {
  const normalizedChannelId = String(channelId || "").trim().toLowerCase();
  const normalizedAccountId = String(accountId || "").trim().toLowerCase();
  const normalizedConversationId = String(conversationId || "").trim();
  if (!normalizedChannelId || !normalizedConversationId) {
    return null;
  }
  return `${normalizedChannelId}|${normalizedAccountId || "default"}|${normalizedConversationId}`;
}

function rememberPendingDiscordReply(api, ctx, parsed, config) {
  const reply = parsed?.operator_reply;
  if (!reply?.summary) {
    return null;
  }
  const replyKind = typeof reply.reply_kind === "string" ? reply.reply_kind.trim().toLowerCase() : "";
  if (!replyKind) {
    return null;
  }
  if (replyKind === "ack" && !config.sendAckReplies) {
    return null;
  }
  const key = buildPendingDiscordReplyKey("discord", ctx.accountId, ctx.conversationId);
  if (!key) {
    api.logger.warn("[project-os-gateway-adapter] Cannot persist pending Discord reply without conversation target");
    return null;
  }
  prunePendingDiscordReplyCache(api).set(key, {
    text: String(reply.summary),
    replyKind,
    storedAt: Date.now(),
  });
  return key;
}

function forgetPendingDiscordReply(api, key) {
  if (!key) {
    return;
  }
  pendingDiscordReplyCache(api).delete(key);
}

function consumePendingDiscordReply(api, ctx, event) {
  const key = buildPendingDiscordReplyKey("discord", ctx.accountId, event?.to);
  if (!key) {
    return null;
  }
  const cache = prunePendingDiscordReplyCache(api);
  const entry = cache.get(key);
  if (!entry) {
    return null;
  }
  cache.delete(key);
  return entry;
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

function resolveOperatorDeliveryTarget(config, payload, channelHint) {
  if (typeof payload?.target === "string" && payload.target.trim()) {
    return payload.target.trim();
  }
  return resolveOperatorTarget(config, channelHint);
}

function ingressDedupCache(api) {
  if (!api._projectOsIngressDedupCache) {
    api._projectOsIngressDedupCache = new Map();
  }
  return api._projectOsIngressDedupCache;
}

function pruneIngressDedupCache(api, now = Date.now()) {
  const cache = ingressDedupCache(api);
  for (const [key, timestamp] of cache.entries()) {
    if (now - Number(timestamp || 0) > INGRESS_DEDUP_TTL_MS) {
      cache.delete(key);
    }
  }
  return cache;
}

function buildIngressDedupKey(event, ctx) {
  const metadata = event && typeof event.metadata === "object" ? event.metadata : {};
  const messageId =
    typeof metadata.messageId === "string" && metadata.messageId.trim()
      ? metadata.messageId.trim()
      : undefined;
  const conversationKey =
    typeof ctx?.conversationId === "string" && ctx.conversationId.trim()
      ? ctx.conversationId.trim()
      : typeof metadata.threadId === "string" && metadata.threadId.trim()
        ? metadata.threadId.trim()
        : typeof metadata.channelId === "string" && metadata.channelId.trim()
          ? metadata.channelId.trim()
          : undefined;
  const messageText = typeof event?.content === "string" ? event.content.trim() : "";
  if (!messageId || !conversationKey || !messageText) {
    return null;
  }
  const contentHash = crypto.createHash("sha256").update(messageText).digest("hex");
  const raw = `${String(ctx?.channelId || "unknown").toLowerCase()}|${messageId}|${conversationKey}|${contentHash}`;
  return crypto.createHash("sha256").update(raw).digest("hex");
}

function isRecentIngressDuplicate(api, dedupKey) {
  if (!dedupKey) {
    return false;
  }
  const cache = pruneIngressDedupCache(api);
  const seenAt = cache.get(dedupKey);
  return typeof seenAt === "number" && Date.now() - seenAt <= INGRESS_DEDUP_TTL_MS;
}

function rememberIngressKey(api, dedupKey) {
  if (!dedupKey) {
    return;
  }
  pruneIngressDedupCache(api).set(dedupKey, Date.now());
}

function forgetIngressKey(api, dedupKey) {
  if (!dedupKey || !api._projectOsIngressDedupCache) {
    return;
  }
  api._projectOsIngressDedupCache.delete(dedupKey);
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
    const target = resolveOperatorDeliveryTarget(config, payload, channelHint);

    if (!target) {
      await ackOperatorDelivery(api, config, deliveryId, "skipped", "discord_target_not_configured", {
        channel_hint: channelHint,
      });
      continue;
    }

    const text = typeof payload.text === "string" && payload.text.trim() ? payload.text.trim() : `[Project OS] ${channelHint}`;
    const replyTo = typeof payload.reply_to === "string" && payload.reply_to.trim() ? payload.reply_to.trim() : undefined;
    const components = payload.components && typeof payload.components === "object" ? payload.components : undefined;
    const accountId =
      typeof payload.account_id === "string" && payload.account_id.trim()
        ? payload.account_id.trim()
        : config.discordAccountId;

    try {
      await sendDiscordMessageDirect(api, target, text, {
        replyTo,
        components,
      });
      await ackOperatorDelivery(api, config, deliveryId, "delivered", undefined, {
        channel_hint: channelHint,
        target,
        reply_to: replyTo,
        components_enabled: Boolean(components),
        account_id: accountId,
      });
    } catch (error) {
      await ackOperatorDelivery(api, config, deliveryId, "pending", String(error), {
        channel_hint: channelHint,
        target,
        reply_to: replyTo,
        components_enabled: Boolean(components),
        account_id: accountId,
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
      const ingressDedupKey = buildIngressDedupKey(event, ctx);

      api.logger.info(
        `[project-os-gateway-adapter] inbound message_received channel=${liveChannelId || "unknown"} account=${String(ctx.accountId || "unknown")} conversation=${String(ctx.conversationId || "unknown")}`
      );

      if (!runtimeConfig.enabledChannels.has(liveChannelId)) {
        api.logger.info(
          `[project-os-gateway-adapter] skipped inbound message_received for channel=${liveChannelId || "unknown"} enabledChannels=${Array.from(runtimeConfig.enabledChannels).join(",") || "none"}`
        );
        return;
      }

      if (
        liveChannelId === "discord" &&
        runtimeConfig.discordAccountId &&
        typeof ctx.accountId === "string" &&
        ctx.accountId.trim() &&
        ctx.accountId.trim() !== runtimeConfig.discordAccountId
      ) {
        api.logger.info(
          `[project-os-gateway-adapter] ignored inbound discord event for non-primary account=${ctx.accountId.trim()} primary=${runtimeConfig.discordAccountId}`
        );
        return { handled: true };
      }

      if (ingressDedupKey && isRecentIngressDuplicate(api, ingressDedupKey)) {
        api.logger.info(
          `[project-os-gateway-adapter] ignored recent duplicate ingress channel=${liveChannelId || "unknown"} conversation=${String(ctx.conversationId || "unknown")}`
        );
        return { handled: true };
      }

      const payload = buildPayload(event, ctx, runtimeConfig);
      rememberIngressKey(api, ingressDedupKey);

      try {
        const { result, parsed } = await dispatchToProjectOs(api, payload, runtimeConfig);

        if (result.code !== 0 && !parsed) {
          forgetIngressKey(api, ingressDedupKey);
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

        if (String(ctx.channelId).toLowerCase() === "discord") {
          maybeSendDiscordImmediateReply(api, event, ctx, parsed, runtimeConfig);
        }

        return { handled: true };
      } catch (error) {
        forgetIngressKey(api, ingressDedupKey);
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
      const pendingReply = consumePendingDiscordReply(api, ctx, event);
      if (pendingReply && pendingReply.text) {
        api.logger.info(
          `[project-os-gateway-adapter] replaced native OpenClaw Discord reply account=${String(ctx.accountId || "unknown")} target=${target} reply_kind=${pendingReply.replyKind}`
        );
        return { content: pendingReply.text };
      }
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
