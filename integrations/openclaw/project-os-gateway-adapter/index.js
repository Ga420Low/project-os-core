import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";

const DEFAULT_PROJECT_OS_REPO_ROOT = "D:/ProjectOS/project-os-core";
const DEFAULT_PYTHON_COMMAND = process.platform === "win32" ? "py" : "python3";
const DEFAULT_CHANNELS = new Set(["discord", "webchat"]);
const DEFAULT_OPERATOR_POLLING_INTERVAL_MS = 8000;
const DEFAULT_PROJECT_OS_TIMEOUT_MS = 10 * 60 * 1000;
const INGRESS_DEDUP_TTL_MS = 10 * 60 * 1000;
const PENDING_DISCORD_REPLY_TTL_MS = 2 * 60 * 1000;
const DISCORD_MESSAGE_MAX_LENGTH = 2000;
const DISCORD_SAFE_CHUNK_LENGTH = 1850;
const DISCORD_FAILURE_NOTICE_MAX_LENGTH = 320;
const DISCORD_MAX_LINES_PER_MESSAGE = 17;
const DISCORD_TYPING_REFRESH_MS = 5000;
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
      : DEFAULT_PROJECT_OS_TIMEOUT_MS;
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

function normalizeDiscordTarget(target) {
  const parsed = parseDiscordTarget(target);
  if (!parsed) {
    const raw = typeof target === "string" ? target.trim() : "";
    return raw || null;
  }
  if (parsed.kind === "channel") {
    return `channel:${parsed.channelId}`;
  }
  return `user:${parsed.userId}`;
}

