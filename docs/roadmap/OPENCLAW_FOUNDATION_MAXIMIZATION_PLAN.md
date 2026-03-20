# OpenClaw Foundation Maximization Plan

## Statut

ACTIVE

## But

Finir la fondation `OpenClaw` au maximum avant d'ajouter:

- la verite metier `Project OS`
- la memoire d'entreprise
- les policies entreprise
- les surfaces operateur produit

## Principe

On prend maintenant:

- ce qui renforce le substrate
- ce qui renforce les playbooks ops
- ce qui renforce la lisibilite runtime
- ce qui renforce le deploiement propre

On ne prend pas maintenant:

- ce qui change la philosophie du runtime
- ce qui cree une seconde verite memoire
- ce qui injecte deja notre couche metier
- ce qui nous enferme dans un fork trop tot

## Adoption matrix

### `openclaw/openclaw`

Statut:

- `ADOPT NOW`

Role:

- base runtime officielle
- onboarding
- canaux
- control plane upstream
- docs et lifecycle officiels

### `digitalknk/openclaw-runbook`

Statut:

- `ADOPT NOW AS REFERENCE`

Ce qu'on prend:

- patterns de hardening
- patterns de cout/guardrails
- patterns d'exploitation boring et stables
- runbook de survie et d'operations

Ce qu'on ne prend pas:

- aucune verite produit
- aucune memoire canonique
- aucune structure metier

### `essamamdani/openclaw-coolify`

Statut:

- `ADOPT PARTIALLY`

Ce qu'on prend:

- idees de packaging
- logique de bootstrap dashboard + tunnel
- simplifications de deploiement

Ce qu'on ne prend pas:

- la stack Coolify elle-meme
- les choix de plateforme qui ne servent pas notre VPS Docker actuel

### `remoteclaw/remoteclaw`

Statut:

- `DEFER / MINE FOR IDEAS`

Ce qu'on garde en tete:

- bridge vers agents CLI
- sessions persistantes
- cron
- MCP tools
- reach multi-canaux

Pourquoi on ne l'adopte pas maintenant:

- remplace deja une partie du coeur plateforme
- peut brouiller notre frontiere `OpenClaw foundation / Project OS enterprise layer`
- licence plus engageante

### `sunkencity999/localclaw`

Statut:

- `ADOPT PARTIALLY FOR FOUNDATION`

Ce qu'on prend:

- separation d'etat
- separation de config
- separation de profils
- separation de port / coexistence
- patterns local-model-first comme lane specialisee possible

Ce qu'on ne prend pas:

- le fork comme base runtime
- une reorientation totale de la V1 vers modeles locaux

Pourquoi:

- tres bonne source d'idees pour garder une fondation propre et isolee
- utile sans casser l'upstream

### `jomafilms/openclaw-multitenant`

Statut:

- `REJECT FOR V1`

Pourquoi:

- multi-tenant hors cible
- isolation/vaults/team sharing prematures
- risque de sur-architecturer la fondation perso / operateur

### `supermemory` satellites

Statut:

- `DO NOT ADOPT NOW`

Pourquoi:

- risquent de brouiller la memoire canonique `Project OS`
- interessants plus tard pour retrieval/compaction, pas pour la fondation V1

## Travail concret autorise maintenant

1. stabiliser l'upstream officiel sur OVH
2. inventorier le substrate reel
3. extraire des runbooks ops ce qui durcit l'exploitation
4. extraire des patterns de deploiement ce qui simplifie le bootstrap
5. extraire de `localclaw` les patterns d'isolation propres
6. documenter les gaps avant couche entreprise

## Travail interdit maintenant

1. forker `OpenClaw` pour y recoller `Project OS`
2. injecter la memoire entreprise dans le coeur upstream
3. copier des bouts historiques locaux en vrac
4. traiter un satellite comme nouvelle base

## Outcome attendu

A la fin de cette phase:

- la fondation `OpenClaw` est la plus propre et la plus solide possible
- l'ops du noeud OVH est lisible
- les references utiles sont triees
- la couche entreprise peut ensuite etre ajoutee proprement au-dessus

## Reference de mise en oeuvre

- `docs/roadmap/OPENCLAW_FOUNDATION_ADOPT_NOW_CHECKLIST.md`
- `docs/roadmap/OPENCLAW_V1_SERVER_RUNBOOK.md`
