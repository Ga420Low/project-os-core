# Project OS Remote Runner Contract

## Statut

ACTIVE - Pack 0 locked contract

## But

Definir le contrat du `remote runner` minimal always-on pour que `Project OS` reste
utile meme quand le PC local est eteint.

## Role canonique

Le `remote runner` execute les runs standards et urgents:

- code
- shell
- patching
- repo work
- clarifications techniques

Il est la continuite utile du systeme, pas sa verite.

## Position dans la topologie

### V1

Le `remote runner` vit sur le meme noeud OVH que le `control plane`, mais dans un
service separe:

- `project-os-runner-remote`

### V2

Il doit pouvoir etre extrait vers:

- `projectos-runner-01`

Sans casser:

- les noms de contrat
- la timeline
- la `PWA`

## Inputs obligatoires

Le `remote runner` recoit depuis le `control plane`:

1. `RunRequest`
2. `RunContract` si policy requise
3. contexte repo borne
4. approvals deja acquises
5. limites de temps
6. limites reseau
7. secrets scopes

## Outputs obligatoires

Le `remote runner` doit produire:

1. `RunnerHeartbeat`
2. `RunEvent`
3. `ActionEvidence`
4. `ArtifactRef`
5. `GitChangeProposal` si le run touche le code
6. statuts de blocage ou clarification

## Moteur d'execution

Le moteur officiel d'execution est:

- `Codex CLI`

`OpenClaw` peut preparer, router ou enrichir.
Il ne remplace pas l'executor.

## Droits autorises

Le `remote runner` a le droit de:

- cloner un repo dans un workspace jetable
- executer `Codex CLI`
- lancer des commandes shell bornees
- generer patch, branche ou PR
- publier des artefacts et metadata vers le `control plane`

## Interdits

Le `remote runner` ne doit pas:

- ecrire dans le clone humain Windows
- ecrire directement dans `main`
- posseder la DB canonique
- devenir surface operateur primaire
- monter le disque `8 To`
- executer des actions Windows host
- auto-merger des changements critiques

## Workspace policy

Le `remote runner` doit travailler dans:

- un workspace recreable
- un clone Git isole
- un repertoire de travail qui peut etre supprime sans perte de verite

Il ne doit jamais reposer sur:

- un etat mutable non journalise
- un repertoire magique partage avec l'humain

## Git policy

Le `remote runner` rend ses changements sous forme de:

- `GitChangeProposal`
- branche
- patch
- ou PR

Il ne ferme jamais seul la boucle de promotion.

## Secrets policy

Le `remote runner` recoit:

- des secrets scopes au run
- ou des credentials machine strictement necessaires

Il ne recoit pas:

- les secrets globaux Windows
- les secrets perso non necessaires
- les credentials d'admin du `control plane`

## Failure modes

### Heartbeat absent

Effet:

- le `control plane` ne peut plus considerer le runner sain

Reaction:

- marquer `remote runner unavailable`
- stopper les nouveaux dispatch critiques

### Workspace bootstrap KO

Effet:

- impossibilite de demarrer le run

Reaction:

- produire un `RunEvent failed`
- garder la preuve de l'erreur

### Git auth KO

Effet:

- pas de clone/push/PR possible

Reaction:

- run bloque ou degrade en patch exportable

### Artifact upload KO

Effet:

- resultat non promu proprement

Reaction:

- aucune completion canonique mensongere
- evidence locale + etat degrade

## Acceptance checks

Le contrat sera considere respecte quand:

1. PC eteint, un run standard fonctionne encore
2. le runner publie un `RunnerHeartbeat` lisible
3. un patch ou une branche revient via `GitChangeProposal`
4. un timeout ou cancel est visible dans le `control plane`
5. aucune action ne depend du clone humain Windows

## References

- `docs/architecture/PROJECT_OS_CANONICAL_DATA_MODEL_CONTRACT.md`
- `docs/integrations/API_RUN_CONTRACT.md`
- `docs/systems/OPENCLAW_UPSTREAM_DOSSIER.md`
- `docs/roadmap/PROJECT_OS_AUTOPILOT_PACK_PLAN.md`

