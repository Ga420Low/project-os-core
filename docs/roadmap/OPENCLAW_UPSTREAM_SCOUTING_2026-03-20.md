# OpenClaw Upstream Scouting 2026-03-20

## Objet

Verifier:

1. quel repo doit servir de fondation runtime V1
2. s'il existe un fork objectivement plus avance et mieux aligne avec `Project OS`
3. quels satellites valent la peine d'etre gardes comme references

## Verdict net

Base runtime retenue:

- `openclaw/openclaw`
- clone upstream direct
- version pinnee sur OVH: `v2026.3.13-1`
- commit: `61d171ab0b2fe4abc9afe89c518586274b4b76c2`

Conclusion:

- aucune "pepite fork" n'a justifie de remplacer l'upstream officiel comme base
- plusieurs repos sont utiles comme references ou accelerateurs ponctuels
- ils ne doivent pas remplacer le substrate officiel

## Upstream officiel

- repo: `openclaw/openclaw`
- URL: `https://github.com/openclaw/openclaw`
- branche par defaut: `main`
- releases recentes observees:
  - `v2026.3.13-1`
  - `v2026.3.12`
  - `v2026.3.11`

Raisons de retention:

- cadence de maintenance forte
- ecosysteme docs officiel vivant
- onboarding et Docker documentes
- plus grande compatibilite future avec guides et communaute

## Candidats evalues

### `remoteclaw/remoteclaw`

URL:

- `https://github.com/remoteclaw/remoteclaw`

Lecture:

- fork tres interessant conceptuellement
- oriente middleware pour agents CLI (`Claude Code`, `Gemini CLI`, `Codex`, `OpenCode`)
- apporte canaux, sessions persistantes, cron, MCP tools
- remplace une partie de la couche plateforme par `AgentRuntime`

Decision:

- `REFERENCE ONLY`

Pourquoi:

- tres pertinent comme source d'idees pour le futur bridge `OpenClaw -> Codex CLI`
- mais trop opinionated pour devenir notre fondation runtime sans reouvrir tout le cadrage
- licence `AGPL-3.0-only`, a prendre au serieux avant toute assimilation profonde

### `digitalknk/openclaw-runbook`

URL:

- `https://github.com/digitalknk/openclaw-runbook`

Lecture:

- runbook non officiel mais mature
- bon materiau sur couts, guardrails, memory boundaries, patterns de run
- contient `guide.md`, exemples, hardening, VPS setup

Decision:

- `KEEP AS OPS REFERENCE`

Pourquoi:

- utile pour accelerer les playbooks d'exploitation
- pas une base runtime

### `essamamdani/openclaw-coolify`

URL:

- `https://github.com/essamamdani/openclaw-coolify`

Lecture:

- repo de deploiement simplifie pour Coolify
- bon pour comprendre un chemin de bootstrap "dashboard + tunnel"

Decision:

- `KEEP AS DEPLOYMENT REFERENCE`

Pourquoi:

- utile pour regarder l'emballage ops
- pas pertinent comme fondation sur notre VPS Docker actuel

### `sunkencity999/localclaw`

URL:

- `https://github.com/sunkencity999/localclaw`

Lecture:

- fork interessant oriente `local-first`
- installe separee
- etat separe
- profils/config separes
- optimisation pour modeles locaux

Decision:

- `MINE FOR FOUNDATION IDEAS`

Pourquoi:

- tres bon materiau pour l'isolation d'etat, de profils et de ports
- utile pour penser des lanes ou profils techniques separes plus tard
- ne doit pas remplacer l'upstream officiel comme base runtime

### `jomafilms/openclaw-multitenant`

URL:

- `https://github.com/jomafilms/openclaw-multitenant`

Lecture:

- multi-tenant
- isolation par conteneurs
- vaults chiffres
- partage equipe

Decision:

- `OUT OF SCOPE FOR V1`

Pourquoi:

- tres loin de notre cible perso / operateur V1
- ajoute une complexite structurelle inutile maintenant
- risque de deformer la fondation en la pensant trop tot comme plateforme multi-tenant

### `supermemory` satellites

Observation:

- quelques repos autour de `supermemory` existent pour OpenClaw-like memory
- interesse uniquement comme experience future de retrieval ou compaction

Decision:

- `DEFER`

Pourquoi:

- la memoire canonique d'entreprise doit rester `Project OS`
- aucun add-on memoire externe ne doit devenir la verite produit

## Regle d'usage

Pour `Sprint 1`:

- `openclaw/openclaw` = base
- forks/satellites = references seulement

Pour `Sprint 2+`:

- on peut reprendre des idees
- on peut reprendre des patterns
- on ne remplace pas la base upstream sans ADR explicite

## Sources

- `https://github.com/openclaw/openclaw`
- `https://github.com/openclaw/openclaw/releases`
- `https://github.com/remoteclaw/remoteclaw`
- `https://github.com/digitalknk/openclaw-runbook`
- `https://github.com/essamamdani/openclaw-coolify`
- `https://github.com/sunkencity999/localclaw`
- `https://github.com/jomafilms/openclaw-multitenant`
