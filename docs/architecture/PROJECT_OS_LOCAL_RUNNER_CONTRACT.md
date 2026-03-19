# Project OS Local Runner Contract

## Statut

ACTIVE - Pack 0 locked contract

## But

Definir le contrat du `local runner` pour exploiter la puissance du PC sans exposer
Windows comme sandbox autonome directe.

## Role canonique

Le `local runner` est une `VM Linux` sur le PC.

Il sert a:

- jobs lourds
- builds
- tests volumineux
- lanes data-local
- futures lanes media / GPU

Il est un accelerateur, pas la base unique du systeme.

## Inputs obligatoires

Le `local runner` recoit:

1. `RunRequest`
2. contexte repo borne
3. approvals deja acquises
4. policy de mounts
5. limites de temps et de ressources
6. consignes d'upload d'artefacts

## Outputs obligatoires

Le `local runner` doit produire:

1. `RunnerHeartbeat`
2. `RunEvent`
3. `ArtifactRef`
4. `ActionEvidence`
5. `GitChangeProposal` si code modifie

## Droits autorises

Le `local runner` a le droit de:

- utiliser CPU/RAM locaux
- utiliser les workspaces jetables
- lire certaines zones du `8 To`
- ecrire dans ses zones `workspace/` et `artifacts/`
- uploader ses preuves vers le `control plane`

## Policy de mounts

Zones autorisees:

- `memory-code/` = `RO`
- `datasets/` = `RO`
- `archives/` = `RO`
- `exports/` = promotion explicite
- `workspace/` = `RW`
- `artifacts/` = `RW`

## Interdits

Le `local runner` ne doit pas:

- executer sur l'OS Windows host
- obtenir un shell direct Windows
- avoir `RW` global sur le `8 To`
- recevoir les secrets globaux Windows
- devenir la seule source de verite des artefacts
- contourner le `control plane`

## Frontiere Windows

Regle dure:

- `Windows host` = atelier humain
- `local runner` = execution autonome isolee

Les agents peuvent consommer la puissance du PC.
Ils ne doivent pas habiter Windows lui-meme.

## OpenClaw et Codex CLI

Le `local runner` peut heberger:

- `OpenClaw`
- `Codex CLI`

Mais:

- `OpenClaw` ne devient pas la verite du projet
- `Codex CLI` ne doit pas ecrire hors du workspace scope

## Failure modes

### VM locale down

Effet:

- perte de la lane locale

Reaction:

- `control plane` degrade
- reroutage distant si possible

### Mount interdit ou absent

Effet:

- le run local ne peut pas continuer proprement

Reaction:

- blocage clair
- pas de fallback RW sauvage

### Hyperviseur KO

Effet:

- plus de runner local

Reaction:

- signal au `home relay`
- etat degrade visible dans la `PWA`

## Acceptance checks

Le contrat sera considere respecte quand:

1. aucun run agent n'execute directement sur Windows
2. les mounts du `8 To` sont scopes et audites
3. les artefacts remontent dans la maison mere
4. casser un workspace local ne casse pas Windows
5. le `control plane` peut tuer ou declarer indisponible le runner local

## References

- `docs/architecture/HOST_WINDOWS_VM_LINUX_MATRIX.md`
- `docs/architecture/PROJECT_OS_CANONICAL_DATA_MODEL_CONTRACT.md`
- `docs/roadmap/PROJECT_OS_AUTOPILOT_PACK_PLAN.md`
- `docs/roadmap/OPENCLAW_REINFORCEMENT_PLAN.md`

