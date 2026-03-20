# Project OS Sprint 1 OpenClaw Substrate Plan

## Statut

IN_PROGRESS - upstream substrate cloned and pinned on OVH

## But

Poser `OpenClaw` proprement sur le noeud OVH sans:

- deployer `project-os-core` tel quel
- melanger runtime upstream et couche entreprise
- recreer une deuxieme verite documentaire ou metier

## Etat de depart confirme

Sur le noeud OVH:

- SSH durci
- `ufw` et `fail2ban` actifs
- Docker actif
- `postgres` et `redis` actifs
- `code-server` actif sur le noeud en acces prive
- racine de travail `Project OS` deja posee dans `/srv/project-os`

Etat substrate execute:

- repo upstream clone dans `/srv/project-os/apps/openclaw-upstream`
- remote confirme: `https://github.com/openclaw/openclaw.git`
- tag pinne: `v2026.3.13-1`
- commit pinne: `61d171ab0b2fe4abc9afe89c518586274b4b76c2`
- dernier commit du tag: `fix(browser): restore batch playwright dispatch`

## Arborescence cible du sprint

```text
/srv/project-os/
|-- apps/
|   |-- openclaw-upstream/
|   `-- project-os-core/
|-- compose/
|-- config/
|-- data/
|-- logs/
`-- backups/
```

## Regle de separation

### `openclaw-upstream`

Role:

- clone runtime upstream
- commit pinne
- reference substrate

Interdit:

- y injecter des couches metier `Project OS`
- y copier des bouts historiques locaux en vrac
- en faire la source de verite produit

### `project-os-core`

Role:

- canon docs
- contrats
- doctrine
- migration map

Interdit:

- le traiter comme la base finale a deployer telle quelle
- le laisser polluer le substrate upstream

## Livrables du sprint

1. dossier `openclaw-upstream` cree sur le noeud
2. clone upstream propre
3. commit exact documente
4. note d'inventaire:
   - version upstream
   - points d'entree runtime
   - prerequis infra
   - surfaces de config
5. validation ecrite:
   - ce qui reste upstream
   - ce qui sera porte plus tard par la couche entreprise

## Sequence d'execution

### Etape 1 - Preparer le dossier

Actions:

1. creer `/srv/project-os/apps/openclaw-upstream`
2. verifier permissions `theo:docker`
3. confirmer que ce dossier reste separe de `project-os-core`

### Etape 2 - Cloner upstream

Actions:

1. cloner le repo upstream `OpenClaw`
2. ne pas forker maintenant
3. verifier la branche et le remote exacts

### Etape 3 - Pinner la version

Actions:

1. relever le commit exact
2. le documenter dans la roadmap
3. interdire mentalement le `tracking flou de main`

Execution confirmee:

- upstream clone sur OVH
- tag stable le plus recent retenu
- HEAD detache volontairement sur le tag pour eviter le drift implicite

### Etape 4 - Inventaire substrate

Actions:

1. identifier le vrai point d'entree runtime
2. identifier la logique de config
3. identifier les deps d'execution
4. identifier les surfaces channel / session / control

### Etape 5 - Health de base

Actions:

1. verifier que le substrate bootstrappe
2. verifier qu'il ne depend pas encore de couches metier `Project OS`
3. documenter les gaps exacts avant `Sprint 2`

## Definition of done

Le sprint est termine si:

1. `OpenClaw` est clone proprement sur OVH
2. son commit est pinne explicitement
3. la separation `upstream runtime` / `project-os-core canon` est visible sur disque
4. un inventaire substrate ecrit existe
5. aucune couche entreprise n'a encore ete injectee dans le coeur upstream

## Selection upstream retenue

Decision:

- base runtime retenue = `openclaw/openclaw`
- mode d'usage = upstream pinne, pas fork actif pour `Sprint 1`

Justification:

- upstream officiel le plus vivant et le mieux maintenu
- releases stables frequentes
- docs officielles et onboarding vivants
- aucune preuve trouvee qu'un fork soit objectivement plus mature pour notre cible sans nous enfermer dans une divergence precoce

## Ce qu'on ne fait pas dans ce sprint

1. bridge `OpenClaw -> Codex CLI`
2. persistence `Project OS DB`
3. `Mission Router`
4. approvals
5. evidence
6. PWA produit

Ces items commencent seulement apres validation du substrate.

## Risque principal

Le vrai risque est conceptuel:

- croire qu'on a "avance vite"
- alors qu'on a seulement reintroduit une base sale et melangee

Ce sprint doit donc privilegier:

- separation
- lisibilite
- pin explicite
- inventaire propre
