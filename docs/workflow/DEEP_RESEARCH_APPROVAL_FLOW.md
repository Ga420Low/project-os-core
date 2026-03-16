# Deep Research Approval Flow

## Purpose

This document defines the user-facing approval contract for deep research.

Deep research is a dedicated workflow, separate from normal Discord conversation mode.

For now, this approval flow only exists after an explicit founder trigger such as `deep research` or `recherche approfondie` written in the message.

## Required Flow

When deep research is detected:

1. prepare the dossier scaffold
2. ask for `research_profile`
3. ask for `research_intensity`
4. once both are explicit, show:
   - dossier path
   - estimated cost
   - estimated time
   - API/model
5. wait for `go` or `stop`

## Important Rules

- the bot must always ask mode before launch
- it may recommend a profile and intensity
- if one value is already explicit, ask only for the missing one
- if both values are explicit, skip directly to cost/time/API confirmation
- the run must never launch before `go`
- a normal conversation must not silently enter this flow

## Expected Discord Language

The operator reply should clearly include:

- subject
- dossier path or doc name
- recommended or confirmed profile
- recommended or confirmed intensity
- estimated cost
- estimated time
- API/model
- `go` or `stop`

## Example Sequence

### Step 1 - trigger detected

The bot asks:

- profile
- intensity

### Step 2 - user responds

Example:

- `component discovery + complexe`

### Step 3 - approval reply

The bot shows:

- confirmed profile
- confirmed intensity
- cost
- time
- API
- `go` / `stop`

### Step 4 - user approves

- `go`

Then the detached job launches.

## Completion Contract

The completion summary must include:

- final French title
- dossier path
- profile
- intensity
- bucket counts
- top actions
- runtime issues if observed
- PDF and Markdown attached