function resolveDiscordTarget(event, ctx) {
  const candidates = [
    typeof ctx?.conversationId === "string" ? ctx.conversationId : "",
    typeof event?.metadata?.originatingTo === "string" ? event.metadata.originatingTo : "",
    typeof event?.to === "string" ? event.to : "",
  ];
  for (const candidate of candidates) {
    const normalized = parseDiscordTarget(candidate) ? normalizeDiscordTarget(candidate) : null;
    if (normalized) {
      return normalized;
    }
  }
  for (const candidate of candidates) {
    const raw = typeof candidate === "string" ? candidate.trim() : "";
    if (raw) {
      return raw;
    }
  }
  return null;
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

function normalizeDiscordAttachmentFiles(files) {
  if (!Array.isArray(files)) {
    return [];
  }
  return files
    .map((entry) => {
      if (!entry || typeof entry !== "object") {
        return null;
      }
      const artifactPath = typeof entry.path === "string" ? entry.path.trim() : "";
      if (!artifactPath) {
        return null;
      }
      const name =
        typeof entry.name === "string" && entry.name.trim()
          ? entry.name.trim()
          : path.basename(artifactPath);
      return {
        path: artifactPath,
        name,
        mimeType:
          typeof entry.mime_type === "string" && entry.mime_type.trim()
            ? entry.mime_type.trim()
            : typeof entry.content_type === "string" && entry.content_type.trim()
              ? entry.content_type.trim()
              : "application/octet-stream",
      };
    })
    .filter(Boolean);
}

function splitDiscordChunkByLines(chunk) {
  const lines = String(chunk || "").split("\n");
  if (lines.length <= DISCORD_MAX_LINES_PER_MESSAGE) {
    return [chunk];
  }
  const chunks = [];
  let buffer = [];
  for (const line of lines) {
    buffer.push(line);
    if (buffer.length >= DISCORD_MAX_LINES_PER_MESSAGE) {
      chunks.push(buffer.join("\n").trim());
      buffer = [];
    }
  }
  if (buffer.length > 0) {
    chunks.push(buffer.join("\n").trim());
  }
  return chunks.filter((item) => item);
}

function splitDiscordMessage(text) {
  const normalized = String(text || "").replace(/\r\n/g, "\n").trim();
  if (!normalized) {
    return [""];
  }
  if (normalized.length <= DISCORD_MESSAGE_MAX_LENGTH) {
    return [normalized];
  }
  const chunks = [];
  let remaining = normalized;
  while (remaining.length > DISCORD_SAFE_CHUNK_LENGTH) {
    let splitAt = remaining.lastIndexOf("\n\n", DISCORD_SAFE_CHUNK_LENGTH);
    if (splitAt < Math.floor(DISCORD_SAFE_CHUNK_LENGTH * 0.5)) {
      splitAt = remaining.lastIndexOf("\n", DISCORD_SAFE_CHUNK_LENGTH);
    }
    if (splitAt < Math.floor(DISCORD_SAFE_CHUNK_LENGTH * 0.5)) {
      splitAt = remaining.lastIndexOf(" ", DISCORD_SAFE_CHUNK_LENGTH);
    }
    if (splitAt <= 0) {
      splitAt = DISCORD_SAFE_CHUNK_LENGTH;
    }
    chunks.push(remaining.slice(0, splitAt).trim());
    remaining = remaining.slice(splitAt).trim();
  }
  if (remaining) {
    chunks.push(remaining);
  }
  return chunks.flatMap((chunk) => splitDiscordChunkByLines(chunk)).filter((chunk) => chunk);
}

function formatDiscordChunk(chunk, index, total) {
  if (total <= 1) {
    return chunk;
  }
  return `[${index + 1}/${total}]\n${chunk}`;
}

function summarizeDiscordDeliveryError(error) {
  const raw = String(error || "").replace(/\s+/g, " ").trim();
  if (!raw) {
    return "erreur inconnue";
  }
  if (raw.includes("BASE_TYPE_MAX_LENGTH")) {
    return "reponse trop longue pour Discord";
  }
  if (raw.includes("DISCORD_BOT_TOKEN")) {
    return "token Discord indisponible";
  }
  if (raw.includes("unsupported Discord target")) {
    return "cible Discord invalide";
  }
  return raw.length <= DISCORD_FAILURE_NOTICE_MAX_LENGTH ? raw : `${raw.slice(0, DISCORD_FAILURE_NOTICE_MAX_LENGTH - 3)}...`;
}

function extractResponseManifest(replyLike) {
  if (!replyLike || typeof replyLike !== "object") {
    return null;
  }
  const directManifest =
    replyLike.response_manifest && typeof replyLike.response_manifest === "object"
      ? replyLike.response_manifest
      : null;
  if (directManifest) {
    return directManifest;
  }
  const metadataManifest =
    replyLike.metadata && typeof replyLike.metadata === "object" && replyLike.metadata.response_manifest
      ? replyLike.metadata.response_manifest
      : null;
  return metadataManifest && typeof metadataManifest === "object" ? metadataManifest : null;
}

async function sendDiscordMessageDirectOnce(channelId, token, text, options = {}) {
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
  const files = normalizeDiscordAttachmentFiles(options.attachments);
  const request = {
    method: "POST",
    headers: {
      Authorization: `Bot ${token}`,
    },
  };
  if (files.length > 0) {
    const form = new FormData();
    const attachmentRefs = [];
    for (let index = 0; index < files.length; index += 1) {
      const file = files[index];
      const buffer = await fs.readFile(file.path);
      form.append(`files[${index}]`, new Blob([buffer], { type: file.mimeType }), file.name);
      attachmentRefs.push({
        id: index,
        filename: file.name,
      });
    }
    payload.attachments = attachmentRefs;
    form.append("payload_json", JSON.stringify(payload));
    request.body = form;
  } else {
    request.headers["Content-Type"] = "application/json";
    request.body = JSON.stringify(payload);
  }

  const response = await fetch(`https://discord.com/api/v10/channels/${channelId}/messages`, request);
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`discord message send failed (${response.status}): ${body}`);
  }
  return response.json();
}

async function sendDiscordTypingDirectOnce(channelId, token) {
  const response = await fetch(`https://discord.com/api/v10/channels/${channelId}/typing`, {
    method: "POST",
    headers: {
      Authorization: `Bot ${token}`,
    },
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`discord typing send failed (${response.status}): ${body}`);
  }
}

