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

- bind retenu:
  - `loopback`

### Exposition distante

- acces distant prive d'abord
- chemin retenu:
  - `Tailscale`
- pas de bind public brut

### Auth gateway

Mode cible retenu:

- `token`

Pourquoi:

- plus propre pour une surface distante privee
- plus defensable qu'un mode sans auth
- compatible avec l'approche `Tailscale + surface privee`

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
2. bind `loopback`
3. port `18789`
4. auth explicite
5. surface privee d'exposition

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
- [ ] fichier de config serveur `OpenClaw` defini
- [x] bind `loopback` retenu pour le gateway
- [x] auth gateway retenue explicitement
- [x] workspace `OpenClaw` retenu explicitement
- [x] politique d'exposition distante retenue (`Tailscale` d'abord)

## Outcome attendu

Quand cette spec sera materialisee sur le noeud:

- la lane `main` sera claire
- le bootstrap runtime ne dependra plus d'une convention floue
- on pourra lancer `OpenClaw` sans melanger le substrate et la couche entreprise
