# Project OS Canonical Data Model Contract

## Statut

ACTIVE - First locked data contract before heavy implementation

## But

Figer le langage de donnees canonique de `Project OS` pour que:

- la `PWA` parle le meme langage que les runners
- `OpenClaw`, `Codex CLI` et `Project OS` n'inventent pas chacun leur propre verite
- la V1 mono-noeud reste extractible en V2 sans gros refacto
- les promotions, approvals, runs, docs et artefacts restent rejouables

Ce document verrouille:

- les familles d'objets
- la source de verite de chaque famille
- les liens obligatoires entre objets
- les noms de contrat a garder stables
- ce qui existe deja dans le code et ce qui reste une cible contractuelle

## Mantra

- centraliser la verite
- isoler le risque
- rendre chaque action rejouable
- garder Windows ennuyeux et stable
- ne jamais confondre prototype qui marche et systeme tenable

## Regle racine

`Project OS` garde la verite operateur.

`GitHub` garde la verite du code.

`OpenClaw` orchestre.

`Codex CLI` execute.

Aucun de ces composants ne doit casser ce partage.

## Frontieres de verite

| Domaine | Verite canonique | Notes |
| --- | --- | --- |
| Code source | `GitHub private repo` | branches, commits, PR, review |
| Etat operateur | `Project OS DB` | tasks, decisions, preferences, runs, docs metadata |
| Artefacts lourds | `object storage` a terme | en V1, volume local structure mais metadata deja en DB |
| Memoire froide | `8 To local` | miroir, archive, cold memory, jamais source unique |
| Execution locale | `runner Linux` | verite d'execution locale, jamais verite globale du projet |

## Contrat de separation produit

### OpenClaw

`OpenClaw` ne possede pas la verite produit.

Il peut:

- lire des politiques, preferences et documents indexes
- produire des intentions, plans et demandes d'execution
- consommer des etats de session et de runtime

Il ne doit pas:

- devenir la base de donnees du projet
- porter seul la memoire operateur
- definir ses propres schemas concurrents pour les objets centraux

### Codex CLI

`Codex CLI` est un moteur d'execution.

Il peut:

- recevoir un `RunRequest`
- travailler dans un workspace Git
- produire des artefacts, logs, sorties et patchs

Il ne doit pas:

- devenir lui-meme la timeline canonique
- garder la seule copie des resultats
- ecrire directement dans le clone humain Windows

### Project OS

`Project OS` porte:

- la DB canonique
- la timeline
- les approvals
- les decisions
- les preferences
- les docs et metadata d'artefacts
- l'etat runner et le fallback

## Familles d'objets canoniques

### 1. Ingress operateur

Objets:

- `ConversationThreadRef`
- `OperatorAttachment`
- `OperatorMessage`
- `ChannelEvent`
- `OperatorEnvelope`

Role:

- decrire ce que l'operateur a envoye
- garder la surface, le thread, les pieces jointes et le contexte d'entree

Source canonique:

- `Project OS DB`

Regle:

- tout message utile entre d'abord comme evenement, pas comme effet implicite

### 2. Intention et mission

Objets:

- `MissionIntent`
- `MissionRun`
- `MissionChain`

Role:

- transformer une entree operateur en objectif machine clair
- garder le suivi des missions, de leurs etapes et de leur statut

Source canonique:

- `Project OS DB`

Regles:

- un `MissionIntent` peut exister sans run immediat
- un `MissionRun` doit toujours pointer vers un `MissionIntent`
- les chains longues vivent dans `MissionChain`, pas dans des prompts perdus

### 3. Routage et execution

Objets existants:

- `RoutingDecision`
- `RoutingDecisionTrace`
- `WorkerRequest`
- `ExecutionTicket`
- `WorkerDispatchEnvelope`
- `ActionEvidence`
- `RuntimeState`
- `SessionState`

Role:

- decider ou va le travail
- prouver pourquoi il y va
- borner ce qui a ete execute
- garder la preuve machine de l'action

Source canonique:

- `Project OS DB`

Regles:

- tout run doit laisser une trace de routage
- toute execution importante doit produire de l'evidence
- un `ActionEvidence` sans contexte de run ou de session est anormal

### 4. Runs API / lane code

Objets existants:

- `RunContract`
- `ApiRunRequest`
- `ApiRunResult`
- `ApiRunReview`
- `CompletionReport`
- `BlockageReport`
- `ClarificationReport`
- `RunLifecycleEvent`
- `OperatorDelivery`

Role:

