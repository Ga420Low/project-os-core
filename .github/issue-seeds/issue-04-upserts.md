## Description

Canonical persistence still relies on `INSERT OR REPLACE`, which deletes and recreates rows instead of updating them in place.

## Impact

Immutable fields like `created_at` can be lost or rewritten, and partial data can be clobbered silently. That weakens auditability and schema trust.

## Root Cause

Persistence code used the shortest SQLite write pattern instead of explicit `ON CONFLICT` upserts with controlled mutable columns.

## Resolution

Introduce a canonical upsert helper in the database layer and migrate persistence writes to `INSERT ... ON CONFLICT DO UPDATE`, preserving immutable fields such as primary keys and `created_at`.

## Regression Coverage

Add tests that verify upserts stay idempotent, preserve `created_at`, and keep default scheduler rows working after the migration changes.

## Durable Lesson

Canonical stores must make update semantics explicit. Convenience write patterns are not acceptable when state traceability matters.

## Reusable Pattern

Centralize repeated SQL write semantics in one helper instead of hand-copying conflict logic across services.

## Repeated Pattern

SQLite shortcuts are attractive in early prototypes and then linger long after the system starts caring about state history.

## Eval Scenario

Persist the same logical row twice with a different mutable field and confirm that `created_at` stays stable while the mutable field updates.
