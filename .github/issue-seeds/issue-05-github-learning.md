## Description

Project OS lacks a durable GitHub issue workflow for capturing audit findings, validating issue closure quality, and promoting resolved issues into local learning memory.

## Impact

Important engineering lessons remain trapped in issue text, and repeated failures keep returning because there is no structured bridge from GitHub resolution back into the local learning system.

## Root Cause

GitHub has not yet been treated as a first-class workflow surface with standardized templates, closure validation, and local ingestion into Project OS learning.

## Resolution

Add issue forms with reserved headings, a closure guard workflow, a reproducible bootstrap script for labels and seed issues, and a local `project-os github sync-learning` path that ingests closed issues into the canonical learning service.

## Regression Coverage

Add unit tests for issue-body parsing, validation, label-to-severity mapping, deduplicated sync, learning promotion, and the scheduler path when `gh` is missing.

## Durable Lesson

External workflow tools can structure knowledge, but the local runtime must remain the only writer of canonical learning state.

## Reusable Pattern

Treat issue trackers as structured evidence sources, then sync them locally through idempotent ingestion with explicit validation.

## Repeated Pattern

Teams often document the fix in GitHub but never convert the lesson into reusable runtime memory or evaluation scenarios.

## Eval Scenario

Close a GitHub issue with all reserved sections filled, run `project-os github sync-learning`, and confirm that decisions, signals, eval candidates, and dataset candidates are created exactly once.
