# Project OS OpenClaw Gateway Adapter

This package keeps `OpenClaw` in the operator-facing role and forwards inbound operator events into `Project OS`.

## Role

- `OpenClaw`: channels, WebChat, Control UI, inbox, pairing
- `Project OS`: runtime truth, memory, mission router, workers, evidence

## What this adapter does

- listens to `message_received`
- maps the event to the canonical `Project OS` ingress payload
- calls:

```bash
py D:/ProjectOS/project-os-core/scripts/project_os_entry.py --config-path <...> --policy-path <...> gateway ingest-openclaw-event --stdin
```

- leaves memory/routing/approvals inside `Project OS`

## What it does not do

- it does not make `OpenClaw` the source of truth
- it does not let `OpenClaw` write canonical memory directly
- it does not bypass the `Mission Router`

## Defaults

- repo root: `D:/ProjectOS/project-os-core`
- config path: `D:/ProjectOS/project-os-core/config/storage_roots.local.json`
- policy path: `D:/ProjectOS/project-os-core/config/runtime_policy.local.json`
- python command: `py` on Windows
- enabled channels: `discord`, `webchat`
- ack replies: disabled by default
- operator delivery polling: enabled only if `discordAccountId` and `operatorTargets` are configured

## Operator delivery loop

The adapter can also relay `Project OS` operator lifecycle events to Discord.

This keeps the architecture split clean:

- `Project OS` emits canonical lifecycle events and keeps the outbox
- `OpenClaw` reads pending deliveries and sends them to Discord

Required plugin config to enable this loop:

- `discordAccountId`: Discord account configured in OpenClaw
- `operatorTargets`: map of logical channel hints to Discord targets
- `suppressNativeDiscordReplies`: keep enabled so the native OpenClaw agent does not answer in guild channels

Typical setup flow:

```bash
openclaw channels add --channel discord --token <DISCORD_BOT_TOKEN> --account discord-main
openclaw channels list
```

If you create the account with `--account discord-main`, then `discord-main` is the value to reuse as `discordAccountId`.

Example:

```json
{
  "discordAccountId": "discord-main",
  "operatorPollingIntervalMs": 8000,
  "suppressNativeDiscordReplies": true,
  "operatorTargets": {
    "runs_live": "channel:1234567890",
    "approvals": "channel:2345678901",
    "incidents": "channel:3456789012",
    "default": "channel:1234567890"
  }
}
```

Required runtime policy for Discord single voice:

```json
{
  "session": {
    "sendPolicy": {
      "default": "allow",
      "rules": [
        { "action": "deny", "match": { "channel": "discord", "chatType": "group" } },
        { "action": "deny", "match": { "channel": "discord", "chatType": "channel" } }
      ]
    }
  }
}
```

The gateway process must also expose `DISCORD_BOT_TOKEN`, because the adapter uses direct Discord REST send for the visible Project OS reply path.

Delivery policy:

- `contract_proposed` -> `approvals`
- `clarification_required` -> `approvals`
- `run_completed` -> `runs_live`
- `run_failed` -> `incidents`
- `run_reviewed` -> `runs_live`

`run_started` is filtered as operator noise and is normally not delivered to Discord.

Optional outbound payload overrides:

- `target`: bypasses `channel_hint -> operatorTargets` mapping
- `reply_to`: forwards a Discord reply target
- `components`: forwards Discord components v2 as-is
- `account_id`: overrides the default Discord account for that delivery

Artifact-first payloads are also supported:

- `response_manifest.discord_summary`: compact visible Discord text
- `response_manifest.attachments`: local artifact files to attach on the last Discord chunk
- `response_manifest.delivery_mode`: observability hint for `inline_text`, `thread_chunked_text`, or `artifact_summary`

Current UX rule:

- keep the full response in Discord chat whenever it still fits cleanly
- only attach a `PDF` for truly long/reviewable outputs
- do not attach review `.md` files in the live Discord conversation

These overrides stay optional. The normal path remains compact `channel_hint` delivery.

## Discord ownership model

For the live Discord server, the intended behavior is:

- inbound guild messages go to `Project OS` through `message_received`
- native OpenClaw Discord auto-replies are stopped structurally by `session.sendPolicy`
- visible Project OS chat replies are sent by the adapter through direct Discord REST send
- the adapter also drives the visible Discord `typing` signal during the run, because direct REST egress bypasses native auto-reply typing
- `message_sending` remains only as a secondary guardrail if a native egress still leaks through
- outbound operator lifecycle messages still go to Discord through adapter-controlled delivery

This keeps Discord single-voiced: `Project OS` speaks, `OpenClaw` transports.

## Pack 2 Discord UX

The upstream Discord features retained for the operator loop are:

- `typingMode = instant`
- `threadBindings`
- `execApprovals`
- `autoPresence`

The adapter itself stays thin:

- it does not implement custom approval logic
- it does not become the canonical thread store
- it only forwards more precise outbound Discord targets when `Project OS` already decided them

## Pack E UX and observability

The adapter now exposes the output mode rather than hiding it:

- docs-safe Discord chunking at `2000` chars max
- line-aware chunking as the last safety net
- artifact-first replies attach the full `markdown` review artifact when present
- visible delivery failure notices stay mandatory when Discord send fails

The operational UX reference lives in:

- `docs/integrations/OPENCLAW_DISCORD_OPERATIONS_UX.md`

## Suggested install path

OpenClaw can load workspace or global extensions. For development, link or copy this folder into:

- `<workspace>/.openclaw/extensions/project-os-gateway-adapter/`
- or `~/.openclaw/extensions/project-os-gateway-adapter/`

The package already exposes:

- `openclaw.extensions = ["./index.js"]`
