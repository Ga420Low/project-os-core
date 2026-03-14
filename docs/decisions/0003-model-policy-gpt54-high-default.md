# ADR 0003 - Model Policy For Project OS

## Status

Accepted

## Decision

Project OS uses the following model policy for the main reasoning layer:

- default model: `gpt-5.4`
- default reasoning level: `high`
- escalation level: `gpt-5.4` with `xhigh`
- exceptional tier: `gpt-5.4-pro`

`gpt-5.4-pro` is not part of the normal execution loop.

## Default Rule

The system should assume:

- `gpt-5.4`
- `reasoning.effort = high`

This is the baseline for:

- mission planning
- runtime arbitration
- tool selection
- recovery after non-trivial errors
- operator explanations

## Escalation Rule

The system may escalate to `gpt-5.4` with `xhigh` only when at least one of these is true:

- the plan spans multiple branches or workers
- the recovery path is ambiguous
- the task has a high coordination cost
- the action sequence is costly to get wrong
- the system is blocked after one failed high-effort attempt

## Pro Rule

The system may use `gpt-5.4-pro` only in rare, explicit cases:

- major architectural arbitration
- extremely difficult multi-step planning
- high-stakes corrective reasoning
- manual founder-approved deep analysis

`gpt-5.4-pro` must stay out of:

- normal routing
- repeated tool loops
- screenshot-by-screenshot control
- routine memory operations
- cheap retries

## Why

- `gpt-5.4` already supports multiple reasoning levels and is the right default intelligence/cost tradeoff for Project OS.
- `high` gives strong baseline quality without immediately pushing into the slowest and most expensive tier.
- `xhigh` is a better escalation path than jumping straight to `pro`.
- `gpt-5.4-pro` is too expensive for routine agent loops and should be treated as an exceptional tier.

## Budget Logic

Project OS is currently optimized for:

- local build work plus operator discussion, with limited API budget for runtime autonomy
- limited API budget for runtime autonomy

That means:

- maximize deterministic local execution
- call the model only for real reasoning
- keep `gpt-5.4-pro` rare
- prefer `gpt-5.4 high` over `pro`

## Operational Guidance

Reasoning policy by severity:

- normal tasks -> `gpt-5.4 high`
- hard tasks -> `gpt-5.4 xhigh`
- exceptional tasks -> `gpt-5.4-pro`

The system should never escalate to `pro` just because a task is long.
It should escalate only when the expected value of better reasoning exceeds the cost.

## Consequences

- workers remain deterministic and cheap
- orchestration stays separate from premium reasoning
- memory and runtime state do not depend on `pro`
- model usage stays compatible with the current budget cap
- future optimization can focus on routing quality, not brute-force model spend
