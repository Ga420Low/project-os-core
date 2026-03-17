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
- [x] `Retrieval Sidecar` pose
- [x] `MemoryBlock` partages poses
- [x] `MemCube` poses
- [x] `ThoughtMemory` posees
- [x] `Sleeptime Curator` async pose
- [x] Profils dual-layer poses
- [x] Supersession non destructive posee
- [x] Traces memoire persistantes posees
- [x] `Temporal Graph` local sidecar pose

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
- [x] Workflow hybride `Discord + Claude API + GPT API + runtime local` documente
- [x] Discipline `DECISION CONFIRMED / DECISION CHANGED` documentee
- [x] Skills de mega prompt documentes
- [x] Identite agent unique documentee
- [x] Handoff memoire supervision locale / API / Discord documente
- [x] Policy Discord + routing adaptatif documentes

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
  - [x] Dashboard auto-lance avant chaque run API reel
  - [x] Run API reel `gpt-5.4` valide sur le poste
- [x] Operating Model vNext
  - [x] `AGENTS.md` racine complet
  - [x] Policy `silence + fin` documentee
  - [x] Contrat de run documente
  - [x] Topologie Discord `hub + salons` documentee
  - [x] Policy outputs operateur en francais clair documentee
  - [x] Workflow `discussion -> contrat -> run silencieux -> rapport -> review` documente
- [ ] Lot 4 - Gateway + Mission Router adapter `OpenClaw` live
  - [x] Entree Python generique `gateway ingest-openclaw-event`
  - [x] Adaptateur package `OpenClaw` local cree
  - [x] Politique `OpenClaw facade / Project OS verite` respectee dans le code
  - [x] Ingress `message_received -> ChannelEvent -> Mission Router` branche
  - [x] Runtime OpenClaw dedie pose (`D:\ProjectOS\openclaw-runtime`)
  - [x] State OpenClaw dedie pose (`D:\ProjectOS\runtime\openclaw`)
  - [x] Bootstrap natif `plugins install --link` valide sur le poste
  - [x] `project-os openclaw doctor` vert sur le poste
  - [x] Replay harness obligatoire vert sur le poste
  - [x] Commande `openclaw truth-health` posee pour la verite live Windows
  - [x] Validation live canonique enregistree via `openclaw validate-live`
  - [x] Cartes Discord compactes preparees dans le modele operateur
  - [x] Runtime `OpenClaw` configure sur Discord du poste
  - [ ] Preuve operateur manuelle depuis un vrai message Discord/WebChat amont
  - [x] Voie locale Windows-first `Ollama + qwen2.5:14b` visible dans `router model-health`
  - [x] `S3` traite localement quand la voie locale est `ready`
- [x] Operating Model v2 - Dual Model (ADR 0013)
  - [x] ADR 0013 redige (supersede ADR 0010)
  - [x] Workflow quotidien fondateur documente
  - [x] Carte des roles GPT API / Claude API / fondateur documentee
  - [x] Niveaux de langage (machine / prompt structure / humain) documentes
  - [x] Templates Discord documentes
  - [x] MASTER_MACHINE, AGENTS, HYBRID_WORKFLOW mis a jour
  - [x] ADR 0010 marque SUPERSEDED
  - [x] Implementation `_call_reviewer()` Claude API dans service.py
  - [x] Implementation `_call_translator()` Claude API dans service.py
  - [x] Champs de clarification fondatrice dans le structured output GPT
  - [x] Filtre anti-bruit dans le pipeline operator delivery
- [ ] Lot API Runs - Persistence atomique
  - [ ] Remplacer INSERT OR REPLACE par INSERT strict sur toutes les tables api_run_*
  - [ ] Wrapper les multi-table writes dans db.transaction()
  - [ ] Ajouter expected_updated_at sur mark_operator_delivery()
  - [ ] Test d'integrite mid-transaction
- [ ] Lot API Runs - Learning Context Injection
  - [ ] Relire les completion_reports recents dans build_context_pack()
  - [ ] Bloc LESSONS_LEARNED dans le context_pack (max 800 tokens)
  - [ ] Tests: run apres rejets inclut les signaux negatifs
- [ ] Lot API Runs - Guardian Pre-Spend Gate
  - [ ] Check budget journalier avant _call_openai()
  - [ ] Detection de boucle (3+ runs meme branche/mode en 2h)
  - [ ] Check taille contexte anormale
  - [ ] Chaque check produit clarification_required, pas un blocage dur
- [ ] Lot API Runs - Hot Memory Integration
  - [ ] Memory card JSON apres review accepted
  - [ ] Inclusion des cards recentes dans build_context_pack()
  - [ ] TTL 7 jours avec migration vers warm
- [ ] Lot API Runs - Run Chain / Missions
  - [ ] Dataclass Mission + MissionStep
  - [ ] Table missions + mission_steps
  - [ ] create_mission() -> PATCH_PLAN automatique
  - [ ] advance_mission() -> run suivant avec contexte
  - [ ] Guard dur 8 steps max
- [ ] Lot API Runs - Scheduled Autonomous Runs
  - [ ] Dataclass ScheduledRun
  - [ ] Table scheduled_runs
  - [ ] check_scheduled_runs() dans la boucle monitor
  - [ ] Guard 5 schedules max actifs
- [x] Lot Persona V2 + Context Integrity
  - [x] `Pack 1 - Persona V2`
  - [x] `Pack 2 - Context Integrity`
  - [x] `Pack 3 - Prompt Ops And Evals`
  - [x] Feuille de route canonique posee dans `docs/roadmap/PERSONA_V2_CONTEXT_INTEGRITY_PLAN.md`
