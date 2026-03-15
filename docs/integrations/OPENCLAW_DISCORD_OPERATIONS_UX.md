# OpenClaw Discord Operations UX

## But

Garder `Discord` simple cote operateur, tout en rendant visibles:

- l'etat de publication
- le mode de sortie (`inline_text`, `thread_chunked_text`, `artifact_summary`)
- la presence d'un artefact complet
- les incidents de livraison sans perte silencieuse

## Regles UX

### 1. Reponse courte

- `inline_text`
- visible directement dans Discord

### 2. Reponse moyenne

- `thread_chunked_text`
- plusieurs messages, chunking en filet final

### 3. Reponse longue ou reviewable

- `artifact_summary`
- resume Discord court
- document complet joint en `markdown`
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

## Lecture dashboard

Le dashboard doit montrer:

- sante des deliveries
- audit no-loss
- modes de reponse Discord recents
- replies `artifact_summary` recentes
- eventuels `manifest_gap`

## Limite actuelle

Le document complet joint est actuellement `markdown`.

Le `PDF` reste une evolution future si une revue visuelle stable devient preferable au markdown.
