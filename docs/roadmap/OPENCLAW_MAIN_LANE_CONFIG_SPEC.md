# OpenClaw Main Lane Config Spec

## Statut

ACTIVE

## But

Figer la configuration attendue de la lane `OpenClaw main` pour le VPS V1 a partir des cles upstream explicitement documentees.

## Source upstream retenue

Les cles suivantes sont explicitement visibles dans la documentation upstream:

- `agents.defaults.workspace`
- `tools.profile`
- `gateway.mode`
- `gateway.port`
- `gateway.bind`
- `gateway.auth.mode`
- `gateway.auth.token`
- `gateway.auth.allowTailscale`
- `gateway.tailscale.mode`
- `logging.redactSensitive`

## Decisions de config lane `main`

### `agents.defaults.workspace`

Valeur retenue:

- `/srv/project-os/data/openclaw/main/workspace`

Pourquoi:

- workspace serveur explicite
- separe de `project-os-core`
- aligne avec notre layout d'etat

### `tools.profile`

Valeur retenue:

- `coding`

Pourquoi:

- conforme au bon default local upstream
- assez puissant pour un vrai substrate utile
- pas aussi ouvert qu'un profil `full`

### `gateway.mode`

Valeur retenue:

- `local`

Pourquoi:

- le noeud OVH porte le gateway localement
- l'acces distant se fait ensuite via surface privee

### `gateway.port`

Valeur retenue:

- `18789`

Pourquoi:

- port officiel attendu upstream
- garde les lanes futures lisibles a `18790+`

### `gateway.bind`

Valeur retenue:

- `lan` pour la lane dockerisee `main`

Pourquoi:

- l'upstream Docker documente qu'un `bind=loopback` dans le conteneur casse l'acces host via le port publie
- la vraie frontiere privee est tenue au niveau host avec `127.0.0.1:18789:18789`
- cela garde une exposition effective privee sans bind public brut

### `gateway.auth.mode`

Valeur retenue:

- `token`

Pourquoi:

- auth explicite
- plus defensable qu'un mode `none`
- alignement avec exposition privee et Control UI distante

### `gateway.auth.token`

Valeur retenue:

- token explicite serveur
- injecte par `OPENCLAW_GATEWAY_TOKEN`
- stocke dans `/srv/project-os/config/env/openclaw/main.env`

Regle:

- pas de token commite
- pas de token laisse implicite
- pas de plaintext token dans `openclaw.json` si l'env serveur suffit

### `gateway.auth.allowTailscale`

Valeur retenue:

- `true` pour la surface privee Tailscale de la lane `main`

Pourquoi:

- permet d'accepter les headers d'identite Tailscale envoyes par le host quand `tailscale serve` proxyfie le gateway
- reste coherent avec notre politique `Tailscale first`

### `gateway.tailscale.mode`

Valeur retenue:

- `off`

Pourquoi:

- `tailscaled` vit sur le host, pas dans le conteneur `OpenClaw`
- la surface privee est geree par `tailscale serve` sur le host
- on evite d'ajouter une dependance runtime inutile dans le conteneur

### `logging.redactSensitive`

Valeur retenue:

- `tools`

Pourquoi:

- upstream recommande cette direction
- meilleur compromis exploitation / hygiene

## Contraintes

1. bind non-prive interdit au niveau host
2. auth `none` interdite
3. `tools.profile=full` interdit pour la lane `main`
4. aucun secret dans le repo
5. `gateway.tailscale.mode=serve` interdit dans le conteneur tant que `tailscaled` reste host-only

## Note d'implementation Docker

La lane `main` est executee en conteneur sur OVH.

Le mode retenu est donc:

- `gateway.bind=lan` dans le conteneur
- port publie uniquement sur `127.0.0.1` cote host
- `tailscale serve` lance sur le host pour le chemin distant prive

La propriete de securite retenue n'est pas "loopback dans le conteneur", mais:

- "surface privee effective au niveau host"

## Outcome attendu

Quand cette spec sera materialisee:

- `openclaw.json` ne sera plus flou
- la lane `main` sera exploitable proprement
- la fondation restera suffisamment solide pour recevoir ensuite la couche entreprise

## Exemple de fichier

- `docs/roadmap/OPENCLAW_MAIN_LANE_ENV_EXAMPLE.env`
- `docs/roadmap/OPENCLAW_MAIN_LANE_OPENCLAW_JSON_EXAMPLE.jsonc`
- `docs/roadmap/OPENCLAW_MAIN_LANE_DOCKER_COMPOSE_EXAMPLE.yml`