async function startDiscordTypingLoop(api, target) {
  const token = resolveDiscordRestToken();
  if (!token) {
    return null;
  }
  let channelId = null;
  try {
    channelId = await resolveDiscordRestChannelId(target, token);
    await sendDiscordTypingDirectOnce(channelId, token);
  } catch (error) {
    api.logger.warn(`[project-os-gateway-adapter] discord typing start failed: ${String(error)}`);
    return null;
  }
  let stopped = false;
  const interval = setInterval(() => {
    if (stopped) {
      return;
    }
    void sendDiscordTypingDirectOnce(channelId, token).catch((error) => {
      api.logger.warn(`[project-os-gateway-adapter] discord typing refresh failed: ${String(error)}`);
    });
  }, DISCORD_TYPING_REFRESH_MS);
  detachTimer(interval);
  return {
    stop() {
      stopped = true;
      clearInterval(interval);
    },
  };
}

async function sendDiscordMessageDirect(api, target, text, options = {}) {
  const token = resolveDiscordRestToken();
  if (!token) {
    throw new Error("DISCORD_BOT_TOKEN is not available in the gateway process environment");
  }

  const channelId = await resolveDiscordRestChannelId(target, token);
  const rawChunks = splitDiscordMessage(text);
  const total = rawChunks.length;
  const attachments = normalizeDiscordAttachmentFiles(options.attachments);
  const results = [];
  for (let index = 0; index < rawChunks.length; index += 1) {
    const chunkText = formatDiscordChunk(rawChunks[index], index, total);
    const result = await sendDiscordMessageDirectOnce(channelId, token, chunkText, {
      replyTo: index === 0 ? options.replyTo : undefined,
      components: index === total - 1 ? options.components : undefined,
      attachments: index === total - 1 ? attachments : undefined,
    });
    results.push(result);
  }
  const lastResult = results[results.length - 1] || null;
  api.logger.info(
    `[project-os-gateway-adapter] sent Project OS Discord reply target=${target} chunks=${String(total)} message_id=${String(lastResult?.id || "unknown")}`
  );
  return lastResult;
}

