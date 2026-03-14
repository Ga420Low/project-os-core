# Project OS Extended Audit - 2026-03-14

## Scope

This audit covers:

- `project-os-core`
- the live local runtime under `D:\ProjectOS\runtime`
- the current `OpenClaw/Discord` loop
- the 11 GPT-5.4 PDF bricks
- the Claude audit summary provided in-thread
- a focused external scan of tools that could matter for `Project OS`

This document is intentionally audit-only. It does not apply fixes.

## Method

Primary local evidence:

- repo docs and ADRs
- runtime config and runtime SQLite state
- targeted code inspection in `src/project_os_core`
- targeted commands:
  - `py -m pytest tests/unit tests/integration -q --maxfail=5`
  - `py -m pytest -q`
  - `py scripts/project_os_entry.py doctor --strict`
  - `py scripts/project_os_entry.py openclaw doctor`

PDF source set:

- `Brique A` to `Brique K` under `D:\divers\bureau\doc`

External source set used for the tool scan:

- [OpenAI Prompt Caching](https://platform.openai.com/docs/guides/prompt-caching)
- [Anthropic Prompt Caching](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching)
- [Anthropic MCP](https://docs.anthropic.com/en/docs/mcp)
- [Anthropic Claude Code Security](https://docs.anthropic.com/en/docs/claude-code/security)
- [RouteLLM](https://github.com/lm-sys/RouteLLM)
- [PydanticAI](https://github.com/pydantic/pydantic-ai)
- [Stagehand](https://github.com/browserbase/stagehand)
- [browser-use](https://github.com/browser-use/browser-use)
- [LangGraph](https://github.com/langchain-ai/langgraph)
- [Langfuse](https://github.com/langfuse/langfuse)
- [OpenAI Agents Python](https://github.com/openai/openai-agents-python)
- [MCP Servers Catalog](https://github.com/modelcontextprotocol/servers)

## Executive Summary

The audit confirms that `Project OS` already has a meaningful local-first core: SQLite WAL persistence, memory tiers, bootstrap/doctor flows, journal evidence, targeted tests, and a live OpenClaw adapter. That is not the problem.

The current structural gaps are elsewhere:

- the product identity is still split between the user vision and a Codex-centric documentation/code trail
- the declared Discord routing truth does not match the provider actually called at runtime
- the live OpenClaw/Discord runtime is not hardened enough for a trusted operator surface
- some approval/budget/security decisions still trust mutable intent metadata
- the schema contains lifecycle/outbox pieces that are not yet proven by live runtime evidence
- the provider/cost/idempotence layer proposed by bricks C/D/F is still mostly absent

The project is not "already finished". It has a strong core, but several high-value control-plane pieces are still missing or inconsistent.

## Evidence Snapshot

### Local verification

- `py -m pytest tests/unit tests/integration -q --maxfail=5` on 2026-03-14: `108 passed in 194.17s`
- this supersedes the earlier `66 passed` snapshot from the previous audit pass
- `py -m pytest -q` on 2026-03-14: fails during collection because `third_party/` tests are picked up and local dependencies for vendored projects are not installed
- `py scripts/project_os_entry.py doctor --strict` on 2026-03-14: green
- `py scripts/project_os_entry.py openclaw doctor` on 2026-03-14: `verdict: OK`, but details still include:
  - repeated warnings that `plugins.allow` is empty and non-bundled plugins may auto-load
  - gateway service `loaded: false`
  - gateway runtime status `unknown` with a file-not-found style detail

### Runtime SQLite snapshot

Observed in `D:\ProjectOS\runtime\project_os_core.db`:

- non-SQLite tables: `55`
- `api_run_results` by status:
  - `clarification_required`: `1`
  - `completed`: `6`
  - `failed`: `1`
  - `reviewed`: `2`
- `channel_events`: `53`
- `journal_events`: `258`
- `memory_records` by tier:
  - `hot`: `2`
  - `warm`: `8`
  - `cold`: `18`
- `learning_signals`: `8`
- `noise_signals`: `4`
- `loop_signals`: `0`
- `bootstrap_states`: `1`
- `session_snapshots`: `0`
- `api_run_lifecycle_events`: `0`
- `api_run_operator_deliveries`: `0`

### OpenClaw runtime snapshot

Observed in `D:\ProjectOS\runtime\openclaw\openclaw.json`:

- `channels.discord.accounts.discord-main.token` is stored inline in the runtime config file
- `groupPolicy` is `open`
- guild channel `1482231737361891368` has `requireMention: false`
- Project OS plugin config already includes some good controls:
  - `discordAccountId`
  - `operatorTargets`
  - `suppressNativeDiscordReplies: true`
  - `sendAckReplies: true`

## P0 Findings

### P0-1 - Codex drift is still structural

Classification: `missing realignment`

Why this matters:

- the user vision is now `Claude API` for Discord discussion and `GPT API` for code
- the current repo still carries a product identity and branch policy that assume `Codex` remains a first-class operating surface

Local evidence:

- `README.md:10` says `Codex`, `OpenAI API`, `Discord`, and later `WebChat` are surfaces of the same agent
- `README.md:30-31` still says the human talks in `Codex` or `Discord`, then `Codex` prepares and launches
- `AGENTS.md:42-43` still keeps `Codex` as the direct conversation app
- `AGENTS.md:365` still requires work on `codex/*`
- `docs/decisions/0013-dual-model-operating-model.md:12-17` still defines `Codex` as a named operating component
- `docs/decisions/0013-dual-model-operating-model.md:53-58` still reserves a dedicated product lane for `Codex`
- `docs/decisions/0011-api-lead-agent-v1.md:38` still says large runs must target `codex/*`
- `src/project_os_core/api_runs/service.py:3655-3656` hard-rejects non-`codex/*` branches
- `src/project_os_core/api_runs/service.py:3848` and `:3862` still hardcode `codex/*` and `Codex review`

Impact:

- docs, CLI behavior, branch governance, and run prompts are not aligned with the intended product model
- this is not cosmetic drift; it affects branch validation, operator expectations, and future workflow design

Recommended correction lot:

- lot 1 `identite produit + conventions + suppression Codex`

### P0-2 - Discord routing truth is inconsistent

Classification: `partial but inconsistent`

Why this matters:

- the runtime should have one truthful explanation of which provider/model is used for Discord chat
- today the declared route and the executed provider do not match

Local evidence:

- `src/project_os_core/router/service.py:300-312` returns `provider="openai"` and `reason="discord_simple_route"`
- `src/project_os_core/gateway/service.py:125-129` special-cases that route
- `src/project_os_core/gateway/service.py:578-599` then calls Anthropic directly with `claude-sonnet-4-20250514`
- `src/project_os_core/gateway/service.py:579` explicitly documents that path as a Claude call

Impact:

- observability is misleading
- cost accounting cannot be trusted later if the route metadata lies
- the user vision is closer to the gateway implementation than to the router declaration, which means the code and the declared policy have diverged

Recommended correction lot:

- lot 3 `runtime truth + outbox + idempotence ingress`
- lot 4 `provider/cost layer`

### P0-3 - OpenClaw/Discord live hardening is not strong enough

Classification: `missing real hardening`

Why this matters:

- Discord is the operator surface
- the current live runtime still trusts too much by default

Local evidence:

- `D:\ProjectOS\runtime\openclaw\openclaw.json:32`, `:36`, `:42` use `groupPolicy: "open"`
- `D:\ProjectOS\runtime\openclaw\openclaw.json:50` sets `requireMention: false`
- `D:\ProjectOS\runtime\openclaw\openclaw.json` stores the Discord token inline in the runtime config file
- `py scripts/project_os_entry.py openclaw doctor` warns repeatedly that `plugins.allow` is empty and non-bundled plugins may auto-load
- the same doctor report still returns `verdict: OK`
- the same doctor report shows gateway service `loaded: false` and runtime status `unknown`

What is already good:

- `suppressNativeDiscordReplies: true` is enabled
- `sendAckReplies: true` is enabled
- logical operator targets are already mapped

Impact:

- the operator surface is not yet hardened enough for "single trusted voice" behavior
- the health signal is too optimistic for the current actual posture

Recommended correction lot:

- lot 2 `securite Discord/OpenClaw`

### P0-4 - Budget and approval decisions still trust mutable intent metadata

Classification: `unsafe source of truth`

Local evidence:

- `src/project_os_core/router/service.py:217-218` reads `daily_spend_estimate_eur` and `monthly_spend_estimate_eur` from `intent.metadata`
- `src/project_os_core/router/service.py:269-270` reads `founder_approved` and `approval_id` from `intent.metadata`
- `src/project_os_core/router/service.py:287-288` uses those values to shape the approval gate

Impact:

- a control-plane decision is still derived from request metadata instead of canonical runtime records
- approval and budget truth can be spoofed or drift from persisted state

Recommended correction lot:

- lot 3 `runtime truth + outbox + idempotence ingress`

### P0-5 - OpenMemory adapter exports `OPENAI_API_KEY` into global process env

Classification: `security boundary leak`

Local evidence:

- `src/project_os_core/memory/adapter.py:47-54`
- `src/project_os_core/memory/adapter.py:51` sets `os.environ["OPENAI_API_KEY"]`

Impact:

- a library adapter expands the secret blast radius to the entire process environment
- this conflicts with the security direction described in brick `I`

Recommended correction lot:

- lot 2 `securite Discord/OpenClaw`
- lot 4 `provider/cost layer`

## P1 Findings

### P1-1 - Lifecycle/outbox exists in schema but is not proven by live runtime

Classification: `partial`

Local evidence:

- `src/project_os_core/database.py:568-601` creates `api_run_lifecycle_events` and `api_run_operator_deliveries`
- `src/project_os_core/api_runs/service.py:3492-3544` persists those records
- runtime counts on 2026-03-14:
  - `api_run_lifecycle_events = 0`
  - `api_run_operator_deliveries = 0`

Impact:

- the code path exists, but the live system has not yet produced evidence that the lifecycle/outbox loop is working on this machine
- this matters directly for the OpenClaw/Discord bug triage that will come next

Recommended correction lot:

- lot 3 `runtime truth + outbox + idempotence ingress`

### P1-2 - RuntimeStore still has scope and approval integrity gaps

Classification: `partial with correctness debt`

Local evidence:

- `src/project_os_core/runtime/store.py:119-136` implements `latest_runtime_state()` as a global latest record, not session-scoped
- `src/project_os_core/runtime/store.py:189-221` lists pending approvals without filtering expired records
- `src/project_os_core/runtime/store.py:224-246` resolves approvals by overwriting `payload_json` with the new metadata payload

Impact:

- session truth can drift in multi-session or replay scenarios
- expired approvals remain visible as pending
- approval metadata can lose previously recorded context

Recommended correction lot:

- lot 3 `runtime truth + outbox + idempotence ingress`

### P1-3 - Rehydration and compaction recovery are only partial

Classification: `partial`

Why this matters:

- brick `E` proposes a deliberate recovery pack and exact resume path
- the current system has bootstrap persistence and session snapshot schema, but not a complete operator-facing rehydration workflow

Local evidence:

- `src/project_os_core/database.py:238-245` creates `bootstrap_states`
- `src/project_os_core/database.py:312-320` creates `session_snapshots`
- runtime counts on 2026-03-14:
  - `bootstrap_states = 1`
  - `session_snapshots = 0`
- `src/project_os_core/api_runs/service.py:3711-3712` reads the latest bootstrap state
- no `WORKING_STATE.json` / `BOOTSTRAP_PACK.md` style recovery pack exists in the current runtime contract

Impact:

- crash recovery is better than a prototype, but not yet at the "resume exactly where it stopped" level described in the PDF

Recommended correction lot:

- lot 3 `runtime truth + outbox + idempotence ingress`
- later follow-up after the Discord/OpenClaw path is stabilized

### P1-4 - Missing provider/cost/idempotence building blocks are confirmed, not hypothetical

Classification: `missing real pieces`

Runtime/schema evidence:

- `idempotency_keys`: absent
- `cost_ledger`: absent
- `delivery_attempts`: absent
- `capability_leases`: absent
- `prompt_cache`: absent

Code evidence:

- no `LLMProvider` abstraction found in `src/project_os_core`
- no `ModelRouter` class found in `src/project_os_core`

Interpretation:

- Claude's suggested missing pieces are materially correct on these points
- the only correction is that aggregate operator delivery tracking already exists via `api_run_operator_deliveries`; what is missing is per-attempt history

Recommended correction lot:

- lot 3 `runtime truth + outbox + idempotence ingress`
- lot 4 `provider/cost layer`

## P2 Findings

### P2-1 - Test and CI signals are false-red and under-scoped

Classification: `tooling debt`

Local evidence:

- `pyproject.toml` has no pytest scoping config
- the repo root has no top-level `pytest.ini`
- only vendored `pytest.ini` files were found under `third_party/letta`
- `.github/workflows/` currently contains only `issue-resolution-guard.yml`
- no test, lint, or type-check workflow is present

Impact:

- local `pytest -q` looks broken even when core tests pass
- CI does not currently prove core quality gates for the actual product code

Recommended correction lot:

- lot 5 `observabilite et outils externes a valeur reelle`

### P2-2 - Documentation and runbooks are fragmented and partially stale

Classification: `docs debt`

Symptoms:

- root docs, ADRs, prompts, workflow docs, and code constraints do not tell one coherent story
- the same topic appears across `README`, `AGENTS`, ADRs, prompts, roadmaps, and integration docs with drifting assumptions

Impact:

- operator behavior, model roles, and correction priorities are harder to trust than they should be

Recommended correction lot:

- lot 1 `identite produit + conventions + suppression Codex`
- lot 5 `observabilite et outils externes a valeur reelle`

### P2-3 - A LangGraph-style orchestration rewrite is not justified yet

Classification: `defer`

Why:

- the current system already has a non-trivial local-first core, journal, router, runtime store, memory tiers, and targeted tests
- the main pain points are control-plane truth, security, idempotence, and provider/cost instrumentation
- a framework migration now would likely hide the real issues instead of solving them

Recommended correction lot:

- none now
- revisit only after lots 1 to 4 are complete and the same orchestration pains remain

## Integration Of The Claude Audit

### Confirmed as real missing pieces

- ingress idempotency for Discord/OpenClaw events
- cost ledger per LLM call
- `LLMProvider` / `ModelRouter` abstraction
- capability leases for risky actions
- delivery attempt history

### Reframed

- `prompt cache SQLite` should not be the first optimization lever
- first move:
  - make prompt prefixes stable enough to exploit native prompt caching from OpenAI and Anthropic
  - record prompt usage, cached tokens, and real cost
  - only then decide whether an application-level cache still has ROI

### Corrected

- `api_run_operator_deliveries` already exists and already tracks aggregate delivery status, attempts, and backoff
- the missing piece is per-attempt detail, not delivery tracking from zero
- loop and budget concepts already exist, but their source of truth is not strong enough yet

## Bricks A-K Matrix

| Brick | Current project status | Decision | Audit note |
| --- | --- | --- | --- |
| A - Persistence & Runtime Truth | Largely present | `keep` | SQLite WAL, journal, runtime DB, channel events, and run tables are real. The missing part is stricter truth at the control-plane edges. |
| B - Multi-layer memory | Largely present | `keep` | Memory tiers, vectors, learning/noise signals, and promotion logic exist already. |
| C - Interchangeable models/backends | Mostly missing | `adapt` | Provider calls are still hardwired. A real abstraction layer is worth implementing later. |
| D - Optimization | Partial | `adapt` | Budget and loop concepts exist; prompt usage, cost ledger, and cache strategy do not. |
| E - Rehydration & recovery | Partial | `adapt` | Bootstrap state exists, but exact resume packs and working-state recovery are not complete. |
| F - Idempotence & capability leases | Mostly missing | `keep` | This is one of the most useful missing bricks for Discord/OpenClaw reliability and future autonomy safety. |
| G - Workers & execution | Mostly aspirational | `defer` | The project has worker ideas and contracts, but not a mature multi-worker system that justifies a large build-out now. |
| H - Observability & alerts | Partial | `adapt` | Local logs and doctor exist. Full metrics, spans, and alerting are still limited. |
| I - Security & permissions | Urgent and incomplete | `keep` | This brick is directly relevant to the current OpenClaw/Discord state. |
| J - Documentation & runbooks | Partial and fragmented | `adapt` | Useful, but should follow product identity cleanup and security/runtime truth fixes. |
| K - Dev workflow | Mixed | `adapt` | Keep replay/CI discipline. Reject Codex-centric framing and branch naming. |

## External Tool Scan

### Evaluate seriously

| Tool or source | Decision | Why it matters for Project OS |
| --- | --- | --- |
| OpenAI prompt caching | `evaluate now` | Cheap near-term win if prompt prefixes become stable. |
| Anthropic prompt caching | `evaluate now` | Same reason for the Discord/Claude lane. |
| RouteLLM | `reference` | Strong reference for cost-quality routing logic without importing a framework wholesale. |
| PydanticAI | `reference` | Useful reference for a typed, model-agnostic provider layer. |
| Stagehand | `defer but relevant` | Strong candidate for a future web worker. |
| browser-use | `defer but relevant` | Same future worker lane, especially if browser automation becomes first-class. |
| LangGraph | `defer` | Only relevant if the current orchestration remains too bespoke after control-plane fixes. |
| Langfuse | `defer` | Valuable later, once there is enough live traffic to justify centralized tracing/evals. |
| OpenAI Agents Python | `reference` | Useful workflow ideas, but not a replacement for the local-first runtime. |
| MCP servers catalog | `reference with strict trust` | Good integration inventory, but only with an explicit trust model. |

### Reject for now

- Qdrant or LanceDB migration
- full remote observability stack
- heavy worker sandboxing before concrete worker demand exists
- framework-first adoption such as Crew/CrewAI without a specific gap to solve

### Important external security signal

Anthropic's MCP and security documentation reinforce the same direction as brick `I`: third-party servers/plugins must be explicitly trusted, and trust should not be assumed by default. That supports tightening the current OpenClaw plugin allowlist posture rather than expanding it.

## Candidate Future Tables And Interfaces

### Candidate tables

- `idempotency_keys`
- `cost_ledger`
- `delivery_attempts`
- `capability_leases`

### Candidate interfaces

- `LLMProvider`
- `ProviderRouter` or `ModelRouter`
- `PromptUsageRecorder`

### Candidate convention replacement

- branch prefix target: `project-os/*`
- remove product-role mentions of `Codex`

## Recommended Backlog

### Lot 1 - Product identity, conventions, and Codex removal

Scope:

- remove Codex as an active product lane from docs, prompts, ADR examples, and run messages
- replace `codex/*` branch enforcement with a neutral convention
- align `README`, `AGENTS`, ADRs, prompts, and runtime messages with:
  - `Claude API` for Discord discussion and translation
  - `GPT API` for code-heavy runs

### Lot 2 - OpenClaw/Discord security

Scope:

- remove plaintext Discord secrets from runtime config flow
- tighten mention and group policy
- enforce explicit trusted plugin allowlist
- make `openclaw doctor` fail or warn accurately when runtime trust is weak
- stop global secret leakage through library adapters

### Lot 3 - Runtime truth, outbox proof, and ingress idempotence

Scope:

- move approval and budget truth to persisted runtime sources
- add ingress idempotency for Discord/OpenClaw events
- prove lifecycle/outbox records in live runtime
- harden `latest_runtime_state`, approval expiry handling, and approval metadata merge behavior
- formalize recovery/rehydration artifacts once the operator loop is stable

### Lot 4 - Provider and cost layer

Scope:

- introduce `LLMProvider` abstraction
- introduce a provider/model router that can declare and execute the same truth
- add prompt usage recording and `cost_ledger`
- evaluate native prompt caching before building an app-level cache

### Lot 5 - Observability, tooling, and external tools with real leverage

Scope:

- isolate core tests from vendored `third_party` suites
- add CI that proves real project quality gates
- consolidate runbooks and operating docs after lots 1 to 4
- evaluate external tools only where they solve a concrete gap

## Final Assessment

The project has a real foundation, not a toy prototype. But the missing pieces are also real:

- identity drift
- routing truth drift
- live Discord/OpenClaw hardening gaps
- metadata-driven control-plane decisions
- absent idempotence/provider/cost primitives
- insufficient live proof for lifecycle/outbox behavior

The next step should not be a broad rewrite. It should be a focused correction sequence, starting with lots 1 to 3, then lot 4, and only then deciding how much extra framework or tooling is actually justified.