- porter les gros runs de code, review et handoff operateur

Source canonique:

- `Project OS DB`

Regles:

- pas de gros run sans `RunContract` si la policy l'exige
- `ApiRunResult` ne vaut pas promotion automatique
- seule la review et/ou la validation humaine rend le resultat durablement actionnable

### 5. Gouvernance et garde-fous

Objets existants:

- `ApprovalRecord`
- `DecisionRecord`
- `LearningSignal`
- `LoopSignal`
- `RefreshRecommendation`
- `OutputQuarantineRecord`
- `DeadLetterRecord`
- `IncidentRecord`

Objets cibles a ajouter proprement:

- `PreferenceRecord`
- `TaskRecord`
- `GitChangeProposal`
- `RunnerHeartbeat`

Role:

- garder les approbations, decisions, alertes, incidents et propositions critiques

Source canonique:

- `Project OS DB`

Regles:

- une decision importante doit devenir un `DecisionRecord`
- une preference fondateur stable doit devenir un `PreferenceRecord`
- aucune auto-amelioration profonde ne saute cette couche

### 6. Memoire et connaissance

Objets existants:

- `MemoryRecord`
- `MemoryBlock`
- `MemCube`
- `RecallPlan`
- `CuratorRun`
- `ThoughtMemory`
- `SupersessionRecord`
- `RetrievalContext`

Objets cibles a formaliser davantage:

- `DocumentRecord`
- `ResearchSourceRecord`
- `PreferenceRecord`

Role:

- stocker ce qui doit etre relu, retrouve, promu et rejoue

Source canonique:

- `Project OS DB` pour metadata et retrieval
- `object storage` a terme pour les blobs lourds

Regles:

- pas de transcript brut promu par defaut
- seules les syntheses, decisions, preferences et documents utiles entrent en memoire durable

### 7. Artefacts et documents

Objets existants:

- `ArtifactPointer`
- `ApiRunArtifact`
- `OperatorReplyArtifact`
- `ArtifactLedgerEntry`
- `ArtifactIngestionTask`
- `HumanArtifact`

Nom de contrat a retenir:

- `ArtifactRef`

Role:

- referencer un binaire, un PDF, une capture, un export ou un bundle de preuve

Source canonique:

- metadata en `Project OS DB`
- binaire en volume structure V1, puis `object storage`

Regles:

- un artefact canonique a toujours:
  - un `artifact_id`
  - un `owner_type`
  - un `owner_id`
  - un `artifact_kind`
  - une localisation
- le systeme ne doit jamais dependre d'un chemin magique non indexe

## Noms de contrat a figer

Les noms ci-dessous sont les noms de contrat a garder stables dans le temps, meme si
les classes Python concretes evoluent.

| Nom de contrat | Etat actuel | Mapping courant |
| --- | --- | --- |
| `RunRequest` | partiellement implemente | `ApiRunRequest` pour la lane API, `ExecutionTicket` / `WorkerRequest` pour la lane worker |
| `RunEvent` | implemente sous autre nom | `RunLifecycleEvent` |
| `RunnerHeartbeat` | cible a formaliser | aujourd'hui couvert partiellement par `RuntimeState` + `runtime registry` |
| `ArtifactRef` | implemente sous plusieurs formes | `ArtifactPointer`, `ApiRunArtifact`, `OperatorReplyArtifact` |
| `DocumentRecord` | cible a formaliser | aujourd'hui eparpille entre memory/docs metadata |
| `TaskRecord` | cible a formaliser | backlog encore non fige comme contrat unique |
| `DecisionRecord` | deja implemente | `DecisionRecord` |
| `PreferenceRecord` | cible a ajouter | doctrine deja posee, pas encore classe canonique stabilisee |
| `ApprovalRecord` | deja implemente | `ApprovalRecord` |
| `GitChangeProposal` | cible a ajouter | aujourd'hui rendu par branche / PR / patch dans divers payloads |

## IDs et prefixes recommandes

Les IDs doivent rester textuels, stables et orientables rapidement.

Prefixes recommandes:

- `session_`
- `thread_`
- `msg_`
- `event_`
- `env_`
- `intent_`
- `mission_`
- `chain_`
- `decision_`
- `approval_`
- `artifact_`
- `memory_`
- `pref_`
- `task_`
- `runreq_`
- `run_`
- `review_`
- `dispatch_`
- `ticket_`
- `heartbeat_`
- `gitprop_`

Regle:

- pas d'ID derive d'un chemin fichier ou d'un nom mutable
- un ID est cree une fois, puis reutilise partout

