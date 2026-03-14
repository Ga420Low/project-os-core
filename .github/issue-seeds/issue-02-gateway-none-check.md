## Description

`_communication_mode_for()` uses `if message_kind in {None, }` instead of a direct `is None` check.

## Impact

There is no current crash, but the expression is noisy and suggests a broader set-membership case that does not exist.

## Root Cause

The condition was written as a singleton set membership test instead of the simpler null guard.

## Resolution

Replace the set-membership expression with `if message_kind is None` to make the intent explicit and keep the branch easy to audit.

## Regression Coverage

Cover the null branch indirectly through existing gateway routing tests or add a focused unit test if the method starts carrying more logic.

## Durable Lesson

Use the narrowest expression that matches the intent. Small control-flow checks should read like invariants, not puzzles.

## Reusable Pattern

Prefer direct identity checks for sentinel values like `None`.

## Repeated Pattern

Low-level gateway conditionals become harder to trust when style noise accumulates in hot-path branching code.

## Eval Scenario

A gateway event without a classified message kind should still route into `discussion` mode through the explicit `is None` branch.
