# OpenClaw Gateway Adapter

Ce document fige le lot `OpenClaw live bootstrap + replay + doctor` entre `OpenClaw` et `Project OS`.

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
- `src/project_os_core/gateway/openclaw_live.py`
- `src/project_os_core/cli.py`
- `integrations/openclaw/project-os-gateway-adapter/package.json`
- `integrations/openclaw/project-os-gateway-adapter/index.js`
- `integrations/openclaw/project-os-gateway-adapter/openclaw.plugin.json`
- `integrations/openclaw/project-os-gateway-adapter/replay_harness.mjs`
- `integrations/openclaw/project-os-gateway-adapter/README.md`
- `fixtures/openclaw/*.json`
- `tests/unit/test_openclaw_live.py`

## Commande canonique du plugin

Le plugin appelle:

```bash
py D:/ProjectOS/project-os-core/scripts/project_os_entry.py --config-path D:/ProjectOS/project-os-core/config/storage_roots.local.json --policy-path D:/ProjectOS/project-os-core/config/runtime_policy.local.json gateway ingest-openclaw-event --stdin
```

## Politique

- `OpenClaw` ne stocke pas la memoire canonique
- `OpenClaw` ne route pas lui-meme les missions
- `OpenClaw` ne contourne pas le `Mission Router`
- les acks de canal restent optionnels et desactives par defaut
- aucune validation live n'est consideree acquise sans un message reel Discord/WebChat
- tant que le replay ou le doctor sont rouges, le mode live doit echouer ferme

## Runtime reel retenu

- runtime OpenClaw: `D:\ProjectOS\openclaw-runtime`
- state OpenClaw: `D:\ProjectOS\runtime\openclaw`

Le code source `OpenClaw` reste une dependance dans `third_party`.
Le runtime actif ne tourne pas dans le checkout source.

## Bootstrap retenu

La voie retenue est la voie native `OpenClaw`:

```bash
openclaw plugins install --link D:/ProjectOS/project-os-core/integrations/openclaw/project-os-gateway-adapter
```

Le bootstrap `Project OS` doit:

1. verifier le binaire `openclaw`
2. preparer les racines runtime et state
3. lier le plugin local
4. verifier le manifest plugin
5. verifier l'entree Python `Project OS`

## Doctor retenu

La commande canonique est:

```bash
py D:/ProjectOS/project-os-core/scripts/project_os_entry.py openclaw doctor
```

Le doctor verifie:

- binaire `OpenClaw`
- racines runtime/state
- manifest plugin
- entree Python callable
- channels actifs
- policy `silence + fin`
- plugin visible dans `OpenClaw`
- config `OpenClaw` valide
- statut gateway lisible

Le verdict doit rester comprehensible pour un non-developpeur:

- `OK`
- `bloque`
- `a corriger`

## Replay retenu

Le replay est obligatoire avant tout live:

```bash
py D:/ProjectOS/project-os-core/scripts/project_os_entry.py openclaw replay --all
```

Les fixtures couvrent:

- message texte simple
- message avec piece jointe
- message de type `tasking`
- message qui doit rester hors memoire durable

Le replay doit prouver:

- `OpenClaw -> plugin -> CLI Project OS -> Gateway -> Mission Router`
- aucun bypass memoire canonique
- aucun bypass `Mission Router`

## Validation live

La validation live minimale est volontairement fail-closed.

La commande:

```bash
py D:/ProjectOS/project-os-core/scripts/project_os_entry.py openclaw validate-live --channel discord --payload-file fixtures/openclaw/simple_text.json
```

doit rester bloquee tant qu'un vrai message Discord/WebChat n'a pas ete prouve.

## Etat du lot

Ce lot est maintenant:

- code
- teste au niveau repo
- bootstrappe sur le poste
- valide par doctor
- valide par replay
- bloque proprement en live tant qu'aucun canal reel n'est branche

Il n'est pas encore considere 100% termine tant qu'un runtime `OpenClaw` reel n'a pas ete branche sur `Discord` ou `WebChat` avec un message entrant reel jusqu'au `Mission Router`.
