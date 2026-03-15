# Learning Runtime And UEFN Autonomy Plan

## Statut

Feuille de route canonique proposee.

Ce document cadre le prochain chantier `learning + verification + UEFN autonomy` de `Project OS`.
Il ne remplace pas la frontiere `OpenClaw` vs `Project OS`.
Il transforme les idees de score, de responsabilite et de self-improvement en architecture verifiable, testable et progressive.

## But

Faire de `Project OS` un systeme qui:

- agit seulement quand la route, la policy et la verification sont coherentes
- apprend par `skills`, `workflows`, `traces` et `verdicts`, pas par un score global flou
- garde `Project OS` comme verite canonique
- utilise `OpenClaw` comme facade operateur
- reutilise le chantier `UEFN` deja pose hors du coeur sans le reecrire depuis zero

Le chantier doit fermer cinq faiblesses:

- absence de `VerifierGate` canonique avant execution
- absence de substrat `evals/graders` dans `project-os-core`
- apprentissage encore centre sur des signaux, pas sur des `skills` et `workflow memory`
- stack `UEFN` deja riche mais encore hors du coeur canonique
- autonomie missionnelle encore partielle et peu connectee au lane `UEFN`

## Point de depart reel

### Ce qui existe deja dans `project-os-core`

- `Mission Router` canonique dans `src/project_os_core/router/service.py`
- `LearningService` deja branche dans `src/project_os_core/learning/service.py`
- injection `learning_context` et `_apply_learning()` dans `src/project_os_core/api_runs/service.py`
- `MissionChainService` deja present dans `src/project_os_core/mission/chain.py`
- `scheduled_tasks` et `mission_chains` deja poses dans `src/project_os_core/database.py`
- frontiere `OpenClaw facade / Project OS truth` deja durcie et documentee

### Ce qui existe deja dans le lane `UEFN` hors coeur

Le chantier `UEFN` n'est pas vide.
Il existe deja hors `project-os-core`, dans `UEFN_Projects/WTF_IDLE_TYCOON/Temp/project_os`:

- `runtime/uefn_surface_graph.py`
- `runtime/uefn_desktop_state.py`
- `runtime/uefn_runtime_policy.py`
- `runtime/uefn_runtime_server.py`
- `config/uefn_action_catalog.json`
- `config/uefn_flow_catalog.json`
- `config/uefn_mission_catalog.json`
- des wrappers `powershell` de controle et de recovery
- des tests runtime sur le surface graph et la runtime policy

### Ce qui manque encore

- aucun package `src/project_os_core/evals/`
- aucun package `src/project_os_core/skills/`
- aucun package canonique `src/project_os_core/uefn/`
- pas de `VerifierGate` obligatoire entre `Mission Router` et l'execution
- pas de `TraceRecord` canonique cross-run / cross-worker
- pas de fiabilite par `skill`
- pas de harness benchmark/eval pour prouver l'amelioration

## Cartographie externe

Cette section rend le document portable pour une autre conversation.
Elle dit explicitement:

- chez qui on recupere quoi
- ce qu'on adapte
- ce qu'on ne copie pas
- dans quel pack chaque source entre

### OpenAI

Sources primaires:

