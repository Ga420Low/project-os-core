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

- `loopback`

Pourquoi:

- conforme a notre politique d'exposition privee
- compatible avec `Tailscale Serve`
- evite un bind public brut

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
- genere et stocke hors repo source

Regle:

- pas de token commite
- pas de token laisse implicite

### `gateway.auth.allowTailscale`

Valeur retenue:

- `true` pour la surface privee Tailscale de la lane `main`

Pourquoi:

- fluidifie l'acces prive au dashboard et aux surfaces web
- reste coherent avec notre politique `Tailscale first`

### `gateway.tailscale.mode`

Valeur retenue:

- `serve`

Pourquoi:

- exposition privee propre
- pas besoin de bind public

### `logging.redactSensitive`

Valeur retenue:

- `tools`

Pourquoi:

- upstream recommande cette direction
- meilleur compromis exploitation / hygiene

## Contraintes

1. non-loopback interdit tant qu'une raison forte n'existe pas
2. auth `none` interdite
3. `tools.profile=full` interdit pour la lane `main`
4. aucun secret dans le repo

## Outcome attendu

Quand cette spec sera materialisee:

- `openclaw.json` ne sera plus flou
- la lane `main` sera exploitable proprement
- la fondation restera suffisamment solide pour recevoir ensuite la couche entreprise

## Exemple de fichier

- `docs/roadmap/OPENCLAW_MAIN_LANE_OPENCLAW_JSON_EXAMPLE.jsonc`
