## Description

Mission chaining auto-approves a generated run contract before checking whether the Guardian would block the run for budget or loop reasons.

## Impact

The chain can mark a step as approved even when the Guardian should have stopped it. That weakens the budget-control and loop-protection contract.

## Root Cause

The chain reuses the normal contract flow but runs `approve_run_contract()` before performing a pre-spend guard check.

## Resolution

Build the step context and prompt, run the Guardian pre-spend check first, and only approve the contract when the Guardian allows the step. If the Guardian blocks, pause the chain and return a `guardian_blocked` outcome without approving the contract.

## Regression Coverage

Add a mission-chain test that asserts the chain pauses before approval and that the blocked contract remains in `prepared` state.

## Durable Lesson

Any automation wrapper around a normal run flow must preserve the same guards and approval ordering as the base path.

## Reusable Pattern

When composing orchestration layers, run budget and safety gates before any state transition that implies commitment.

## Repeated Pattern

Wrapper workflows often drift from the canonical execution path and silently bypass safety gates.

## Eval Scenario

Launch a chain step whose estimated cost breaches the Guardian limit. The chain must pause and leave the contract unapproved.
