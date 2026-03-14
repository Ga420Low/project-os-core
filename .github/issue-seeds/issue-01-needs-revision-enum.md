## Description

`ApiRunReviewVerdict.NEEDS_REVISION` collides with `accepted_with_reserves`, so Python treats it as an enum alias instead of a distinct verdict.

## Impact

The reviewer cannot explicitly request revision work before integration. Downstream reporting and dashboards collapse two different review states into one.

## Root Cause

The enum value was copied from `accepted_with_reserves` instead of using a dedicated wire value.

## Resolution

Change the enum wire value to `needs_revision` and update every reviewer prompt, parser, dashboard badge, and completion summary that branches on review verdicts.

## Regression Coverage

Add unit tests for enum uniqueness, reviewer parsing, and a completion report path that exercises `needs_revision`.

## Durable Lesson

Never treat enum wire values as copy-paste text. Distinct workflow states must always have distinct serialized values and explicit downstream handling.

## Reusable Pattern

When a verdict or status is added, update prompt contracts, parsers, dashboards, translations, and tests in the same lot.

## Repeated Pattern

Workflow-state additions often fail because only the enum is changed while the prompt/parser/reporting layers are left stale.

## Eval Scenario

Reviewer returns `{ "verdict": "needs_revision" }` and the runtime must persist a distinct review, render a distinct badge, and produce a revision-focused completion report.
