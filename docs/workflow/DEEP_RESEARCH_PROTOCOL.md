# Deep Research Protocol

## Purpose

`Deep research` is the canonical workflow when `Project OS` must produce a durable research artifact instead of a short conversational answer.

It is designed to:

- start from the real repo, not from generic public advice
- search external sources with a higher proof bar
- translate findings into concrete `Project OS` decisions
- persist results as machine-readable `Markdown` plus reader-friendly `PDF`

Deep research is a separate system from normal conversation mode.

For now, it must only activate when the founder explicitly writes a trigger such as `deep research` or `recherche approfondie` in the message.

Normal conversation, even if serious, long, or expensive, must not silently switch into deep research.

This document is the umbrella entry point. It defines the common contract and points to the more specific standards.

## Core Concepts

Deep research now has two independent axes:

- `kind`
  - storage axis only
  - `audit` -> `docs/audits/`
  - `system` -> `docs/systems/`
- `research_profile`
  - reasoning axis
  - `project_audit`
  - `component_discovery`
  - `domain_audit`
- `research_intensity`
  - execution depth axis
  - `simple`
  - `complex`
  - `extreme`

In short:

- `kind` decides where the artifact lives
- `research_profile` decides what questions the engine must answer
- `research_intensity` decides how hard the engine goes

## Trigger Phrases

The following phrases must activate deep research handling:

- `deep research`
- `recherche approfondie`
- `audit profond`
- `fouille github`
- `cherche les pepites`
- `regarde les forks`
- `va chercher plus loin`

The trigger also applies when the wording is clearly equivalent, even with typos.

Hard boundary:

- deep research is not a generic escalation of a conversation
- it is a dedicated workflow with its own dossier, approval flow, and detached execution
- it only starts from an explicit founder trigger in the message itself

## Mandatory Operator Flow

When deep research is detected, the operator flow is:

1. detect the request
2. scaffold the dossier path
3. ask for `research_profile`
4. ask for `research_intensity`
5. once both are explicit, show:
   - dossier path
   - estimated cost
   - estimated time
   - API/model
6. wait for `go` or `stop`
7. launch the detached job only after approval

Important rule:

- the bot must always ask for mode before launch
- it may recommend a profile and intensity
- it must not silently launch based only on inferred defaults

The detailed operator UX is defined in:

- [DEEP_RESEARCH_APPROVAL_FLOW.md](./DEEP_RESEARCH_APPROVAL_FLOW.md)

## Common Execution Contract

Every deep research run must follow these common rules:

### 1. Repo-first

Before the serious web pass:

- inspect the repo snapshot
- inspect relevant local docs
- inspect active packages and touched areas
- identify existing constraints and local truth

### 2. Source discipline

Prefer, in order:

- official docs and standards bodies
- official product pages and changelogs
- official repositories
- benchmark homes and original papers
- strong ecosystem repos and registries

Do not let weak signals dominate the final thesis.

### 3. GitHub lane when relevant

When repos matter, inspect:

- README
- license
- recent activity
- releases
- install surface
- visible limitations
- forks and satellites when relevant

### 4. Project OS translation

The research is not done until it becomes a Project OS decision:

- `KEEP`
- `ADAPT`
- `DEFER`
- `REJECT`

For every actionable item, say:

- what to take
- what not to import
- where it lands in Project OS
- what proof is required

## Canonical Output Contract

Deep research produces two artifacts:

- canonical `Markdown` in English for machines
- reader `PDF` in French for humans

The canonical repo artifact lives under:

- `docs/audits/` for audits
- `docs/systems/` for system dossiers

The cold archive keeps:

- `Markdown`
- `PDF`
- `manifest.json`
- runtime artifacts

Filename and archive slug must derive from the English SEO title.

## Profile Standards

Profiles are defined in:

- [DEEP_RESEARCH_PROFILES_STANDARD.md](./DEEP_RESEARCH_PROFILES_STANDARD.md)

Summary:

- `project_audit` = whole Project OS ambition
- `component_discovery` = a system, stack, feature, subsystem, or improvement area
- `domain_audit` = an outside topic where Project OS fit is secondary

## Intensity Standards

Intensity is defined in:

- [DEEP_RESEARCH_INTENSITY_STANDARD.md](./DEEP_RESEARCH_INTENSITY_STANDARD.md)

Summary:

- `simple` = one strong worker
- `complex` = light committee with in-process parallel scouts, source reputation, and stateful synthesis
- `extreme` = War Room with child-worker mesh, source safety gate, persistent reputation, and stateful synthesis
- current route note: `extreme` uses the canonical `OpenAI` research path by default, and any `Anthropic Sonnet` debug route must be explicitly re-enabled in config for temporary diagnostics only
- default deep-research model split: `gpt-5` for planner, expert lanes, and final synthesis; `gpt-5-mini` for the cheap scout swarm; `gpt-5` for the reader translation fallback chain

## Quality and Safety

Quality, trust, and publication rules are defined in:

- [DEEP_RESEARCH_QUALITY_STANDARD.md](./DEEP_RESEARCH_QUALITY_STANDARD.md)

At minimum:

- suspicious domains are downgraded or quarantined
- `Markdown` must stay machine-clean
- `PDF` must stay readable on mobile
- a weak run may archive artifacts but must not pretend to be canonical success

## Canonical Dossiers

Execution mode dossiers live in:

- [DEEP_RESEARCH_SIMPLE_MODE_DOSSIER.md](../systems/DEEP_RESEARCH_SIMPLE_MODE_DOSSIER.md)
- [DEEP_RESEARCH_COMPLEX_MODE_DOSSIER.md](../systems/DEEP_RESEARCH_COMPLEX_MODE_DOSSIER.md)
- [DEEP_RESEARCH_WAR_ROOM_DOSSIER.md](../systems/DEEP_RESEARCH_WAR_ROOM_DOSSIER.md)

## Runtime Integration

The Discord/OpenClaw runtime must:

- prepare the dossier scaffold
- require explicit profile + intensity
- require `go` before launch
- run the detached deep research job
- write the final repo dossier
- send the PDF and Markdown back to Discord
- archive the cold bundle

## Sources

- [OpenAI - Introducing deep research](https://openai.com/index/introducing-deep-research/)
- [OpenAI - Deep research FAQ](https://help.openai.com/en/articles/10500283-deep-research)
- [OpenAI - Graders guide](https://platform.openai.com/docs/guides/graders)
- [Anthropic - Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)
- [GitHub Docs - About repository graphs](https://docs.github.com/en/repositories/viewing-activity-and-data-for-your-repository/about-repository-graphs)
- [GitHub Docs - About forks](https://docs.github.com/pull-requests/collaborating-with-pull-requests/working-with-forks/about-forks)
