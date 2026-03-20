# Project OS V1 OpenClaw Enterprise Rebuild Roadmap

## Statut

ACTIVE - Canonical rebuild roadmap for the `OpenClaw + notre entreprise` V1

## But

Construire la vraie `V1` visee comme:

- une fondation runtime `OpenClaw`
- un executor officiel `Codex CLI`
- une couche entreprise `Project OS`

Le but n'est pas de pousser tout l'ancien projet dans le VPS.
Le but est de reconstruire une base plus propre en reprenant seulement ce qui merite
d'etre reconstitue au-dessus d'une fondation plus saine.

Lecture execution immediate:

- `docs/roadmap/PROJECT_OS_V1_OPENCLAW_ENTERPRISE_EXECUTION_PLAN.md`

## Phrase de reference

`La V1 de reconstruction retenue est: OpenClaw comme fondation runtime, Codex CLI comme moteur d'execution, et Project OS comme couche entreprise qui remonte progressivement docs, memoire, policies, audit, approvals, routing et surfaces operateur.`

## Regles dures

1. `OpenClaw` reste le plus upstream possible
2. pas de fork massif au debut
3. pas de gros merge sale de `project-os-core` dans `OpenClaw`
4. les briques utiles sont reconstituees au-dessus de la fondation via `contrats -> adapters -> wrappers -> policies -> UI`
5. `project-os-core` reste la source canonique de doctrine, contrats, migration et couches metier a reprendre
6. l'humain garde le dernier mot sur les changements critiques

## Ce qu'on garde comme fondation

### OpenClaw

On garde d'`OpenClaw`:

- la boucle autonome
- les primitives de controle
- la discipline de session
- le runtime substrate
- les surfaces channel quand elles sont pertinentes
- la logique de rigueur upstream

Ce qu'`OpenClaw` apporte aussi a la memoire:

- meilleure continuite de session
- meilleure hygiene de contexte
- compaction plus saine
- primitives runtime plus solides pour porter de la memoire de travail

Ce qu'`OpenClaw` n'apporte pas a lui seul:

- la memoire canonique d'entreprise
- le registre fondateur
- la memoire produit profonde
- la gouvernance preferences / decisions / evidence

### Codex CLI

On garde de `Codex CLI`:

- codegen
- shell
- patching
- repo work
- file ops
- execution forte pour les runs code

### OVH node V1

On garde comme socle V1:

- `OVH VPS-3`
- `postgres`
- `redis`
- `runner distant minimal`
- `control plane` naissant
- `Cloudflare Tunnel`
- `Tailscale`

## Ce qu'on reprend depuis `project-os-core`

On ne reprend pas tout.

On reprend prioritairement:

1. les contrats canoniques
2. la doctrine de verite
3. la memoire produit
4. les policies
5. les flows operateur
6. les conventions de preview/git/approval
7. les modeles de donnees utiles
8. les composants metier qui rentrent proprement dans la nouvelle base

## Ce qu'on ne reprend pas tel quel

1. les couches historiques trop locales
2. les bouts de runtime qui contredisent la nouvelle topologie
3. les wrappers temporaires sales
4. les surfaces qui recreent une deuxieme verite
5. les integrations qui ne s'ancrent pas proprement sur `OpenClaw` ou le `control plane`

## Topologie de repos recommandee

### A. `openclaw-upstream`

Role:

- clone propre
- commit pinne
- reference runtime

### B. `project-os-core`

Role:

- canon docs
- contrats
- doctrine
- migration map
- backlog de reimplementation

### C. `project-os-platform`

Role:

- vraie reconstruction produit
- control plane
- adapters `OpenClaw -> Codex CLI`
- data model
- PWA
- memory layer
- approvals
- audit
- routing

## Packs de reconstruction

### Pack A - Foundation Freeze

Objectif:

- figer la forme `OpenClaw foundation + Project OS enterprise layer`

Livrables:

- doctrine ecrite
- frontieres repo ecrites
- liste `KEEP / REBUILD / REJECT`

Gate:

- plus aucune ambiguite sur le fait que `project-os-core` n'est pas la base finale a deployer telle quelle

