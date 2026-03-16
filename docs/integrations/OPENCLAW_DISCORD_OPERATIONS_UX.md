# OpenClaw Discord Operations UX

## But

Garder `Discord` simple cote operateur, tout en rendant visibles:

- l'etat de publication
- le mode de sortie (`inline_text`, `thread_chunked_text`, `artifact_summary`)
- la presence d'un artefact complet
- les incidents de livraison sans perte silencieuse

## Regles UX

### 0. Presence immediate

- `typing indicator` actif des l'ingress via le bridge Discord direct
- pas de message texte `vu / j'ai commence`
- reglage retenu: `agents.defaults.typingMode = instant`
- cadence retenue: `agents.defaults.typingIntervalSeconds = 6`

### 1. Reponse courte

- `inline_text`
- visible directement dans Discord

### 2. Reponse moyenne

- `thread_chunked_text`
- plusieurs messages, chunking en filet final

### 3. Reponse longue ou reviewable

- `artifact_summary`
- resume Discord court
- document complet joint en `PDF`
- manifest durable cote runtime

## Etats visibles

Les etats a rendre visibles dans le dashboard et les audits sont:

- `queued`
- `ok`
- `attention`
- `breach`
- `none`

Interpretation:

- `queued`: livraison encore en attente sans erreur
- `ok`: livraison complete ou replay-safe sans alerte
- `attention`: incident visible mais recuperable
- `breach`: risque de perte silencieuse ou failure visible manquante
- `none`: pas de delivery rattachee

## Audit no-loss

Le dashboard doit permettre de repondre vite a ces questions:

1. Est-ce qu'une livraison importante a echoue sans signal visible ?
2. Est-ce qu'un dead-letter existe ?
3. Est-ce qu'un replay est possible ?
4. Est-ce que la sortie longue a bien un artefact complet ?

## Replay

Si une delivery terminale a echoue:

- dead-letter JSON durable
- replay manuel via:

```bash
project-os api-runs requeue-operator-delivery --delivery-id <delivery_id>
```

## Calibration live

Pour calibrer une vraie conversation Discord sans automatiser un compte utilisateur:

```bash
py D:/ProjectOS/project-os-core/scripts/project_os_entry.py openclaw discord-calibration --watch
```

Ce watcher montre en direct:

- le message entrant Discord
- la route choisie
- l'API / le modele visibles cote runtime
- les cartes `approval / cout / temps / go`
- les deliveries recentes
- les dernieres lignes du log OpenClaw

Options utiles:

- `--limit 8` pour remonter plus d'evenements
- `--log-lines 40` pour voir plus de log
- `--json` pour exporter un snapshot brut exploitable ensuite

## Lecture dashboard

Le dashboard doit montrer:

- sante des deliveries
- audit no-loss
- modes de reponse Discord recents
- replies `artifact_summary` recentes
- eventuels `manifest_gap`

## Regle produit retenue

- tant que la reponse tient proprement dans Discord, on garde la `full response` en chat
- on ne joint pas de `.md` dans la conversation pour une reponse moyenne
- on bascule en `PDF` seulement pour les vraies sorties longues / reviewables

## Future - Meeting OS

Le cockpit texte actuel reste la surface canonique en production.

La voie `meeting voice` vise autre chose:

- le fondateur appelle le maitre, jamais l'inverse
- au debut, `une seule voix visible`: le maitre
- les workers de fond restent silencieux
- les changements de cerveau (`sonnet`, `opus`, `gpt`) doivent etre gouvernes par langage naturel, cout et confirmation si necessaire
- les invites temporaires (`designer`, `coder`, `researcher`) sont un lot futur, pas une baseline

Regles produit deja figees pour cette future voie:

- `inbound only`
- `single visible voice`
- `master memory is canonical`
- `guest agents are temporary`
- `background workers stay silent`

Reference canonique:

- `docs/roadmap/DISCORD_MEETING_OS_PLAN.md`
