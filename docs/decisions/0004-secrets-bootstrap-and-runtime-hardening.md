# 0004 - Secrets, Bootstrap, and Runtime Hardening

## Status
Accepted

## Context

`Project OS` must stop depending on repository-local secrets and prototype-grade bootstrap behavior.
The core now runs as a production-like mono-PC system with:

- storage split across `D:` hot/warm and `E:` cold archive
- a forbidden archive subtree at `E:\DO_NOT_TOUCH`
- OpenMemory as primary memory
- SQLite as canonical system state

Without a hardened bootstrap and secret policy, the rest of the stack would inherit unsafe defaults.

## Decision

- Secrets are resolved through a provider chain, not from tracked repository files.
- Provider order is:
  1. `Infisical` when available and configured
  2. process environment
  3. Windows user environment
  4. local fallback file outside the repo
- Repository `.env` files are migrated out of the repo and removed.
- Bootstrap is idempotent and records canonical state in SQLite and on disk.
- `doctor --strict` fails when critical prerequisites are missing.
- Runtime evidence and journal files are append-only, validated, and written only under managed roots.

## Consequences

- Secrets no longer live in the repo.
- Bootstrap and doctor become enforceable gates instead of informational commands.
- Future gateway/orchestration layers can assume stable storage, secret resolution, and runtime invariants.
