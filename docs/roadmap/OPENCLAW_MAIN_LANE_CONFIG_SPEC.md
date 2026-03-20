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
- `gateway.auth.trustedProxy.userHeader`
- `gateway.auth.trustedProxy.requiredHeaders`
- `gateway.auth.trustedProxy.allowUsers`
- `gateway.tailscale.mode`
- `gateway.trustedProxies`
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

- `trusted-proxy`

Pourquoi:

- notre pattern reel est `Docker + host tailscale serve`, pas le mode upstream integre `tailscale serve` dans le meme process
- le flux `allowTailscale` ne supprime pas le collage manuel du token dans cette topologie
- `trusted-proxy` est le mode coherent quand l'identite est delivree par le proxy Tailscale

### `gateway.auth.trustedProxy`

Valeur retenue:

- `userHeader=tailscale-user-login`
- `requiredHeaders=x-forwarded-for,x-forwarded-host,x-forwarded-proto`
- `allowUsers` restreint aux identites operateur du tailnet

Regle:

- l'UI privee quotidienne ne doit pas demander de token a coller a chaque ouverture
- la confiance est delegatee au proxy Tailscale prive
- l'allowlist d'utilisateurs doit rester plus etroite que le tailnet si possible

### `gateway.trustedProxies`

Valeur retenue:

- IP(s) minimales du proxy host vues depuis le conteneur

Pourquoi:

- OpenClaw ne doit accepter les headers d'identite que depuis le proxy effectif
- sur notre noeud Docker actuel, la vue gateway du proxy host passe par l'IP bridge `172.20.0.1`

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
6. collage manuel d'un token dans la Control UI interdit comme UX operateur quotidienne pour la surface Tailscale privee

## Note d'implementation Docker

La lane `main` est executee en conteneur sur OVH.

Le mode retenu est donc:

- `gateway.bind=lan` dans le conteneur
- port publie uniquement sur `127.0.0.1` cote host
- `tailscale serve` lance sur le host pour le chemin distant prive

La propriete de securite retenue n'est pas "loopback dans le conteneur", mais:

- "surface privee effective au niveau host"

La propriete UX retenue n'est pas "plusieurs secrets visibles", mais:

- "une seule auth visible pour l'operateur prive: Tailscale"
- les couches de securite supplementaires reviendront ensuite dans la web app `Project OS`

## Outcome attendu

Quand cette spec sera materialisee:

- `openclaw.json` ne sera plus flou
- la lane `main` sera exploitable proprement
- la fondation restera suffisamment solide pour recevoir ensuite la couche entreprise
- l'operateur n'aura plus a recoller un token manuel pour ouvrir le dashboard prive sur son tailnet

## Exemple de fichier

- `docs/roadmap/OPENCLAW_MAIN_LANE_ENV_EXAMPLE.env`
- `docs/roadmap/OPENCLAW_MAIN_LANE_OPENCLAW_JSON_EXAMPLE.jsonc`
- `docs/roadmap/OPENCLAW_MAIN_LANE_DOCKER_COMPOSE_EXAMPLE.yml`
