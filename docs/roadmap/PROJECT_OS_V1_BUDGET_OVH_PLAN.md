# Project OS V1 Budget OVH Plan

## Statut

ACTIVE - Canonical V1 implementation path under budget ceiling

## But

Documenter la V1 canonique testable de `Project OS` avec un plafond cible de
`30 EUR/mo HT`, sans casser la trajectoire scalable du systeme.

La regle de lecture est simple:

- `V1` = budget, operable, extractible
- `V2` = separation plus robuste, pas immediate

## Mantra

- centraliser la verite
- isoler le risque
- rendre chaque action rejouable
- garder Windows ennuyeux et stable
- ne jamais confondre prototype qui marche et systeme tenable

## Decision canonique V1

La V1 retenue est:

1. `un seul noeud distant OVH`
2. `Cloudflare Tunnel`
3. `Tailscale`
4. `GitHub private repo`
5. `home relay local always-on`
6. `runner local Linux sur le PC`

Le noeud distant unique porte en V1:

- `project-os-web`
- `project-os-api`
- `postgres`
- `redis`
- `project-os-runner-remote`

## Pourquoi la V1 mono-noeud est acceptable

Elle est acceptable si et seulement si les frontieres logiques sont deja
respectees.

La V1 n'est donc pas:

- une grosse application spaghetti
- un runner qui connait des chemins magiques partout
- une rustine avant un refacto inevitable

## Ce que la V1 doit deja garantir

PC eteint, `Project OS` doit garder:

- la web app
- le login
- les docs, PDF, notes et historique
- les tasks, decisions, preferences et runs
- un chat utile
- un terminal fallback

PC allume, `Project OS` gagne:

- la puissance du runner local
- les jobs lourds
- l'acces controle au `8 To`

## Budget V1 vise

### Compute principal

Plan retenu:

- `OVH VPS-3`
- reference officielle: [OVHcloud VPS](https://www.ovhcloud.com/en/vps/)

### Discipline budget

En V1:

- pas d'object storage externe obligatoire
- pas de second noeud distant obligatoire
- pas de DB separee obligatoire

## Ce qui est explicitement reporte en V2

### V2 robuste suspendue

Les points suivants sont reportes et ne font pas partie de la V1 canonique:

1. extraire `projectos-control-01` hors du noeud unique
2. extraire `projectos-runner-01` hors du noeud unique
3. sortir les artefacts vivants vers `object storage`
4. separer plus fortement `control plane`, `remote runner` et `data plane`
5. durcir les backups et restores avec drills plus lourds

## Regles dures de compatibilite V1 -> V2

Pour eviter le gros refacto plus tard, la V1 doit deja respecter:

1. contrats runner explicites
2. metadata en DB, pas dans des chemins magiques
3. workspaces Git isoles
4. retour agent via branche, PR ou patch
5. terminal fallback non lie au runner local
6. services separes en `Docker Compose`

## Runway OVH a garder en tete

`OVHcloud` peut absorber beaucoup plus que le simple `VPS-3`.

Pour la suite, voir:

- `docs/roadmap/OVH_SERVICE_RUNWAY_MATRIX.md`

Ce point est important pour `Project OS`:

- on ne choisit pas OVH seulement pour le prix
- on le choisit aussi parce qu'il peut absorber plus tard:
  - `Object Storage`
  - `Cold Archive`
  - `OpenSearch`
  - `AI Endpoints`
  - `speech/audio`
  - briques IA plus lourdes

## Phrase de reference

`La V1 canonique de Project OS est un mono-noeud distant OVH propre, complete par un home relay et un runner local. La V2 robuste separera ensuite control plane, remote runner et stockage externe sans changer les contrats du systeme.`
