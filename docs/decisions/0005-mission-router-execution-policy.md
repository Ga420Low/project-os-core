# 0005 - Mission Router Execution Policy

## Status
Accepted

## Context

The system needs a policy-aware execution layer before `OpenClaw` and `LangGraph` are attached.
`Mission Router` is the decision layer between operator intent and worker execution.

It must enforce:

- model policy
- approvals
- budget limits
- forbidden zones
- runtime health
- worker/profile compatibility

## Decision

- `Mission Router` is implemented before external gateway/orchestration integration.
- It converts operator intent into a routing decision traceable in SQLite.
- Default reasoning route is `gpt-5.4` with `high`.
- Escalation route is `gpt-5.4` with `xhigh`.
- `gpt-5.4-pro` is exceptional only and requires founder approval.
- Deterministic work should avoid model calls whenever possible.
- Any mission targeting forbidden paths, missing required secrets, or a non-ready runtime is blocked.
- Destructive and exceptional missions require explicit approval.

## Consequences

- Gateway adapters will not make execution decisions on their own.
- Workers will execute only policy-approved requests.
- Cost, approvals, and route choice become inspectable evidence instead of implicit behavior.
