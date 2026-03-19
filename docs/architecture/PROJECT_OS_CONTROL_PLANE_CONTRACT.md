# Project OS Control Plane Contract

## Statut

ACTIVE - Pack 0 locked contract

## But

Definir le contrat du `control plane` pour que la maison mere reste:

- toujours utile quand le PC est eteint
- stable meme si un runner tombe
- source canonique de l'etat operateur
- extractible de la V1 mono-noeud OVH vers une V2 split sans rearchitecture produit

## Mantra

- centraliser la verite
- isoler le risque
- rendre chaque action rejouable
- garder Windows ennuyeux et stable
- ne jamais confondre prototype qui marche et systeme tenable

## Role canonique

Le `control plane` est la maison mere distante.

Il porte:

- la `PWA`
- l'API
- l'auth applicative
- la `DB` canonique
- la timeline
- les approvals
- les decisions
- les preferences
- les docs metadata
- les metadata d'artefacts
- le terminal fallback
- l'etat des runners et du `home relay`

Il ne doit pas etre confondu avec:

- le `remote runner`
- le `local runner`
- le `home relay`
- `OpenClaw`
- `Codex CLI`

## Position dans la topologie

### V1

En `V1`, le `control plane` cohabite sur `projectos-core-01` avec:

- `project-os-web`
- `project-os-api`
- `postgres`
- `redis`
- `project-os-runner-remote`

### V2

En `V2`, il reste le meme contrat logique mais peut etre extrait sur:

- `projectos-control-01`

La topologie physique change, pas le contrat produit.

## Inputs obligatoires

Le `control plane` recoit:

1. `OperatorEnvelope`
2. `MissionIntent`
3. `RoutingDecision`
4. `RunRequest`
5. `RunEvent`
6. `ApprovalRecord`
7. `DecisionRecord`
8. `ArtifactRef`
9. `RuntimeState`
10. `RunnerHeartbeat`
11. `ActionEvidence`
12. `GitChangeProposal`

Autres inputs autorises:

- signaux `home relay`
- health snapshots
- login/auth events
- signals de degradation
- metadata documentaires

## Outputs obligatoires

Le `control plane` doit pouvoir produire:

1. surfaces `PWA` lisibles
2. API JSON stables
3. timeline de runs et d'incidents
4. approvals a confirmer
5. decisions et preferences visibles
6. dispatch vers `remote runner` ou `local runner`
7. terminal fallback borne
8. etat degrade clair quand un composant tombe

## Droits autorises

Le `control plane` a le droit de:

- lire et ecrire dans la `Project OS DB`
- router un run vers un runner
- suspendre un run
- annuler un run
- demander une approval
- journaliser un incident
- promouvoir une decision
- promouvoir une preference apres confirmation humaine
- exposer les metadata d'artefacts et de documents

## Interdits

Le `control plane` ne doit pas:

- devenir un shell d'execution forte par defaut
- remplacer le `remote runner`
- remplacer le `local runner`
- posseder la seule copie du code source
- pousser directement dans `main`
- devenir un second cerveau concurrent a `OpenClaw`
- lire ou monter directement le disque `8 To`
- dependre d'une session Windows deja ouverte

## Frontieres avec OpenClaw et Codex CLI

### OpenClaw

`OpenClaw` peut:

- injecter des intents
- enrichir le routage
- lire des objets canoniques du `control plane`

`OpenClaw` ne peut pas:

- posseder la DB canonique
- publier une timeline parallele
- contourner les approvals

### Codex CLI

`Codex CLI` est appele via un runner.

Le `control plane` ne doit pas:

- l'utiliser comme moteur local implicite
- faire croire qu'un chat utile existe si aucun runner n'est disponible

## Degradation attendue

Si un runner tombe, le `control plane` doit rester capable de:

- servir l'UI
- montrer les docs et PDF
- montrer les tasks, decisions et preferences
- montrer l'historique des runs
- expliquer la degradation
- proposer le fallback suivant

## Failure modes

### DB indisponible

Effet:

- la maison mere perd sa verite immediate

Reaction obligatoire:

- bloquer les nouveaux runs
- exposer un incident critique
- garder une page de statut minimale si possible

### Redis / queue indisponible

Effet:

- dispatch et streaming fragilises

Reaction obligatoire:

- degrader proprement le streaming
- ne pas mentir sur l'etat du run

### Remote runner indisponible

Effet:

- plus de continuite utile PC eteint

Reaction obligatoire:

- etat degrade visible
- reroutage local si disponible et pertinent
- pas de faux succes

### Home relay indisponible

Effet:

- perte de reprise locale

Reaction obligatoire:

- le signaler comme indisponible
- ne pas impacter la maison mere

### Cloudflare / DNS indisponible

Effet:

- perte de la surface web publique

Reaction obligatoire:

- acces d'urgence hors app documente
- Tailscale / SSH / KVM comme voies de reprise

## Acceptance checks

Le contrat sera considere respecte quand:

1. le PC est eteint et la `PWA` reste consultable
2. le `control plane` affiche l'etat des runners sans shell manuel
3. un run distant peut etre cree, suivi et annule
4. le terminal fallback existe sans dependre du runner local
5. aucune route critique ne depend d'un terminal Windows ouvert
6. `OpenClaw` et `Codex CLI` ne publient pas de verite concurrente

## References

- `docs/architecture/PROJECT_OS_CANONICAL_DATA_MODEL_CONTRACT.md`
- `docs/architecture/PROJECT_OS_MOTHER_CONTROL_PLANE_ARCHITECTURE.md`
- `docs/roadmap/PROJECT_OS_AUTOPILOT_PACK_PLAN.md`
- `docs/roadmap/PROJECT_OS_V1_BUDGET_OVH_PLAN.md`
- `docs/systems/OPENCLAW_UPSTREAM_DOSSIER.md`