Execution immediate:

1. figer `OpenClaw` comme fondation V1 dans les docs canoniques
2. figer `project-os-core` comme repo canonique de migration
3. lister les briques `KEEP / REBUILD / REJECT`
4. decider si le futur repo produit s'appelle `project-os-platform` ou autre nom final

### Pack B - Upstream Runtime Base

Objectif:

- poser `OpenClaw` proprement sur le noeud OVH

Livrables:

- clone upstream propre
- commit pinne
- bootstrap runtime
- health checks de base

Gate:

- `OpenClaw` tourne proprement sans modifications metier parasites

Execution immediate:

1. cloner `OpenClaw` proprement sur le noeud OVH
2. pinner un commit upstream
3. verifier le bootstrap runtime et les checks de base
4. documenter la version exact du substrate retenu

### Pack C - Enterprise Contracts Layer

Objectif:

- brancher la couche canonique `Project OS` sur la fondation

Livrables:

- modeles `RunRequest`, `RunEvent`, `PreferenceRecord`, `DecisionRecord`, `ApprovalRecord`
- adapters de lecture/ecriture
- persistence canonique dans `Project OS DB`

Gate:

- `OpenClaw` n'invente pas sa propre verite concurrente

Execution immediate:

1. brancher la persistance `Project OS DB`
2. brancher les objets canoniques prioritaires
3. prouver qu'une action runtime `OpenClaw` peut se traduire dans les contrats `Project OS`

### Pack D - Execution Bridge

Objectif:

- faire de `Codex CLI` l'executor officiel au-dessus de la fondation

Livrables:

- bridge `OpenClaw -> Codex CLI`
- workspaces Git isoles
- retour `patch / branch / PR`

Gate:

- un run code se lance depuis la nouvelle base sans toucher le clone humain

### Pack E - Mother Control Plane

Objectif:

- faire monter la maison mere produit

Livrables:

- API
- PWA
- auth
- timeline
- docs metadata
- tasks
- decisions
- preferences
- run inspector

Gate:

- la web app devient une vraie surface operateur, pas une facade vide

### Pack F - Enterprise Memory And Policies

Objectif:

- remonter ce qui fait "notre entreprise"

Livrables:

- registre de preferences fondateur
- decision log
- policies d'approvals
- evidence model
- audit trail

Gate:

- les preferences et decisions ne vivent plus dans des prompts flous

### Pack G - Controlled Migration Of Useful Capabilities

Objectif:

- reconstituer les petits bouts utiles de l'ancien projet

Livrables:

- tableau `capability -> source -> target -> strategy`
- reimplementations propres des capacites utiles
- rejet explicite des couches inutiles

Gate:

- chaque capacite reprise a un point d'ancrage clair et ne salit pas la fondation

## Test de discipline

La reconstruction est consideree saine si:

1. `OpenClaw` peut etre mis a jour sans explosion immediate
2. la couche entreprise `Project OS` reste lisible et separee
3. aucun morceau repris de l'ancien projet n'introduit une deuxieme verite
4. les briques reconstituees sont plus propres que leur equivalent historique

## Decision memoire

La memoire V1 la plus puissante n'est pas:

- `OpenClaw seul`
- ni `project-os-core` deploye brut

La memoire V1 la plus puissante visee est:

- `OpenClaw` pour la discipline runtime
- `Project OS` pour la memoire d'entreprise
- `Codex CLI` pour l'execution outillee qui nourrit cette memoire proprement

Donc la V1 de reconstruction doit explicitement chercher:

1. une meilleure fondation agentique
2. une meilleure memoire canonique
3. une meilleure remontée des preuves et decisions

## References

- `PROJECT_OS_MASTER_MACHINE.md`
- `docs/architecture/PROJECT_OS_ARCHITECTURE_DECISION_MATRIX.md`
- `docs/roadmap/OPENCLAW_REINFORCEMENT_PLAN.md`
- `docs/systems/OPENCLAW_UPSTREAM_DOSSIER.md`
- `docs/roadmap/PROJECT_OS_AUTOPILOT_ROADMAP.md`