- [x] Lot Discord Autonomy No-Loss
  - [x] Feuille de route canonique posee dans `docs/roadmap/DISCORD_AUTONOMY_NO_LOSS_PLAN.md`
  - [x] `Pack A - Lossless Input`
  - [x] `Pack B - Long Context Workflow`
  - [x] `Pack C - Artifact-First Output`
  - [x] `Pack D - Delivery Guarantees`
  - [x] `Pack E - UX And Observability`
- [x] Lot Natural Manager Mode
  - [x] Feuille de route canonique posee dans `docs/roadmap/NATURAL_MANAGER_MODE_PLAN.md`
  - [x] `Pack 1 - Intent Taxonomy And State Machine`
  - [x] `Pack 2 - Natural Directive Extraction`
  - [x] `Pack 3 - Action Contract And Clarification Gate`
  - [x] `Pack 4 - Execution Handoff And Reporting UX`
  - [x] `Pack 5 - Evals And Smoke Tests`
  - [x] Extension `Escalade cout-aware + go fondateur` integree au runtime
  - [x] Extension `Deep research -> cout + temps + go` harmonisee
  - [x] Extension `Discussion Sonnet -> proposition Opus + go` harmonisee
- [ ] Lot Discord Facade And Continuity Patch
  - [x] Feuille de route canonique posee dans `docs/roadmap/DISCORD_FACADE_AND_CONTINUITY_PATCH_PLAN.md`
  - [x] `Pack 1 - Visibility Contract And Protected Cases`
  - [x] `Pack 2 - Standard Reply Cleanup Outside Deep Research`
  - [x] `Pack 3 - Discord Medium Format And Human Delivery`
  - [x] `Pack 4 - Immediate And Thread Continuity`
  - [x] `Pack 5 - Project Continuity, Retention And Regression Rails`
- [ ] Lot Discord Meeting OS
  - [x] Feuille de route canonique posee dans `docs/roadmap/DISCORD_MEETING_OS_PLAN.md`
  - [ ] `Pack 1 - Voice Session Contract`
  - [ ] `Pack 2 - Voice Transport And Speech Loop`
  - [ ] `Pack 3 - Meeting Mode Switching And Cost Guard`
  - [ ] `Pack 4 - Meeting Memory And Artifact Output`
  - [ ] `Pack 5 - Background Worker Mesh`
  - [ ] `Pack 6 - Guest Agent Protocol`
  - [ ] `Pack 7 - Cost Accounting, Safety And Live Evals`
- [ ] Lot Debug System v1
  - [x] Feuille de route canonique posee dans `docs/roadmap/DEBUG_SYSTEM_V1_PLAN.md`
  - [ ] `Pack 0 - Taxonomie des IDs, filiation causale, invariants DB, quarantine des sorties invalides`
  - [ ] `Pack 1 - Correlation spine locale, debug trace, couverture via SQLite/logs/CLI`
  - [ ] `Pack 2 - Replay canonique, reprise background, idempotence et dead letters multi-domaines`
  - [ ] `Pack 3 - Incident engine, substrat evals unique et provenance`
  - [ ] `Pack 4 - Dashboard, Discord debug, privacy TTL, gates progressifs`
  - [ ] `Pack 5 - Resilience systeme`
  - [ ] `Pack 6 - Audit final du debug live Discord`
  - [ ] `Pack supplementaire - Corrections du debug live Discord (si l'audit final l'exige)`
- [ ] Sanctuary Security Layer v1
  - [ ] Approval Truth Hardening
  - [ ] Destructive Boundary Hardening
  - [ ] Data Egress Guard
  - [ ] Local Surfaces And Token Hygiene
  - [ ] Recovery Without Unsafe Degrade
- [ ] Lot 5 - Orchestration durable `LangGraph` live
- [ ] Lot 6 - Windows worker + perception
- [ ] Lot 7 - Browser worker `Stagehand`
- [ ] Lot 9 - Profile `UEFN`
- [ ] Lot 10 - Audit ancien repo `keep / migrate / rewrite / delete`

## Extensions optionnelles

- [ ] Extension A - Remote export et triage heberge
  - [ ] Frontiere OTLP propre vers `Sentry`, `Tempo`, `Jaeger`, `Langfuse` ou `LangSmith`
  - [ ] Export desactive par defaut
  - [ ] Aucune plateforme externe ne devient la verite canonique
- [ ] Extension B - Auto-learning de correction
  - [ ] Regroupement d'incidents similaires
  - [ ] Suggestion de replay ou d'eval manquants
  - [ ] Proposition de `fix patterns` a partir des incidents clos

## Documentation systeme complete

- [x] Physical Storage Layout (`docs/architecture/PHYSICAL_STORAGE_LAYOUT.md`)
- [x] Quality Standards (`docs/architecture/QUALITY_STANDARDS.md`)
- [x] Error Recovery and Resilience (`docs/architecture/ERROR_RECOVERY_AND_RESILIENCE.md`)
- [x] Cost Optimization Strategy (`docs/architecture/COST_OPTIMIZATION_STRATEGY.md`)
- [x] Worker Capability Contracts (`docs/architecture/WORKER_CAPABILITY_CONTRACTS.md`)
- [x] Third-Party Integration Guide (`docs/knowledge/THIRD_PARTY_INTEGRATION_GUIDE.md`)
- [x] Automation Modes and Chaining (`docs/architecture/AUTOMATION_MODES_AND_CHAINING.md`)
