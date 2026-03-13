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
- enabled channels: `discord`, `webchat`, `internal`
- ack replies: disabled by default

## Suggested install path

OpenClaw can load workspace or global extensions. For development, link or copy this folder into:

- `<workspace>/.openclaw/extensions/project-os-gateway-adapter/`
- or `~/.openclaw/extensions/project-os-gateway-adapter/`

The package already exposes:

- `openclaw.extensions = ["./index.js"]`
