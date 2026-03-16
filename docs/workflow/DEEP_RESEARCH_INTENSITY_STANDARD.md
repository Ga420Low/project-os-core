# Deep Research Intensity Standard

## Purpose

`research_intensity` decides how much orchestration, evidence gathering, and adversarial checking the run should perform.

User-facing labels:

- `Simple`
- `Complexe`
- `Extreme`

Internal values:

- `simple`
- `complex`
- `extreme`

## Shared Invariants

All intensities must:

- preserve the same approval flow
- preserve the same detached-job model
- preserve the same output contract
- stay inside the current provider/cost architecture in v1

## `simple`

### Shape

- one strong research worker
- repo context
- one main research pass
- one lightweight source-scoring post-pass
- one French reader translation pass
- rendering and archive

### Best for

- normal audits
- many domain audits
- light subsystem work

### Expectations

- still repo-first
- still source-backed
- no committee
- light source reputation only: seed trust plus freshness

## `complex`

### Shape

- parent planner
- repo scout
- official-doc scout
- GitHub scout
- optional papers scout when the planner explicitly asks for it
- optional skeptic
- parent synthesizer
- publisher

### Best for

- serious subsystem audits
- stack comparisons
- medium-depth project work

### Expectations

- committee-light behavior
- explicit scout lanes
- in-process parallel scouts with a bounded worker pool
- source safety gate enabled
- medium source reputation: seed trust, freshness, corroboration, contradiction notes
- Responses continuity from planner through final synthesis
- more than one evidence lane

## `extreme`

### Shape

- parent planner
- cheap scout swarm
- source safety gate
- repo scout
- official-doc scout
- GitHub/forks/satellites scout
- papers/benchmarks scout
- skeptic / contradiction pass
- expert synthesizer
- publisher
- lane workers write their own request, status, result, and response artifacts under `lanes/`

### Best for

- high-value project audits
- very strategic subsystem discovery
- cases where blind spots matter more than speed

### Expectations

- multi-lane evidence
- mandatory source safety gate
- cheap scouts gather and rank
- expert studies curated evidence, not raw noise
- suspicious sources can be mentioned only as weak signals
- cheap scout output must seed the specialist lanes before the expert synthesis
- partial scout-lane failures should degrade the quality gate, not immediately collapse the whole run to a fake full-success state
- child-worker mesh, not only scoped serial passes
- full source reputation: seed trust, freshness, corroboration, ecosystem hints, and persistent local history
- state continuity must survive planner, lanes, skeptic, and final synthesis
- the current debug route may use `Anthropic Sonnet` for extreme research passes and keep `OpenAI` only for the reader PDF translation
- every extreme run should emit phase-level debug logs with counted tokens, actual usage, and per-phase estimated cost

### Current v2 implementation note

- `simple` stays single-worker and cheap
- `complex` runs lane scouts in parallel inside the detached parent job
- `extreme` keeps one detached parent job but launches real child lane workers locally
- `cheap scout swarm` seeds specialist lanes with briefs and candidate sources
- `complex` reuses OpenAI Responses state through final synthesis
- `extreme` currently supports a temporary `Anthropic Sonnet debug` route for research phases, with manual prompt-chain continuity plus counted-token debug logs
- translation remains stateless by design

### Explicit v2 constraints

- no separate crawler platform
- no arbitrary browser automation against unknown sites
- no download-and-run behavior
- no authenticated browsing during source collection