## Liens obligatoires entre objets

### Chaine operateur -> execution

```text
OperatorMessage
  -> ChannelEvent
  -> OperatorEnvelope
  -> MissionIntent
  -> RoutingDecision
  -> MissionRun
  -> RunRequest
  -> RunEvent
  -> ArtifactRef / ActionEvidence / OperatorDelivery
```

### Chaine run code

```text
RunContract
  -> ApiRunRequest
  -> ApiRunResult
  -> ApiRunReview
  -> RunLifecycleEvent
  -> DecisionRecord / ArtifactRef / GitChangeProposal
```

### Chaine memoire

```text
OperatorMessage / RunEvent / ArtifactRef
  -> LearningSignal / CuratorRun / RecallPlan
  -> MemoryRecord / ThoughtMemory / DecisionRecord / PreferenceRecord
```

## Etats minimums a garder stables

### ApprovalRecord

- `pending`
- `approved`
- `rejected`
- `expired`

### MissionRun

- `queued`
- `running`
- `paused`
- `waiting_approval`
- `completed`
- `failed`

### ApiRunResult

- `prepared`
- `awaiting_go`
- `running`
- `clarification_required`
- `completed`
- `failed`
- `paused`
- `stopped`
- `reviewed`

### PreferenceRecord cible

- `proposed`
- `confirmed`
- `active`
- `superseded`
- `rejected`

## Placement physique par famille

| Famille | DB | Object storage | GitHub | Runner local | 8 To |
| --- | --- | --- | --- | --- | --- |
| intents / runs / approvals / decisions | oui | non | non | copie de travail seulement | non |
| docs metadata / retrieval metadata | oui | parfois | parfois | cache local possible | miroir possible |
| artefacts binaires | metadata seulement | oui a terme | parfois si code/doc versionne | temporaire | archive seulement |
| code | refs seulement | non | oui | workspace | miroir possible |
| cold memory / archive | metadata partielle | plus tard | non | non | oui |

Regles:

- la DB garde les pointeurs et les statuts
- `GitHub` garde le code, pas la timeline operateur
- le runner garde du temporaire et du recreable
- le `8 To` garde du froid, pas du vivant canonique

## Contrat OpenClaw dans le modele de donnees

`OpenClaw` s'interface au systeme via des contrats, pas via une base parallele.

Il peut:

- consommer `PreferenceRecord`, `DecisionRecord`, `DocumentRecord`, `MemoryRecord`
- produire ou enrichir `MissionIntent`, `RunRequest`, `RoutingDecisionTrace`, `GitChangeProposal`
- lire `RunnerHeartbeat`, `RuntimeState`, `ApprovalRecord`

Il ne doit pas:

- redefinir `TaskRecord`, `DecisionRecord` ou `ApprovalRecord`
- ecrire une memoire canonique concurrente au control plane
- etre la seule source des etats d'execution

## Regles dures de non-duplication

1. pas de double verite forte entre DB et fichiers locaux
2. pas de metadata critiques uniquement dans des JSON hors DB
3. pas de PR/branche comme substitut a `DecisionRecord`
4. pas de blob prompt comme substitut a `PreferenceRecord`
5. pas de chemin disque comme substitut a `ArtifactRef`
6. pas de session runner comme substitut a l'historique de run

## Definition of done du contrat

Le contrat sera considere verrouille quand:

1. chaque brique majeure du systeme peut pointer vers ce document sans ambiguite
2. le `remote runner contract` reutilise ces noms sans en inventer de concurrents
3. le `control plane contract` reutilise ces noms sans table parallele inutile
4. le `git workflow contract` s'appuie explicitement sur `GitChangeProposal`
5. la `PWA` peut afficher runs, approvals, decisions, preferences, docs et artefacts via ces familles

## References

- `PROJECT_OS_MASTER_MACHINE.md`
- `docs/architecture/MEMORY_STORAGE_AND_OPS_BLUEPRINT.md`
- `docs/architecture/PROJECT_OS_MOTHER_CONTROL_PLANE_ARCHITECTURE.md`
- `docs/roadmap/PROJECT_OS_AUTOPILOT_PACK_PLAN.md`
- `docs/systems/OPENCLAW_UPSTREAM_DOSSIER.md`
- `docs/roadmap/OPENCLAW_REINFORCEMENT_PLAN.md`
- `src/project_os_core/models.py`
- `src/project_os_core/database.py`
- `src/project_os_core/runtime/store.py`
- `src/project_os_core/session/state.py`
