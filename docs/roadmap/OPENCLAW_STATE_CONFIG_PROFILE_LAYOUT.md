# OpenClaw State Config Profile Layout

## Statut

ACTIVE

## But

Figer la separation serveur des chemins:

- etat
- config
- credentials
- sessions
- workspace
- lanes/profils

Pour que la fondation `OpenClaw` reste propre avant d'ajouter `Project OS`.

## Ce que dit l'upstream

Depuis l'upstream `OpenClaw` observe:

- racine d'etat par defaut: `~/.openclaw`
- config principale: `~/.openclaw/openclaw.json`
- workspace par defaut: `~/.openclaw/workspace`
- credentials OAuth: `~/.openclaw/credentials/oauth.json`
- credentials WhatsApp: `~/.openclaw/credentials/whatsapp/<accountId>/`
- auth profiles agent: `~/.openclaw/agents/<agentId>/agent/auth-profiles.json`
- sessions store: `~/.openclaw/agents/<agentId>/sessions/sessions.json`
- transcripts: `~/.openclaw/agents/<agentId>/sessions/<sessionId>.jsonl`
- logs cron: `~/.openclaw/cron/runs/<jobId>.jsonl`

L'upstream mentionne aussi:

- `OPENCLAW_STATE_DIR` pour deplacer la racine d'etat
- gateway par defaut sur le port `18789`
- bind recommande `loopback`

## Traduction serveur V1 retenue

On ne veut pas dependre de `~/.openclaw` implicitement sur un VPS.

On retient donc une racine explicite:

```text
/srv/project-os/data/openclaw/
```

Et une lane principale:

```text
/srv/project-os/data/openclaw/main/
```

## Layout cible lane `main`

```text
/srv/project-os/data/openclaw/main/
|-- openclaw.json
|-- credentials/
|   |-- oauth.json
|   `-- whatsapp/
|-- agents/
|   `-- main/
|       |-- agent/
|       |   `-- auth-profiles.json
|       `-- sessions/
|           |-- sessions.json
|           `-- *.jsonl
|-- cron/
|   `-- runs/
|-- workspace/
|   |-- AGENTS.md
|   |-- SOUL.md
|   |-- TOOLS.md
|   `-- ...
`-- logs/
```

## Variable de controle

Le substrate serveur devra etre lance avec:

```text
OPENCLAW_STATE_DIR=/srv/project-os/data/openclaw/main
```

## Regle de separation

### Etat runtime OpenClaw

Vit sous:

- `/srv/project-os/data/openclaw/main`

### Config serveur Project OS

Vit sous:

- `/srv/project-os/config/env`

### Canon docs / contrats / migration

Vit dans:

- `/srv/project-os/apps/project-os-core`

### Code upstream

Vit dans:

- `/srv/project-os/apps/openclaw-upstream`

## Lanes futures

Si une lane additionnelle apparait plus tard, elle obtient sa propre racine:

```text
/srv/project-os/data/openclaw/<lane-name>/
```

Exemples:

- `/srv/project-os/data/openclaw/main`
- `/srv/project-os/data/openclaw/budget`
- `/srv/project-os/data/openclaw/recovery`

Chaque lane devra avoir:

1. sa config
2. son port si un gateway distinct existe
3. son workspace si necessaire
4. ses logs
5. son etat de sessions

## Ports proposes

Lane principale:

- `18789`

Lanes additionnelles:

- `18790+`

Regle:

- pas de collision
- pas de bind externe brut
- exposition distante seulement via surface privee

## Ce qu'on ne fait pas

1. utiliser `~/.openclaw` comme convention floue de prod sans l'encadrer
2. melanger l'etat `OpenClaw` et l'etat `Project OS`
3. partager un meme dossier d'etat entre plusieurs lanes
4. traiter la lane `main` comme memoire d'entreprise canonique

## Decision

Pour le VPS V1:

- `openclaw-upstream` reste le code
- `/srv/project-os/data/openclaw/main` devient la racine d'etat runtime cible
- `Project OS` gardera sa propre verite operatoire au-dessus

## Materialisation serveur

Le layout de base a deja ete cree sur le noeud pour la lane `main`:

- `/srv/project-os/data/openclaw/main/...`
- `/srv/project-os/logs/openclaw/main`
- `/srv/project-os/config/env/openclaw`
