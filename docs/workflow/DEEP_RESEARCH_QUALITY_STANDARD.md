# Deep Research Quality Standard

## Purpose

This document defines the trust, evidence, retention, and publication quality gates for deep research.

## Source Trust and Reputation Classes

- `trusted_primary`
- `trusted_ecosystem`
- `neutral_secondary`
- `weak_signal`
- `quarantined`

## Default Trust Heuristics

### `trusted_primary`

- official docs
- standards bodies
- official repos
- original papers
- benchmark homes

### `trusted_ecosystem`

- strong registries
- respected wrappers
- strong satellites
- serious ecosystem tooling

### `neutral_secondary`

- secondary analysis from plausible sources
- summaries that may help but do not define truth

### `weak_signal`

- small blogs
- low-maintenance mirrors
- uncertain commentary

### `quarantined`

- suspicious domains
- low-trust content
- anything that should never become decisive evidence automatically

## Safety Rules

- suspicious domains never become primary evidence automatically
- quarantined sources may be mentioned only as weak signals
- no code execution from gathered sources
- no download-and-run in v1
- no authenticated browsing during collection in v1

## Evidence Provenance

Each run should keep enough provenance to explain what was used:

- execution plan
- source trust summary
- source reputation summary
- evidence manifest
- model and tool metadata
- repo context snapshot
- response continuity summary when applicable

## Runtime Artifact Retention

The cold archive should preserve:

- `request.json`
- `repo_context.json`
- `execution_plan.json`
- `mesh_manifest.json`
- `cheap_scout_swarm.json` when the run actually used the War Room broad-discovery pass
- `prompt.md`
- `response.json`
- `result.json`
- `reader_fr.json`
- `status.json`
- `model_debug.jsonl` when phase-level debug logging is enabled
- `usage_summary.json` when a run produced model debug entries
- `manifest.json`
- final Markdown
- final PDF
- `lanes/` for `extreme` runs

## Reputation Engine

The runtime now combines:

- seed trust heuristics
- freshness
- corroboration across domains
- contradiction notes from the skeptic lane
- ecosystem hints for GitHub and package registries
- persistent local history in SQLite

Mode scaling:

- `simple`: seed trust plus freshness
- `complex`: seed trust, freshness, corroboration, contradiction notes
- `extreme`: full score with persistent local history

## Publication Gate

A run may archive artifacts without being considered fully clean or fully successful.

Current v1 runtime behavior:

- if the main synthesis path succeeds but one or more auxiliary lanes fail, the run is published with `quality_gate.status=degraded`
- if the main synthesis path fails, the run ends as `failed`
- a dedicated terminal runtime status such as `insufficient` is not yet implemented

Treat the following cases as publication-quality failures even if artifacts are archived:

- the evidence quality is too weak
- the report violates its profile contract
- the trust gate is missing where required
- the final synthesis overstates weak signals

In those cases, the dossier should either:

- publish as `degraded` with explicit notes and partial-proof framing, or
- fail hard if no trustworthy synthesis can be produced

## Output Quality Gates

### Markdown

- English
- machine-clean
- stable section order
- explicit data fields for structured reuse

### PDF

- French
- easy to skim on mobile
- compact tables where useful
- no dependence on Markdown readability
