# Project OS V1 OpenClaw Enterprise Execution Plan

## Statut

ACTIVE - Immediate execution plan for the `OpenClaw + couche entreprise` rebuild

## But

Traduire la roadmap de reconstruction en ordre d'execution concret, court et defensable.

## Hypothese de depart

Ce plan suppose:

- `OpenClaw` = fondation runtime
- `Codex CLI` = executor officiel
- `Project OS` = couche entreprise
- `project-os-core` = canon docs, contrats et migration
- `OVH VPS-3` = noeud V1 actif

## Etat deja acquis

- noeud OVH provisionne
- SSH durci
- `ufw` et `fail2ban` actifs
- Docker actif
- `postgres` et `redis` poses sur le noeud
- arborescence `/srv/project-os` posee
- doctrine `OpenClaw foundation + notre entreprise` publiee

## Regle de travail

1. on ne deploye pas `project-os-core` tel quel comme base finale
2. on ne salit pas `OpenClaw` upstream avec des couches metier en vrac
3. on pose d'abord le substrate
4. on remonte ensuite la couche entreprise par adapters et contrats

## Sprint 1 - Substrate propre

Objectif:

- poser `OpenClaw` proprement sur le noeud OVH

Actions:

1. cloner `OpenClaw` upstream dans un dossier dedie
2. pinner un commit upstream explicite
3. documenter la version retenue
4. verifier que le runtime bootstrappe sans couche metier parasite
5. conserver `project-os-core` comme repo canonique de migration, pas comme base runtime finale

Done quand:

- `OpenClaw` tourne proprement sur OVH
- la version upstream retenue est documentee
- aucune confusion repo/runtime n'existe

## Sprint 2 - Contrats entreprise minimaux

Objectif:

- brancher la verite `Project OS` au-dessus du substrate

Actions:

1. poser les modeles minimaux:
   - `RunRequest`
   - `RunEvent`
   - `DecisionRecord`
   - `PreferenceRecord`
   - `ApprovalRecord`
2. brancher la persistence sur `Project OS DB`
3. prouver qu'une action runtime se traduit en ecriture canonique
4. verifier qu'`OpenClaw` n'introduit pas de verite concurrente

Done quand:

- une action runtime produit une trace canonique `Project OS`
- la frontiere `OpenClaw runtime / Project OS truth` est testable

## Sprint 3 - Bridge d'execution

Objectif:

- faire de `Codex CLI` l'executor reel de la nouvelle base

Actions:

1. poser le bridge `OpenClaw -> Codex CLI`
2. definir les workspaces Git isoles
3. produire les sorties standard:
   - `patch`
   - `branch`
   - `PR proposal`
4. verifier qu'aucun run ne touche le clone humain

Done quand:

- un run code passe par la nouvelle base et sort un resultat versionnable

## Sprint 4 - Couches coeur entreprise

Objectif:

- remonter les briques differentiantes `Project OS`

Actions:

1. `Mission Router` policy-aware
2. `approval engine`
3. `evidence pipeline`
4. `research / deep research`
5. `docs metadata / timeline / run inspector`

Done quand:

- les decisions, approvals et preuves vivent dans la couche entreprise
- le transport live ne devient pas la verite

## Ordre exact recommande maintenant

1. cloner `OpenClaw` upstream sur OVH
2. pinner le commit
3. documenter l'inventaire runtime upstream
4. brancher les contrats minimaux `Project OS`
5. poser le bridge `OpenClaw -> Codex CLI`
6. remonter `Mission Router`
7. remonter approvals et evidence

## Ce qu'on ne fait pas maintenant

1. gros fork massif `OpenClaw`
2. copie brute de bouts historiques `project-os-core` dans le substrate
3. redeployer mentalement le vieux runtime local comme V1
4. traiter la memoire OpenClaw comme memoire d'entreprise suffisante

## Point de verification a chaque sprint

Toujours verifier:

- qui porte la verite
- qui porte le transport
- qui porte l'execution
- qui porte la memoire d'entreprise

Si ces 4 reponses se melangent, le sprint n'est pas propre.
