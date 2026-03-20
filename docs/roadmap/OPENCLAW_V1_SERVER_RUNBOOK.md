# OpenClaw V1 Server Runbook

## Statut

ACTIVE - runbook operable pour la fondation `OpenClaw` sur le noeud OVH V1

## But

Donner un runbook court, concret et lisible pour exploiter la fondation `OpenClaw` sur le VPS V1 sans:

- deployer trop tot la couche entreprise
- perdre la separation entre code, etat, config et surfaces admin
- ouvrir des acces inutiles

## Perimetre

Ce runbook couvre:

1. le noeud OVH V1
2. l'upstream `OpenClaw` clone et pinne
3. les services d'infra deja poses
4. les surfaces admin privees
5. les guardrails obligatoires a respecter

Ce runbook ne couvre pas encore:

1. le bridge `OpenClaw -> Codex CLI`
2. la verite entreprise `Project OS`
3. les approvals
4. l'evidence pipeline
5. la PWA produit finale

## Etat reel du noeud au moment du runbook

Noeud:

- provider: `OVH VPS-3`
- OS: `Ubuntu 24.04`
- acces admin: `theo` par cle SSH
- acces public SSH par mot de passe: coupe
- hardening de fondation: `ufw` + `fail2ban`

Services deja poses:

- `postgres`
- `redis`
- `code-server`
- `tailscale`

Substrate upstream:

- repo: `openclaw/openclaw`
- clone: `/srv/project-os/apps/openclaw-upstream`
- tag retenu: `v2026.3.13-1`
- commit retenu: `61d171ab0b2fe4abc9afe89c518586274b4b76c2`

Canon documentaire:

- repo canon: `/srv/project-os/apps/project-os-core`

## Layout serveur retenu

```text
/srv/project-os/
|-- apps/
|   |-- openclaw-upstream/
|   `-- project-os-core/
|-- compose/
|   |-- base/
|   `-- tools/
|-- config/
|   `-- env/
|-- data/
|   |-- postgres/
|   |-- redis/
|   `-- code-server/
|-- logs/
|   |-- control-plane/
|   |-- runner/
|   `-- code-server/
`-- backups/
```

## Regle de separation

### Code

- `openclaw-upstream` = fondation runtime officielle
- `project-os-core` = canon docs / contrats / migration

Interdit:

- injecter la couche entreprise dans le repo upstream pendant la phase fondation
- traiter `project-os-core` comme le runtime V1 final tel quel

### Etat

Etat present:

- `postgres` -> `/srv/project-os/data/postgres`
- `redis` -> `/srv/project-os/data/redis`
- `code-server` -> `/srv/project-os/data/code-server`

Etat cible a tenir pour OpenClaw:

- racine d'etat par role
- pas d'etat melange entre substrate et couche entreprise
- futur etat `OpenClaw` a isoler dans une racine dediee, par exemple:
  - `/srv/project-os/data/openclaw/main`
  - puis plus tard des lanes/profils separes si necessaire

### Config

Config serveur:

- sous `/srv/project-os/config/env`

Regle:

- une config par surface
- pas de secrets commites
- pas de config locale Windows consideree comme verite serveur

## Ports utilises et reserves

Ports actifs maintenant:

- `5432` -> `postgres`, bind local `127.0.0.1`
- `6379` -> `redis`, bind local `127.0.0.1`
- `8443` -> `code-server`, bind local `127.0.0.1`

Ports de substrate a reserver mentalement:

- `18789` -> `OpenClaw` main lane attendue
- `18790+` -> lanes/profils additionnels si un besoin apparait

Regle:

- bind local uniquement quand possible
- exposition externe seulement via surface privee (`Tailscale`, tunnel prive)

## Surfaces admin privees

### SSH

Mode retenu:

- user `theo`
- cle SSH
- acces public durci

### `code-server`

Role:

- mini OS operateur
- lecture fichiers
- edition
- terminal
- visibilite sur `/srv/project-os`

Acces:

- prive via `Tailscale`
- URL Tailscale du noeud