- [Graders guide](https://platform.openai.com/docs/guides/graders)
- [Deliberative alignment](https://openai.com/index/deliberative-alignment/)
- [Rule-based rewards](https://openai.com/index/improving-model-safety-behavior-with-rule-based-rewards/)
- [Chain-of-thought monitoring](https://openai.com/index/chain-of-thought-monitoring/)

Ce qu'on recupere:

- graders multi-axes
- eval-driven design
- policy-aware verification
- regles explicites de reward pour les comportements verifiables

Ce qu'on n'importe pas:

- aucune dependance a une stack OpenAI-only
- aucune logique qui suppose qu'on doive optimser le chain-of-thought comme signal primaire de securite

Ou ca entre:

- `Pack 1 - Evals And Graders Foundation`
- `Pack 5 - Verifier Loop, Abstention, Recovery`
- `Pack 8 - Prompt Ops And Policy Optimization`

Decision:

- `ADAPT`

### Anthropic

Sources primaires:

- [Building Effective AI Agents](https://resources.anthropic.com/building-effective-ai-agents)
- `docs.anthropic.com` pour la surface `computer use`

Ce qu'on recupere:

- design simple d'agents
- boucle `plan -> act -> verify`
- usage mesurable des outils
- human-in-the-loop propre

Ce qu'on n'importe pas:

- aucune dependance a un SDK agent Anthropic comme coeur de `Project OS`

Ou ca entre:

- `Pack 1`
- `Pack 4`
- `Pack 5`
- `Pack 7`

Decision:

- `ADAPT`

### DeepSeek

Sources primaires:

- [DeepSeek-R1 repo](https://github.com/deepseek-ai/DeepSeek-R1)
- [DeepSeekMath paper](https://arxiv.org/abs/2402.03300)
- [DeepSeek-Prover-V2 repo](https://github.com/deepseek-ai/DeepSeek-Prover-V2)
- [DeepSeek-Prover-V2 paper](https://arxiv.org/abs/2504.21801)

Ce qu'on recupere:

- l'idee centrale que le RL devient fort quand la recompense est verifiable
- process rewards
- decomposition en sous-buts verifiables
- calibration par preuve locale

Ce qu'on n'importe pas:

- pas de RL end-to-end immediat
- pas de copie de leur stack d'entrainement

Ou ca entre:

- `Pack 5`
- `Pack 9`

Decision:

- `ADAPT` pour les principes
- `DEFER` pour la partie entrainement lourd

### Microsoft

Sources primaires:

- [UFO repo](https://github.com/microsoft/UFO)
- [UFO paper](https://arxiv.org/abs/2402.07939)
- [UFO2 paper](https://arxiv.org/abs/2504.14603)
- [OmniParser repo](https://github.com/microsoft/OmniParser)
- [WindowsAgentArena repo](https://github.com/microsoft/WindowsAgentArena)

Ce qu'on recupere:

- separation `host agent / app agent`
- patterns Windows-first
- parsing et grounding GUI
- benchmark desktop realiste

Ce qu'on n'importe pas:

- pas de remplacement du coeur `Project OS`
- pas de fork complet `UFO`

Ou ca entre:

- `Pack 3`
- `Pack 4`
- `Pack 6`

Decision:

- `ADAPT`

### ByteDance et ShowLab

Sources primaires:

- [UI-TARS repo](https://github.com/bytedance/UI-TARS)
- [UI-TARS desktop stack](https://github.com/bytedance/UI-TARS-desktop)
- [ShowUI repo](https://github.com/showlab/ShowUI)

Ce qu'on recupere:

- patterns de grounding GUI
- structure de benchmark `OSWorld`
- exemples de stack agent desktop ouverte

Ce qu'on n'importe pas:

- pas d'adoption immediate d'un nouveau modele fondation GUI comme colonne vertebrale

Ou ca entre:

- `Pack 3`
- `Pack 6`

Decision:

- `ADAPT`

### OpenAdapt

Sources primaires:

- [OpenAdapt main repo](https://github.com/OpenAdaptAI/OpenAdapt)
- sous-projets `openadapt-grounding`, `openadapt-retrieval`, `openadapt-agent`

Ce qu'on recupere:

- pipeline `demonstrate -> learn -> execute`
- separation `policy / grounding`
- retrieval de demonstrations
- replay et evaluation a partir des captures

Ce qu'on n'importe pas:

- pas de remplacement complet du lane local UEFN
- pas de migration opportuniste vers leur packaging modulaire

Ou ca entre:

- `Pack 3`
- `Pack 4`
- `Pack 6`

Decision:

- `ADAPT`

### Cradle

Sources primaires:

- [Cradle repo](https://github.com/BAAI-Agents/Cradle)
- [Cradle paper](https://arxiv.org/abs/2403.03186)

Ce qu'on recupere:

- `skill_registry`
- distinction `atomic_skills / composite_skills`
- self-reflection connectee aux skills

Ce qu'on n'importe pas:

- pas de migration de leur architecture complete ni de leurs environnements de demo

Ou ca entre:

- `Pack 2`
- `Pack 6`

Decision:

- `ADAPT`

### Voyager

Sources primaires:

- [Voyager repo](https://github.com/MineDojo/Voyager)
- [Voyager paper](https://arxiv.org/abs/2305.16291)

Ce qu'on recupere:

- bibliotheque de skills executable
- iterative prompting a partir des erreurs d'execution
- self-verification

Ce qu'on n'importe pas:

- pas de curriculum open-ended complet
- pas de transposition directe de Minecraft

Ou ca entre:

- `Pack 2`
- `Pack 6`

Decision:

- `ADAPT`

### Agent Workflow Memory

Sources primaires:

- [Agent Workflow Memory repo](https://github.com/zorazrw/agent-workflow-memory)
- [Agent Workflow Memory paper](https://arxiv.org/abs/2409.07429)

Ce qu'on recupere:

- la notion de `workflow memory`
- abstraction de sous-routines recurrentes
- promotion offline et online de workflows

Ce qu'on n'importe pas:

- pas de couplage a WebArena/Mind2Web comme coeur d'eval principal

Ou ca entre:

- `Pack 2`
- `Pack 6`

Decision:

- `ADAPT`

### MemOS et plugins memoire

Sources primaires:

- [MemOS repo](https://github.com/MemTensor/MemOS)
- [MemOS Cloud OpenClaw Plugin](https://github.com/MemTensor/MemOS-Cloud-OpenClaw-Plugin)
- `openclaw-memos-lifecycle-plugin`

Ce qu'on recupere:

- memoire typée `profile / behavior / skill / event / task`
- compaction et recovery
- skill evolution
- pattern de lifecycle plugin memoire

Ce qu'on n'importe pas:

- pas de deuxieme source de verite memoire
- pas de remplacement de la DB canonique `Project OS`

Ou ca entre:

- `Pack 2`
- `Pack 6`

Decision:

- `ADAPT`

### Google DeepMind

Sources primaires:

- [Project Mariner](https://deepmind.google/technologies/project-mariner/)

Ce qu'on recupere:

- teach-and-repeat
- demonstration and replay mindset
- prudence sur les actions web/GUI a haut risque

Ce qu'on n'importe pas:

- pas de dependance a une stack fermee
- pas de couplage Chrome-first dans le lane `UEFN`

Ou ca entre:

- `Pack 6`

Decision:

- `ADAPT` pour le pattern, pas pour la stack

### Benchmarks et verifiers

Sources primaires:

- [AgentRewardBench paper](https://arxiv.org/abs/2504.08942)
- [WindowsAgentArena](https://github.com/microsoft/WindowsAgentArena)
- [AgentBench paper](https://arxiv.org/abs/2308.03688)

Ce qu'on recupere:

- benchmark des evaluateurs automatiques
- benchmark desktop Windows
- discipline de benchmark multi-environnements

Ce qu'on n'importe pas:

- pas de benchmark externe comme unique metrique de succes

Ou ca entre:

- `Pack 1`
- `Pack 5`
- `Pack 6`

Decision:

- `KEEP` comme references d'eval

### Sources deja presentes chez nous

Sources locales a reutiliser avant toute copie externe:

- `src/project_os_core/router/service.py`
- `src/project_os_core/api_runs/service.py`
- `src/project_os_core/learning/service.py`
- `src/project_os_core/mission/chain.py`
- `UEFN_Projects/WTF_IDLE_TYCOON/Temp/project_os/runtime/uefn_surface_graph.py`
- `UEFN_Projects/WTF_IDLE_TYCOON/Temp/project_os/runtime/uefn_desktop_state.py`
- `UEFN_Projects/WTF_IDLE_TYCOON/Temp/project_os/runtime/uefn_runtime_policy.py`

Ce qu'on recupere:

- la frontiere de verite deja posee
- les catalogues d'actions `UEFN`
- les wrappers et policies deja testes

Ce qu'on n'importe pas:

- rien de concurrent

Ou ca entre:

- tous les packs

Decision:

- `KEEP` prioritaire

## Regles d'architecture

Regles dures:

- `Project OS` garde la verite canonique
- `OpenClaw` reste facade / transport / UX operateur
- toute action passe par `Mission Router` puis `VerifierGate`, jamais l'inverse
- aucune action destructive sans policy explicite et preuve d'approbation
- aucun score global unique ne pilote l'autonomie
- l'apprentissage durable porte sur des `skills`, des `workflows`, des `traces`, des `verdicts`
- le lane `UEFN` doit etre canonicalise progressivement dans le coeur, pas duplique
- les wrappers `powershell` et scripts `Temp/project_os` peuvent survivre comme surface d'integration locale tant que le coeur Python devient canonique
- aucune reecriture complete de `UEFN` runtime n'est autorisee en phase initiale

## Strategie de refactor

### Principe general

Ne pas recreer un second systeme.
Le bon mouvement est:

1. garder `project-os-core` comme source canonique
2. extraire les briques stables de `Temp/project_os/runtime` vers `src/project_os_core/uefn/`
3. garder temporairement les scripts `powershell` comme adaptateurs d'environnement local
4. brancher la verification et l'apprentissage au-dessus de ces briques extraites

### Refactor cible du repo

Packages a ajouter:

- `src/project_os_core/evals/`
- `src/project_os_core/skills/`
- `src/project_os_core/uefn/`

Packages a etendre:

- `src/project_os_core/models.py`
- `src/project_os_core/database.py`
- `src/project_os_core/services.py`
- `src/project_os_core/router/service.py`
- `src/project_os_core/api_runs/service.py`
- `src/project_os_core/learning/service.py`
- `src/project_os_core/mission/chain.py`
- `src/project_os_core/scheduler/service.py`

Principe de migration `UEFN`:

- `surface_graph`, `desktop_state`, `runtime_policy` et les catalogues deviennent des briques Python canoniques dans `src/project_os_core/uefn/`
- `Temp/project_os/control/*.ps1` reste la couche de transport Windows/UEFN tant qu'une couche Python native ne la remplace pas proprement
- les fichiers `Temp/project_os/config/*.json` deviennent soit des assets canoniques du coeur, soit des fichiers config versionnes et charges par le coeur

## Ordre retenu

1. `Pack 0 - Invariants And Runtime Contract`
2. `Pack 1 - Evals And Graders Foundation`
3. `Pack 2 - Skill Reliability And Workflow Memory`
4. `Pack 3 - UEFN Grounding Canonicalization`
5. `Pack 4 - Hybrid Action Layer`
6. `Pack 5 - Verifier Loop, Abstention, Recovery`
7. `Pack 6 - Teach And Repeat`
8. `Pack 7 - Mission Autonomy`
9. `Pack 8 - Prompt Ops And Policy Optimization`
10. `Pack 9 - Targeted RL`

Pourquoi cet ordre:

- on fixe d'abord le contrat systeme
- on pose ensuite les preuves et la mesure
- on rend ensuite l'apprentissage specifique et cumulatif
- on canonicalise ensuite le lane `UEFN`
- on branche ensuite l'execution hybride et sa verification
- on industrialise ensuite la capture et le replay
- on ouvre ensuite l'autonomie missionnelle
- on n'optimise prompts et RL qu'apres la mesure

## Pack 0 - Invariants And Runtime Contract

### Objet

Geler les invariants du systeme pour fermer les ambiguitees d'architecture avant d'ajouter des couches d'apprentissage.

### Reuse explicite

- `src/project_os_core/router/service.py`
- `src/project_os_core/gateway/openclaw_live.py`
- `src/project_os_core/mission/chain.py`
- docs `OPENCLAW_REINFORCEMENT_PLAN.md`

### Travaux

- rediger un ADR unique `Learning Runtime`
- figer les frontieres `OpenClaw facade / Mission Router truth / VerifierGate obligatoire`
- figer la regle `aucune action destructive sans policy`
- figer le placement du futur `VerifierGate` apres routage et avant execution
- figer le fait qu'un echec de verification degrade la confiance d'un `skill`, pas "l'agent" global

### Livrables

- `docs/decisions/00xx-learning-runtime-and-verifier-gate.md`
- references croisees depuis `docs/roadmap/BUILD_STATUS_CHECKLIST.md`

### Criteres d'acceptation

- aucune doc active ne laisse entendre qu'un worker peut agir avant le router
- le futur `VerifierGate` a une place claire dans le graphe
- la politique destructive est unique et non contradictoire

### Non-buts

- creer deja les graders
- brancher deja le lane `UEFN`

## Pack 1 - Evals And Graders Foundation

### Objet

Poser le substrat de mesure qui manque aujourd'hui.

### Etat de depart

`project-os-core` a deja des verdicts et des reviews, mais pas encore un package `evals` canonique ni un schema de traces cross-surface.

### Refactor repo

Ajouter:

- `src/project_os_core/evals/__init__.py`
- `src/project_os_core/evals/models.py`
- `src/project_os_core/evals/service.py`
- `src/project_os_core/evals/registry.py`
- `src/project_os_core/evals/graders.py`
- `src/project_os_core/evals/fixtures.py`

Etendre:

- `src/project_os_core/models.py`
- `src/project_os_core/database.py`
- `src/project_os_core/services.py`

### Schema canonique a ajouter

Nouvelles tables:

- `trace_records`
- `grader_runs`
- `grader_verdicts`
- `benchmark_tasks`
- `benchmark_runs`

Objets canoniques a ajouter:

- `TraceRecord`
- `GraderAxis`
- `GraderVerdict`
- `BenchmarkTask`
- `BenchmarkRun`

### Graders minimum

Quatre graders separes:

- `outcome`
- `safety`
- `evidence`
- `policy`

### Integration

- `api_runs` enregistre des traces evaluables
- `mission chains` peuvent etre notees
- `scheduler` peut lancer des suites d'eval
- `learning` peut consommer les verdicts grader

### Jeu initial

Un premier set de `30 a 50` taches canoniques:

- `api_runs` code
- `routing`
- `Discord/OpenClaw truth`
- `UEFN read-only shell`
- `UEFN safe_write`
- `UEFN recovery`

### Criteres d'acceptation

- aucun run autonome sans note par axe
- chaque verdict grader est persiste
- les traces et verdicts sont rejouables localement

### Non-buts

- optimiser les prompts
- faire du RL

## Pack 2 - Skill Reliability And Workflow Memory

### Objet

Remplacer la logique implicite de "bon ou mauvais agent" par une fiabilite locale, cumulative et specifique a un `skill` ou un `workflow`.

### Etat de depart

Le coeur sait deja enregistrer:

- decisions
- signaux
- loops
- refresh recommendations
- dataset/eval candidates

Mais il ne sait pas encore promouvoir proprement:

- un `skill`
- un `workflow`
- une `reliability curve`

### Refactor repo

Ajouter:

- `src/project_os_core/skills/__init__.py`
- `src/project_os_core/skills/models.py`
- `src/project_os_core/skills/service.py`
- `src/project_os_core/skills/promotion.py`
- `src/project_os_core/skills/reliability.py`

Etendre:

- `src/project_os_core/learning/service.py`
- `src/project_os_core/memory/store.py`
- `src/project_os_core/memory/curator.py`
- `src/project_os_core/api_runs/service.py`

### Tables a ajouter

- `skill_records`
- `workflow_records`
- `skill_executions`
- `skill_reliability`

### Typologie memoire a figer

- `profile`
- `behavior`
- `skill`
- `event`
- `task`

### Regles

- un run accepte peut promouvoir un `workflow`
- un `workflow` stable peut promouvoir un `skill`
- un echec degrade seulement la fiabilite locale du skill concerne
- un score global humainement lisible peut exister pour reporting, jamais pour gouverner seul

### Criteres d'acceptation

- un skill a un historique d'execution, pas juste une note statique
- les replays et verdicts alimentent la fiabilite
- la memoire procedurale devient interrogeable par `skill` et `workflow`

### Non-buts

- generer encore des demonstrations
- brancher encore le lane UEFN complet

## Pack 3 - UEFN Grounding Canonicalization

### Objet

Faire passer le lane `UEFN` de runtime local riche mais hors coeur a une brique canonique reutilisable par `Project OS`.

### Etat de depart

Le lane `UEFN` existe deja hors coeur dans `Temp/project_os/runtime`.
Il ne faut pas le reecrire depuis zero.

### Refactor repo

Ajouter:

- `src/project_os_core/uefn/__init__.py`
- `src/project_os_core/uefn/catalogs.py`
- `src/project_os_core/uefn/surface_graph.py`
- `src/project_os_core/uefn/desktop_state.py`
- `src/project_os_core/uefn/grounding.py`
- `src/project_os_core/uefn/refs.py`

Etendre:

- `src/project_os_core/services.py`
- `src/project_os_core/models.py`
- `src/project_os_core/paths.py`

### Strategie de migration

Extraire progressivement depuis:

- `Temp/project_os/runtime/uefn_surface_graph.py`
- `Temp/project_os/runtime/uefn_desktop_state.py`
- `Temp/project_os/runtime/uefn_runtime_policy.py`
- `Temp/project_os/config/uefn_action_catalog.json`
- `Temp/project_os/config/uefn_flow_catalog.json`
- `Temp/project_os/config/uefn_mission_catalog.json`

### Resultat cible

Un service hybride:

- `UIA`
- `screenshot`
- `OCR`
- `Set-of-Mark`

avec:

- `surface graph` stable
- `ui refs`
- `target_id` semantique
- score d'incertitude de ciblage

### Criteres d'acceptation

- le coeur Python sait reconstruire l'etat UEFN sans shell ad hoc externe
- les clics XY ne sont plus la verite primaire
- le systeme sait dire "incertain" et s'abstenir

### Non-buts

- supprimer tous les wrappers `powershell`
- faire deja de la vision-only pure

## Pack 4 - Hybrid Action Layer

### Objet

Poser un `AppAgent UEFN` qui choisit la meilleure voie d'action sans confondre action, perception et verification.

### Refactor repo

Ajouter:

- `src/project_os_core/uefn/actions.py`
- `src/project_os_core/uefn/contracts.py`
- `src/project_os_core/uefn/app_agent.py`

Etendre:

- `src/project_os_core/router/service.py`
- `src/project_os_core/services.py`

### Ordre d'execution interne

Priorites:

1. commande native ou action deterministe
2. UIA/semantic target
3. vision click fallback

Chaque action doit porter:

- preconditions
- postconditions
- dry-run summary
- rollback hint
- risk mode

### Criteres d'acceptation

- aucune action si la postcondition attendue n'est pas verifiable
- aucune action destructive si la verification pre-action est insuffisante
- le fallback vision reste borne et explicite

### Non-buts

- remplacer tous les scripts de controle locaux d'un coup

## Pack 5 - Verifier Loop, Abstention, Recovery

### Objet

Faire de la "punition" une propriete architecturale:

- blocage
- revision
- escalade
- baisse de confiance

### Refactor repo

Ajouter:

- `src/project_os_core/evals/verifier_gate.py`
- `src/project_os_core/evals/outcome_scorer.py`
- `src/project_os_core/evals/abstention.py`
- `src/project_os_core/evals/recovery.py`

Etendre:

- `src/project_os_core/router/service.py`
- `src/project_os_core/api_runs/service.py`
- `src/project_os_core/mission/chain.py`
- futur `src/project_os_core/uefn/app_agent.py`

### Contrat canonique

Le `Mission Router` choisit si la mission est autorisee et quel lane est legitime.
Le `VerifierGate` decide si l'execution courante est suffisamment prouvable.

Sorties minimales:

- `go`
- `revise`
- `ask`
- `block`

### Policies a brancher

- `AbstentionPolicy`
- `RecoveryPolicy`
- `LoopPolicy`
- `PostconditionPolicy`

### Criteres d'acceptation

- aucune execution `UEFN` sans passage `router -> verifier -> executor`
- les raisons de blocage sont persistantes et lisibles
- un echec repete degrade la confiance du skill concerne

### Non-buts

- masquer les chain-of-thoughts comme signal de securite primaire
- faire du reward shaping opaque

## Pack 6 - Teach And Repeat

### Objet

Industrialiser la capture, le replay et la promotion de traces approuvees en `skills` reutilisables.

### Refactor repo

Ajouter:

- `src/project_os_core/uefn/demo_capture.py`
- `src/project_os_core/uefn/replay.py`
- `src/project_os_core/uefn/state_diff.py`
- `src/project_os_core/skills/clustering.py`

Etendre:

- `src/project_os_core/evals/service.py`
- `src/project_os_core/learning/service.py`

### Actifs a produire

- demonstrations UEFN capturees
- replay harness
- diff d'etat avant/apres
- clustering des erreurs
- bibliotheque de `golden traces`

### Criteres d'acceptation

- une trace approuvee peut etre rejouee et comparee
- une bonne sequence peut promouvoir un workflow
- une mauvaise sequence cree un pattern d'echec exploitable

### Non-buts

- fine-tuning immediat

## Pack 7 - Mission Autonomy

### Objet

Faire vivre l'autonomie missionnelle sans creer un second moteur.

### Etat de depart

Le repo a deja:

- `MissionChainService`
- `scheduled_tasks`
- `SchedulerService`

Le bon travail est de les renforcer, pas de les remplacer.

### Refactor repo

Etendre:

- `src/project_os_core/mission/chain.py`
- `src/project_os_core/scheduler/service.py`
- `src/project_os_core/api_runs/service.py`
- `src/project_os_core/router/service.py`

### Travaux

- connecter les graders aux chaines
- connecter `refresh recommendations` et `loop signals` aux chaines
- connecter les scheduled runs aux suites d'eval
- preparer des chaines `UEFN workflows` au-dessus des catalogues canoniques

### Criteres d'acceptation

- autonomie limitee mais controlee sur les chaines `audit -> design -> patch_plan -> generate_patch`
- autonomie `UEFN` bornee a des workflows explicitement approuves
- toute escalation reste tracable et reproductible

### Non-buts

- autonomie ouverte illimitee

## Pack 8 - Prompt Ops And Policy Optimization

### Objet

Optimiser prompts, contracts et policies uniquement apres que la mesure et les traces soient stables.

### Refactor repo

Ajouter:

- `src/project_os_core/evals/optimization.py`
- `src/project_os_core/evals/datasets.py`

Etendre:

- `src/project_os_core/api_runs/service.py`
- `src/project_os_core/evals/service.py`

### Boucle cible

- dataset
- eval suite
- prompt variants
- grader results
- best policy

### Criteres d'acceptation

- toute optimisation est benchmark-driven
- un prompt ne change pas sans impact mesure
- les verifiers et contracts ont aussi des evals

### Non-buts

- optimisation intuitionniste
- recompilation sauvage de prompts sans regression suite

## Pack 9 - Targeted RL

### Statut

`DEFER`

### Objet

Introduire du RL ou du `GRPO` uniquement sur des sous-problemes a recompense claire.

### Cibles legitimes

- ranking de cibles UI
- selection d'actions
- calibration des verifiers
- choix de recovery

### Preconditions

- benchmark stable
- labels fiables
- traces suffisantes
- baseline non-RL deja forte

### Non-buts

- RL end-to-end du lane `UEFN`
- seconde architecture d'entrainement opaque des le debut

## Impact sur la roadmap existante

Cette feuille de route recoupe et precise:

- `Lot 6 - Windows worker + perception`
- `Lot 9 - Profile UEFN`

Elle consomme aussi des briques deja prevues ou deja presentes:

- `Mission chains`
- `scheduled runs`
- `learning context`
- `OpenClaw reinforcement`

Le bon mouvement n'est pas de creer une roadmap concurrente.
Le bon mouvement est de s'en servir comme plan operatoire detaille pour fermer:

- le trou `verification/evals`
- le trou `skills/workflow memory`
- le trou `UEFN canonical`

## Definition of done globale

Le chantier sera considere vraiment lance proprement quand:

1. un ADR `Learning Runtime` fige les invariants
2. un package `evals` canonique existe
3. un package `skills` canonique existe
4. les briques `UEFN` stables ont commence a migrer vers `src/project_os_core/uefn/`
5. le chemin `Mission Router -> VerifierGate -> Executor` est explicite dans le code
6. une premiere suite benchmark locale prouve ou casse objectivement les progres

## References

- `src/project_os_core/router/service.py`
- `src/project_os_core/api_runs/service.py`
- `src/project_os_core/learning/service.py`
- `src/project_os_core/mission/chain.py`
- `src/project_os_core/database.py`
- `docs/roadmap/BUILD_STATUS_CHECKLIST.md`
- `docs/roadmap/OPENCLAW_REINFORCEMENT_PLAN.md`
- `UEFN_Projects/WTF_IDLE_TYCOON/Temp/project_os/runtime/uefn_surface_graph.py`
- `UEFN_Projects/WTF_IDLE_TYCOON/Temp/project_os/runtime/uefn_desktop_state.py`
- `UEFN_Projects/WTF_IDLE_TYCOON/Temp/project_os/runtime/uefn_runtime_policy.py`
- `UEFN_Projects/WTF_IDLE_TYCOON/Temp/project_os/config/uefn_action_catalog.json`
- `UEFN_Projects/WTF_IDLE_TYCOON/Temp/project_os/config/uefn_flow_catalog.json`
