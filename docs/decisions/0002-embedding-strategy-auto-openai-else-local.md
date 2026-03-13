# ADR 0002 - Embedding Strategy

## Status

Accepted

## Decision

Project OS uses an `auto` embedding strategy:

- if `OPENAI_API_KEY` is present:
  - provider = `openai`
  - model = `text-embedding-3-small`
  - quality preset = `balanced`
- otherwise:
  - provider = `local_hash`
  - deterministic local embeddings

## Why

- `text-embedding-3-small` is the best quality/cost default for the current memory layer.
- It keeps API cost under control while remaining much stronger than local placeholder hashing.
- The local deterministic fallback keeps the system fully usable offline and before API activation.

## Overrides

Environment variables can override the default:

- `PROJECT_OS_EMBED_PROVIDER`
- `PROJECT_OS_EMBED_MODEL`
- `PROJECT_OS_EMBED_DIMENSIONS`
- `PROJECT_OS_EMBED_QUALITY`

## Notes

- `OpenMemory` is configured from the same strategy.
- The canonical local vector index is rebuilt automatically if the embedding strategy signature changes.

