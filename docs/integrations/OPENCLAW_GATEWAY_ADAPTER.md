# OpenClaw Gateway Adapter

Ce document fige le premier pont live entre `OpenClaw` et `Project OS`.

## Principe

`OpenClaw` reste la facade operateur:

- Discord
- WebChat
- Control UI
- inbox
- pairing

`Project OS` reste le coeur:

- runtime truth
- memory
- mission router
- workers
- evidence

## Point d'integration retenu

On n'a pas modifie le channel Discord d'`OpenClaw`.
On branche un plugin local qui ecoute le hook:

- `message_received`

Puis le plugin:

1. transforme l'evenement `OpenClaw`
2. construit une charge utile canonique
3. appelle `Project OS` via CLI
4. laisse `Project OS` prendre toutes les decisions

## Fichiers du lot

- `src/project_os_core/gateway/openclaw_adapter.py`
- `src/project_os_core/cli.py`
- `integrations/openclaw/project-os-gateway-adapter/package.json`
- `integrations/openclaw/project-os-gateway-adapter/index.js`
- `integrations/openclaw/project-os-gateway-adapter/README.md`

## Commande canonique

Le plugin appelle:

```bash
py D:/ProjectOS/project-os-core/scripts/project_os_entry.py --config-path D:/ProjectOS/project-os-core/config/storage_roots.local.json --policy-path D:/ProjectOS/project-os-core/config/runtime_policy.local.json gateway ingest-openclaw-event --stdin
```

## Politique

- `OpenClaw` ne stocke pas la memoire canonique
- `OpenClaw` ne route pas lui-meme les missions
- `OpenClaw` ne contourne pas le `Mission Router`
- les acks de canal restent optionnels et desactives par defaut

## Etat du lot

Ce lot est code et teste au niveau repo.
Il n'est pas encore considere 100% termine tant qu'un runtime `OpenClaw` reel n'a pas ete branche sur le poste et valide sur `Discord` ou `WebChat`.
