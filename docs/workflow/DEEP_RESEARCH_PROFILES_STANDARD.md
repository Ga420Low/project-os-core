# Deep Research Profiles Standard

## Purpose

This document defines the reasoning contract for each `research_profile`.

The profile decides what the engine is trying to learn and how the final report should be shaped.

## Shared Invariants

All profiles must:

- be repo-first when the topic touches Project OS
- cite source-backed findings
- finish with explicit decisions
- emit canonical Markdown in English
- emit reader PDF in French

## `project_audit`

### What it is for

Use `project_audit` when the request targets the whole Project OS trajectory.

Examples:

- `audit de mon projet`
- `what should Project OS improve overall`
- `how do we reach the final system`

### Core question

`What most improves the odds that Project OS becomes the ambitious system it is trying to become?`

### Required shape

The report must include:

- `Executive Summary`
- `North Star`
- `System Thesis`
- `Platform Layers`
- `Capability Gaps`
- `Priority Ladder`
- `Observed Runtime Issues`
- `Recommendations`
- `Success Metrics`
- `Risks`
- `Open Questions`
- `Sources`

### Required strategic framing

The audit must connect recommendations to the larger system, including as relevant:

- master agent
- manager agents
- execution surfaces
- verification
- memory
- evals
- operator control

### Validation intent

Fail the report if:

- it collapses into local hardening only
- it never states the grand-system direction
- the recommendations do not connect to larger Project OS architecture

## `component_discovery`

### What it is for

Use `component_discovery` when the request targets a subsystem, stack, feature, piece, or improvement area.

Examples:

- memory systems
- routing stack
- verification systems
- Discord/gateway improvements
- eval stack
- desktop stack

### Core question

`What are we underthinking in this subsystem, and what outside systems or forks materially improve it?`

### Required shape

The report must include:

- `Executive Summary`
- `Blind Spots`
- `External Leverage`
- `Underbuilt Layers`
- `Priority Ladder`
- `Observed Runtime Issues`
- `Recommendations`
- `Stop Doing or Deprioritize`
- `Success Metrics`
- `Risks`
- `Open Questions`
- `Sources`

### Required discovery behavior

The audit must aggressively look for:

- upstream repos
- strong forks
- satellites
- wrappers
- recent releases
- smaller but sharper repos

### Validation intent

Fail the report if:

- there is no real external leverage
- no GitHub or fork or satellite insight appears
- all `A faire` items are just local cleanup

## `domain_audit`

### What it is for

Use `domain_audit` for topics outside the product core.

Examples:

- tomatoes
- travel
- product comparison unrelated to the current repo

### Core question

`What is the best factual synthesis for the topic, and what is the correct level of Project OS fit?`

### Required shape

Keep the lighter generic structure:

- summary
- why now
- repo fit
- recommendations
- risks
- open questions
- sources

### Validation intent

Fail the report if:

- it becomes mostly meta-commentary about Project OS
- it over-engineers a simple outside topic into a pseudo system strategy memo
