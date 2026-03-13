# Project OS Build Status Checklist

Cette checklist sert de verite simple sur l'etat reel du build.
On coche uniquement ce qui est effectivement fini dans le repo ou valide sur la machine.

## Foundation

- [x] Repo `project-os-core` separe du projet UEFN
- [x] Structure coeur posee (`runtime`, `memory`, `router`, `workers`, `gateway`, `orchestration`, `profiles`, `integrations`)
- [x] Stockage `D:` / `E:` documente et branche
- [x] Zone interdite `E:\\DO_NOT_TOUCH` prise en compte dans la policy

## Lot 1 - Bootstrap du coeur

- [x] Chargeur de config canonique
- [x] Types canoniques principaux poses
- [x] Racines runtime/memory/session/index creees
- [x] `bootstrap` idempotent
- [x] `doctor --strict` disponible
- [x] `health snapshot` disponible

## Lot 2 - Memory OS

- [x] `OpenMemory` retenu comme memoire primaire
- [x] `SQLite` branche comme verite canonique
- [x] `sqlite-vec` branche pour le retrieval local
- [x] Tiers `hot / warm / cold` poses
- [x] Pointeurs d'artefacts et archivage poses
- [x] Strategie embeddings OpenAI/fallback locale posee
- [x] Reindexation canonique posee

## Lot 3 - Runtime State + Evidence

- [x] `RuntimeState` canonique
- [x] `SessionState` canonique
- [x] `ApprovalRecord` canonique
- [x] `ActionEvidence` canonique
- [x] Journal append-only local
- [x] Evidence avec checksum/taille/chemin verifie

## Hardening Pass 1

- [x] DB canonique versionnee
- [x] Observabilite locale minimale posee
- [x] Secrets hors repo
- [x] `Infisical` source primaire active pour `OPENAI_API_KEY`
- [x] Policy modele `gpt-5.4 high -> xhigh -> pro exceptionnel` figee
- [x] Mission Router policy-aware implante

## Mission Router

- [x] `OperatorEnvelope -> MissionIntent`
- [x] `MissionIntent -> RoutingDecision`
- [x] Budget soft journalier/mensuel pris en compte
- [x] Blocage des chemins interdits
- [x] Blocage si runtime malsain
- [x] Blocage/approval pour l'exceptionnel
- [x] Route `cheap`
- [x] Route `standard`
- [x] Route `hard`
- [x] Route `exceptional`

## Infisical professionnalisation

- [x] Projet dedie `Project OS Core`
- [x] Repo lie via `.infisical.json`
- [x] `OPENAI_API_KEY` migre dans `Infisical`
- [x] Mode local passe en `infisical_required`
- [x] Support `Universal Auth` code-first dans le resolver
- [x] `Client ID` et `Client Secret` ranges sur la machine hors repo
- [x] Validation finale sans dependance a la session utilisateur CLI

## Roadmap freeze avant lot 4

- [x] Frontiere `OpenClaw` vs `Project OS` figee
- [x] Policy `Discord selective sync` posee
- [x] Graphe mission canonique a 6 roles pose
- [x] Types gateway/orchestration/promotions poses
- [x] Adaptateur gateway interne `ChannelEvent -> Mission Router` implemente
- [x] `ExecutionTicket` emis seulement par le graphe canonique
- [x] Workflow hybride `Codex + API 1M + runtime local` documente
- [x] Discipline `DECISION CONFIRMED / DECISION CHANGED` documentee
- [x] Skills de mega prompt documentes

## Lots suivants

- [x] API Lead Agent v1
  - [x] `api_runs` subsystem pose
  - [x] Modes `audit / design / patch_plan / generate_patch` poses
  - [x] `ContextPack` canonique pose
  - [x] `MegaPrompt` canonique pose
  - [x] `ApiRunResult` canonique pose
  - [x] `ApiRunReview` canonique pose
  - [x] Stockage repo/runtime separe pour les gros runs
  - [x] `learning` layer posee
  - [x] Promotion `DECISION CONFIRMED / CHANGED` posee
  - [x] Signaux `loop / refresh / dataset` poses
  - [x] Monitor texte local des runs pose
  - [x] Dashboard web local des runs pose
  - [x] Dashboard compact en francais avec terminal integre
  - [x] Run API reel `gpt-5.4` valide sur le poste
- [ ] Lot 4 - Gateway + Mission Router adapter `OpenClaw` live
  - [x] Entree Python generique `gateway ingest-openclaw-event`
  - [x] Adaptateur package `OpenClaw` local cree
  - [x] Politique `OpenClaw facade / Project OS verite` respectee dans le code
  - [x] Ingress `message_received -> ChannelEvent -> Mission Router` branche
  - [ ] Runtime `OpenClaw` reel connecte sur Discord/WebChat du poste
- [ ] Lot 5 - Orchestration durable `LangGraph` live
- [ ] Lot 6 - Windows worker + perception
- [ ] Lot 7 - Browser worker `Stagehand`
- [ ] Lot 8 - Ops distantes `Langfuse` + `OpenTelemetry`
- [ ] Lot 9 - Profile `UEFN`
- [ ] Lot 10 - Audit ancien repo `keep / migrate / rewrite / delete`
