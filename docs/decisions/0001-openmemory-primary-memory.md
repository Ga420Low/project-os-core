# ADR 0001 - OpenMemory As Primary Memory Core

## Status

Accepted

## Context

Project OS needs a local-first memory stack that stays on the founder PC, survives long missions, and does not depend on prompt stuffing or remote vendor memory.

We evaluated:

- `Letta`
- `OpenMemory`
- `Mem0`
- `Zep`

The memory layer also needs a canonical local store, a portable retrieval layer, and stable artifact pointers.

## Decision

Project OS v1 and v2 use:

- `OpenMemory` as the primary memory engine
- `SQLite` as the canonical local storage layer
- `sqlite-vec` as the embedded vector retrieval layer
- local files for evidence, screenshots, reports, and cold archives

`Letta` remains a backup and comparison path, not the center of the first implementation.

## Why

- `OpenMemory` fits the local-first requirement directly.
- It already supports standalone local SQLite usage.
- It aligns better with the Project OS split between:
  - operator shell
  - orchestration
  - memory
  - runtime truth
- `Letta` is strong, but it overlaps more with responsibilities already assigned to `OpenClaw` and `LangGraph`.

## Consequences

- The memory lot will be built around an internal adapter that wraps `OpenMemory`.
- The Project OS canonical database remains separate and authoritative for operational metadata.
- `OpenMemory` will never be imported directly from random modules. It goes through a stable Project OS adapter.
- If `OpenMemory` changes too aggressively, Project OS can swap adapters without rewriting the whole core.