### Tailscale

Role:

- surface privee principale d'acces mobile et desktop
- pas de dependance immediate a une exposition publique

Regle:

- on privilegie le prive
- on n'ouvre pas de surface admin brute sur Internet pour "aller plus vite"

## Guardrails `runbook` adoptes maintenant

### Hardening obligatoire

Doit rester vrai:

1. `ufw` actif
2. `fail2ban` actif
3. `PasswordAuthentication no`
4. `PermitRootLogin no`
5. acces admin seulement par cle + user explicite

### Readiness boring

Chaque service doit pouvoir etre relu rapidement par:

1. `docker ps`
2. `docker compose ps`
3. `docker compose logs --tail=50`
4. `systemctl status <service>`

### Recovery boring

Avant toute grosse modif infra:

1. savoir quel compose est touche
2. savoir quel volume data est implique
3. savoir comment revenir a l'etat precedent

### Surface privee avant surface publique

Ordre retenu:

1. SSH durci
2. Tailscale
3. surface admin privee
4. seulement ensuite eventuelle exposition publique applicative

## Patterns `coolify` adoptes maintenant

On reprend:

1. bootstrap simple
2. checks de readiness lisibles
3. URL admin privee facile a ouvrir
4. chemin de deploiement lisible service par service

On ne reprend pas:

1. Coolify comme plateforme
2. la logique "panel d'abord"

## Patterns `localclaw` adoptes maintenant

On reprend:

1. separation d'etat
2. separation de config
3. separation de profils
4. separation de ports
5. coexistence propre entre lanes

Traduction pour nous:

- `OpenClaw` main lane doit vivre separement
- si une lane additionnelle apparait plus tard, elle obtient:
  - sa config
  - son port
  - son etat
  - ses logs

## Cost and quota guardrails

La fondation V1 doit rester sobre.

Regles:

1. pas de multiplication de surfaces runtime sans besoin reel
2. pas de workers/forks/lanes experimentales permanentes sans justification
3. les modes de run doivent rester lisibles:
   - `normal`
   - `budget`
   - `recovery`
4. les futures integrations modele devront exposer:
   - le provider actif
   - le mode actif
   - le cout ou budget si disponible

## Checklist operateur de base

### Debut de session

1. verifier `docker ps`
2. verifier acces `code-server`
3. verifier `tailscale status`
4. verifier l'etat du substrate upstream clone

### Avant modif substrate

1. verifier le tag/commit upstream actif
2. verifier les services dependants
3. verifier les volumes data touches
4. confirmer qu'on ne melange pas encore la couche entreprise

### Apres modif substrate

1. relire les logs
2. relire la readiness
3. confirmer que l'acces prive reste OK
4. documenter ce qui a change

## Commandes utiles

```bash
# docker
docker ps
docker compose -f /srv/project-os/compose/base/docker-compose.yml ps

# logs
docker compose -f /srv/project-os/compose/base/docker-compose.yml logs --tail=50

# firewall
sudo ufw status

# fail2ban
sudo systemctl status fail2ban --no-pager

# tailscale
tailscale status
tailscale ip -4

# code-server
docker logs --tail=50 project-os-code-server

# upstream pin
cd /srv/project-os/apps/openclaw-upstream
git rev-parse HEAD
git describe --tags --exact-match
```

## Definition of done de la phase fondation

La phase fondation est acceptable si:

1. l'upstream officiel est clone et pinne
2. les services de base sont lisibles et prives
3. la separation code / etat / config / admin est maintenue
4. les patterns critiques de `runbook`, `coolify` et `localclaw` sont internalises dans nos propres docs
5. on peut ensuite attaquer la couche entreprise sans reouvrir l'architecture de base

## Docs de support

- `docs/roadmap/OPENCLAW_SUBSTRATE_READINESS_CHECKLIST.md`
- `docs/roadmap/OPENCLAW_STATE_CONFIG_PROFILE_LAYOUT.md`
- `docs/roadmap/OPENCLAW_MAIN_LANE_CONFIG_SPEC.md`