async function sendDiscordDeliveryFailureNotice(api, target, error, options = {}) {
  const reason = summarizeDiscordDeliveryError(error);
  const notice = `[Project OS] Reponse calculee mais livraison Discord echouee: ${reason}. Regarde les logs gateway pour le detail.`;
  try {
    await sendDiscordMessageDirect(api, target, notice, {
      replyTo: options.replyTo,
    });
    return true;
  } catch (fallbackError) {
    api.logger.warn(
      `[project-os-gateway-adapter] failed to send Discord delivery error notice target=${target}: ${String(fallbackError)}`
    );
    return false;
  }
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
  const reply = parsed?.operator_reply;
  if (!reply?.summary) {
    return;
  }
  const responseManifest = extractResponseManifest(reply);
  const replyKind = typeof reply.reply_kind === "string" ? reply.reply_kind.trim().toLowerCase() : "";
  const isDeepResearchLaunch =
    replyKind === "ack" &&
    Boolean(parsed?.metadata?.deep_research_job_id || reply?.metadata?.deep_research_job_id);
  if (isDeepResearchLaunch) {
    return;
  }
  if (replyKind === "ack" && !config.sendAckReplies) {
    return;
  }
  const target = resolveDiscordTarget(event, ctx);
  if (!target) {
    api.logger.warn("[project-os-gateway-adapter] missing Discord target for direct Project OS reply");
    return;
  }
  const pendingKey = rememberPendingDiscordReply(api, ctx, event, parsed, config, target);
  const replyTo =
    typeof event?.metadata?.messageId === "string" && event.metadata.messageId.trim()
      ? event.metadata.messageId.trim()
      : undefined;
  try {
    api.logger.info(
      `[project-os-gateway-adapter] sending Project OS Discord reply account=${String(ctx?.accountId || "unknown")} target=${target} reply_kind=${replyKind || "unknown"}`
    );
    await sendDiscordMessageDirect(api, target, String(responseManifest?.discord_summary || reply.summary), {
      replyTo,
      components: reply.components,
      attachments: responseManifest?.attachments,
    });
    forgetPendingDiscordReply(api, pendingKey);
  } catch (error) {
    api.logger.warn(`[project-os-gateway-adapter] direct Discord Project OS reply failed: ${String(error)}`);
    const failureNotice = `[Project OS] Reponse calculee mais non livree completement. Cause: ${summarizeDiscordDeliveryError(error)}.`;
    overwritePendingDiscordReply(api, pendingKey, failureNotice, "error");
    const noticeSent = await sendDiscordDeliveryFailureNotice(api, target, error, { replyTo });
    if (noticeSent) {
      forgetPendingDiscordReply(api, pendingKey);
    }
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
  const normalizedConversationId = normalizeDiscordTarget(conversationId);
  if (!normalizedChannelId || !normalizedConversationId) {
    return null;
  }
  return `${normalizedChannelId}|${normalizedAccountId || "default"}|${normalizedConversationId}`;
}

function rememberPendingDiscordReply(api, ctx, event, parsed, config, targetOverride) {
  const reply = parsed?.operator_reply;
  if (!reply?.summary) {
    return null;
  }
  const responseManifest = extractResponseManifest(reply);
  const replyKind = typeof reply.reply_kind === "string" ? reply.reply_kind.trim().toLowerCase() : "";
  if (!replyKind) {
    return null;
  }
  if (replyKind === "ack" && !config.sendAckReplies) {
    return null;
  }
  const key = buildPendingDiscordReplyKey(
    "discord",
    ctx.accountId,
    targetOverride || resolveDiscordTarget(event, ctx)
  );
  if (!key) {
    api.logger.warn("[project-os-gateway-adapter] Cannot persist pending Discord reply without conversation target");
    return null;
  }
  prunePendingDiscordReplyCache(api).set(key, {
    text: String(responseManifest?.discord_summary || reply.summary),
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

function overwritePendingDiscordReply(api, key, text, replyKind = "error") {
  if (!key) {
    return;
  }
  const cache = prunePendingDiscordReplyCache(api);
  const entry = cache.get(key);
  if (!entry) {
    return;
  }
  cache.set(key, {
    ...entry,
    text: String(text || ""),
    replyKind,
    storedAt: Date.now(),
  });
}

function consumePendingDiscordReply(api, ctx, event) {
  const key = buildPendingDiscordReplyKey("discord", ctx.accountId, resolveDiscordTarget(event, ctx));
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

function operatorDeliveryInflightCache(api) {
  if (!api._projectOsOperatorDeliveryInflight) {
    api._projectOsOperatorDeliveryInflight = new Set();
  }
  return api._projectOsOperatorDeliveryInflight;
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
    const inflight = operatorDeliveryInflightCache(api);
    if (inflight.has(deliveryId)) {
      continue;
    }
    inflight.add(deliveryId);

    try {
      const payload = delivery.payload && typeof delivery.payload === "object" ? delivery.payload : {};
      const channelHint = typeof delivery.channel_hint === "string" ? delivery.channel_hint : "runs_live";
      const deliveryGuarantee =
        typeof delivery.delivery_guarantee === "string" && delivery.delivery_guarantee.trim()
          ? delivery.delivery_guarantee.trim()
          : typeof payload.delivery_guarantee === "string" && payload.delivery_guarantee.trim()
            ? payload.delivery_guarantee.trim()
            : "important";
      const target = resolveOperatorDeliveryTarget(config, payload, channelHint);

      if (!target) {
        await ackOperatorDelivery(api, config, deliveryId, "pending", "discord_target_not_configured", {
          channel_hint: channelHint,
          delivery_guarantee: deliveryGuarantee,
          delivery_blocker: "discord_target_not_configured",
        });
        continue;
      }

      const responseManifest = extractResponseManifest(payload);
      const text =
        typeof responseManifest?.discord_summary === "string" && responseManifest.discord_summary.trim()
          ? responseManifest.discord_summary.trim()
          : typeof payload.text === "string" && payload.text.trim()
            ? payload.text.trim()
            : `[Project OS] ${channelHint}`;
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
          attachments: responseManifest?.attachments,
        });
        await ackOperatorDelivery(api, config, deliveryId, "delivered", undefined, {
          channel_hint: channelHint,
          target,
          reply_to: replyTo,
          components_enabled: Boolean(components),
          attachment_count: Array.isArray(responseManifest?.attachments) ? responseManifest.attachments.length : 0,
          account_id: accountId,
          delivery_guarantee: deliveryGuarantee,
        });
      } catch (error) {
        const failureNoticeSent = await sendDiscordDeliveryFailureNotice(api, target, error, { replyTo });
        await ackOperatorDelivery(api, config, deliveryId, "pending", String(error), {
          channel_hint: channelHint,
          target,
          reply_to: replyTo,
          components_enabled: Boolean(components),
          attachment_count: Array.isArray(responseManifest?.attachments) ? responseManifest.attachments.length : 0,
          account_id: accountId,
          delivery_guarantee: deliveryGuarantee,
          failure_notice_sent: failureNoticeSent,
        });
      }
    } finally {
      inflight.delete(deliveryId);
    }
  }
}

function startOperatorDeliveryPolling(api) {
  if (api._projectOsOperatorDeliveryPollingStarted) {
    return;
  }
  api._projectOsOperatorDeliveryPollingStarted = true;
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
  if (api._projectOsSchedulerPollingStarted) {
    return;
  }
  api._projectOsSchedulerPollingStarted = true;
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
        return;
      }

      if (ingressDedupKey && isRecentIngressDuplicate(api, ingressDedupKey)) {
        api.logger.info(
          `[project-os-gateway-adapter] ignored recent duplicate ingress channel=${liveChannelId || "unknown"} conversation=${String(ctx.conversationId || "unknown")}`
        );
        return;
      }

    const payload = buildPayload(event, ctx, runtimeConfig);
      rememberIngressKey(api, ingressDedupKey);
      let typingHandle = null;

      try {
        if (liveChannelId === "discord") {
          const target = resolveDiscordTarget(event, ctx);
          if (target) {
            typingHandle = await startDiscordTypingLoop(api, target);
          }
        }
        const { result, parsed } = await dispatchToProjectOs(api, payload, runtimeConfig);

        if (result.code !== 0 && !parsed) {
          forgetIngressKey(api, ingressDedupKey);
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

        if (String(ctx.channelId).toLowerCase() === "discord") {
          await maybeSendDiscordImmediateReply(api, event, ctx, parsed, runtimeConfig);
        }
      } catch (error) {
        forgetIngressKey(api, ingressDedupKey);
        api.logger.warn(
          `[project-os-gateway-adapter] ${error?.stack || error?.message || String(error)}`
        );
      } finally {
        typingHandle?.stop?.();
      }
    };

    const handleMessageSending = async (event, ctx) => {
      const runtimeConfig = resolveConfig(api);
      if (!shouldSuppressNativeDiscordReply(event, ctx, runtimeConfig)) {
        return;
      }

      const target = resolveDiscordTarget(event, ctx) || "unknown";
      const pendingReply = consumePendingDiscordReply(api, ctx, event);
      if (pendingReply && pendingReply.text) {
        api.logger.info(
          `[project-os-gateway-adapter] guardrail replaced unexpected native OpenClaw Discord reply account=${String(ctx.accountId || "unknown")} target=${target} reply_kind=${pendingReply.replyKind}`
        );
        return { content: pendingReply.text };
      }
      api.logger.info(
        `[project-os-gateway-adapter] guardrail suppressed unexpected native OpenClaw Discord reply account=${String(ctx.accountId || "unknown")} target=${target}`
      );
      return { cancel: true };
    };

    // Upstream OpenClaw 2026.3.12 fires message_received as fire-and-forget.
    // This handler is forward-only and cannot suppress native replies by itself.
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
    // Guardrail only: direct REST send is the primary Project OS egress path.
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
