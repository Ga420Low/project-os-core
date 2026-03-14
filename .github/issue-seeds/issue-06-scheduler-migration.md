## Description

The `scheduled_tasks` table is still created inside the scheduler service instead of the canonical database migration pipeline.

## Impact

Schema versioning is incomplete and different instances can drift depending on which services booted first.

## Root Cause

The scheduler was introduced with local table bootstrap logic instead of being folded into `CanonicalDatabase._migrate`.

## Resolution

Move `scheduled_tasks` creation and indexes into the canonical migration layer, bump the schema version, and remove scheduler-local table creation.

## Regression Coverage

Update scheduler tests to verify default tasks still appear after booting against a fresh database created only through the canonical migration path.

## Durable Lesson

Every persistent table belongs to the canonical migration story from day one. Service-local schema creation is drift waiting to happen.

## Reusable Pattern

Put schema DDL in one place and keep runtime services focused on behavior, not ad-hoc schema repair.

## Repeated Pattern

New subsystems often bootstrap their own tables locally and only later reveal migration drift across environments.

## Eval Scenario

Create a fresh runtime, boot the scheduler, and confirm that `scheduled_tasks` already exists before the scheduler inserts defaults.
