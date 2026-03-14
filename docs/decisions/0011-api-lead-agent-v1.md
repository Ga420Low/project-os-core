# ADR 0011 - API Lead Agent v1

## Status

Accepted — operating model updated by ADR 0013

Note: the former manual inspection role is now handled by Claude API (cross-model auditor + translator).
See `docs/decisions/0013-dual-model-operating-model.md` for the current operating model.

## Decision

Project OS adopts an `API Lead Agent v1` layer built around `gpt-5.4` and the `Responses API`.

The current operating model is (ADR 0013):

- `GPT API` (gpt-5.4, 1M context) = large-context lead agent for `audit`, `design`, `patch_plan`, and `generate_patch`
- `Claude API` (opus/sonnet, 1M context) = cross-model auditor and human translator
- `Project OS runtime` = canonical truth for memory, evidence, routing, budgets, approvals, and artifacts

The coding lane remains `repo_cli`.
The desktop lane remains `future_computer_use`.

## Why

This gives Project OS a high-capacity planning and coding force without giving up local truth, testability, or review discipline.

It also lets the product build itself progressively:

- large-context reasoning happens through repeatable API runs
- validated outputs are reviewed and integrated locally
- rejected or changed outputs feed the learning layer

## Consequences

### Accepted

- `api_runs` is now a first-class subsystem in the core
- large runs must target `project-os/*` branches
- outputs are structured and schema-bound
- raw prompts/results live in runtime storage, not in the repo
- validated decisions and review outcomes feed the learning layer
- a local text monitor exists for human visibility
- a local web dashboard exists for visual supervision while the API works

### Rejected

- no direct push to `main` from API runs
- no code-writing v1 via Windows computer use
- no second memory truth outside canonical runtime storage
- no fine-tuning dependency in v1

## Follow-up

- connect `OpenClaw` live on top of the existing gateway adapter
- connect `LangGraph` live on top of the canonical six-role graph
- later add the desktop/computer-use lane as a separate capability
