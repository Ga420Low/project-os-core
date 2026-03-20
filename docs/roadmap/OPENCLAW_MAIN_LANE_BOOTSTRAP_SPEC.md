# OpenClaw Main Lane Bootstrap Spec

## Statut

ACTIVE

## But

Transformer la pre-readiness substrate en parametres concrets pour la lane `OpenClaw main` sur le VPS V1.

## Role de la lane `main`

La lane `main` est:

- la lane substrate primaire
- la lane de bootstrap officiel `OpenClaw`
- la lane sur laquelle on valide le runtime propre avant couche entreprise

Ce n'est pas:

- la memoire d'entreprise canonique
- une lane budget
- une lane recovery
- une lane multi-tenant

## Parametres retenus

### Code

- repo: `/srv/project-os/apps/openclaw-upstream`
- remote: `https://github.com/openclaw/openclaw.git`
- version: `v2026.3.13-1`
- commit: `61d171ab0b2fe4abc9afe89c518586274b4b76c2`

### Etat

- `OPENCLAW_STATE_DIR=/srv/project-os/data/openclaw/main`

### Workspace

- workspace lane main:
  - `/srv/project-os/data/openclaw/main/workspace`

### Port

- gateway port principal:
  - `18789`

### Bind

- bind runtime retenu:
  - `lan` dans le conteneur `OpenClaw`
- publication host retenue:
  - `127.0.0.1:18789 -> 18789`

Pourquoi:

- l'upstream Docker documente qu'un `bind=loopback` dans le conteneur casse l'acces host via le port publie
- la vraie frontiere privee doit donc etre tenue au niveau host
- cette combinaison garde une exposition effective privee tout en laissant `Tailscale Serve` proxyfier le host

### Exposition distante

- acces distant prive d'abord
- chemin retenu:
  - `Tailscale Serve` gere par le host
- pas de bind public brut
- pas de `tailscaled` dans le conteneur `OpenClaw`

### Auth gateway

Mode cible retenu:

- `token`

Pourquoi:

- plus propre pour une surface distante privee
- plus defensable qu'un mode sans auth
- compatible avec l'approche `Tailscale + surface privee`

Source retenue:

- `OPENCLAW_GATEWAY_TOKEN` dans `/srv/project-os/config/env/openclaw/main.env`

## Artefacts materialises sur le noeud

Fichiers runtime poses:

- env serveur:
  - `/srv/project-os/config/env/openclaw/main.env`
- config OpenClaw:
  - `/srv/project-os/data/openclaw/main/openclaw.json`
- compose lane `main`:
  - `/srv/project-os/compose/openclaw/main/docker-compose.yml`

Exemples redacts suivis dans le repo canon:

- `docs/roadmap/OPENCLAW_MAIN_LANE_ENV_EXAMPLE.env`
- `docs/roadmap/OPENCLAW_MAIN_LANE_OPENCLAW_JSON_EXAMPLE.jsonc`
- `docs/roadmap/OPENCLAW_MAIN_LANE_DOCKER_COMPOSE_EXAMPLE.yml`

Etat runtime valide:

- image:
  - `ghcr.io/openclaw/openclaw:2026.3.13-1`
- conteneur:
  - `openclaw-main-gateway`
- sante:
  - `healthz` et `readyz` OK

## Fichiers attendus dans la lane `main`

```text
/srv/project-os/data/openclaw/main/
|-- openclaw.json
|-- credentials/
|   `-- oauth.json
|-- agents/
|   `-- main/
|       |-- agent/
|       |   `-- auth-profiles.json
|       `-- sessions/
|-- cron/
|   `-- runs/
`-- workspace/
```

## Valeurs de config obligatoires

Le fichier `openclaw.json` serveur devra refléter explicitement:

1. workspace explicite
2. bind runtime docker `lan`
3. port `18789`
4. auth explicite
5. surface privee d'exposition
6. `gateway.tailscale.mode` desactive dans le conteneur

## Auth et credentials

Regle:

- les credentials OpenClaw runtime vivent dans la lane `main`
- les secrets serveur globaux restent geres hors repo
- les credentials OAuth peuvent etre completes sur une machine avec navigateur puis copies vers la lane serveur si necessaire

## Ce qu'on ne fait pas dans cette spec

1. definir encore la couche `Project OS`
2. definir les approvals
3. definir la memoire entreprise
4. definir des lanes additionnelles

## Readiness mapping

Cette spec doit permettre de cocher ensuite dans la checklist substrate:

- [x] racine d'etat `OpenClaw` dediee definie
- [x] fichier de config serveur `OpenClaw` defini
- [x] bind runtime docker + publication host privee retenus pour le gateway
- [x] auth gateway retenue explicitement
- [x] workspace `OpenClaw` retenu explicitement
- [x] politique d'exposition distante retenue (`Tailscale` host d'abord)

## Outcome attendu

Quand cette spec sera materialisee sur le noeud:

- la lane `main` sera claire
- le bootstrap runtime ne dependra plus d'une convention floue
- on pourra lancer `OpenClaw` sans melanger le substrate et la couche entreprise
