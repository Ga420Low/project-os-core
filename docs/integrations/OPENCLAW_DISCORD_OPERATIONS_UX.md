# OpenClaw Discord Operations UX

Ce runbook ferme `Pack 2 - Discord Operations UX` sans faire de `Discord` une deuxieme verite.

## Decision retenue

On garde les primitives upstream utiles:

- `threadBindings`
- `execApprovals`
- `autoPresence`

On refuse le theatre:

- pas de bot multi-personnages
- pas de logique metier critique enfouie dans des handlers Discord
- pas de components riches complexes tant que la boucle de base n'est pas beton

## Contrat retenu

`Discord` reste une surface visible.
Le runtime reste la source canonique.

Donc:

- chaque thread Discord utile doit pouvoir etre relie a un contexte runtime
- un clic d'approbation ne doit pas contourner la policy d'approbation
- la presence Discord doit suivre la sante runtime upstream, pas un flag bricolé
- si un thread Discord disparait, la verite canonique reste reconstructible depuis `Project OS`

## Pack 2 actif

### Thread bindings

OpenClaw runtime:

- `session.threadBindings.enabled = true`
- `channels.discord.threadBindings.enabled = true`
- `spawnSubagentSessions = false`

Project OS runtime:

- table `discord_thread_bindings`
- projection durable `discord thread -> mission/session`
- bind persiste depuis les `channel_events` / `gateway_dispatch_results`

Usage:

- `run`
- `incident`
- `approval`
- `discussion`

### Exec approvals

Voie retenue:

- `channels.discord.execApprovals.enabled = true`
- `target = "dm"`
- approvers explicites

Pourquoi `dm`:

- le prompt contient du texte de commande
- on veut eviter de le publier par erreur en salon
- les approvals sensibles restent compactes et privees

### Auto presence

Voie retenue:

- `channels.discord.autoPresence.enabled = true`
- textes sobres

Mapping upstream assume:

- `healthy` -> online
- `degraded` / `unknown` -> idle
- `exhausted` / unavailable -> dnd

On n'ajoute pas de couche locale de presence custom avant d'en avoir besoin.

## Policy locale Project OS

Le doctor Pack 2 bloque si:

- `threadBindings` manquent
- `autoPresence` manque
- `execApprovals` manque
- la cible approvals n'est pas celle retenue
- les approvers attendus ne sont pas presents

La commande canonique est:

```powershell
py D:/ProjectOS/project-os-core/scripts/project_os_entry.py --config-path D:/ProjectOS/project-os-core/config/storage_roots.local.json --policy-path D:/ProjectOS/project-os-core/config/runtime_policy.local.json openclaw doctor
```

## Delivery policy

Le plugin Project OS Gateway Adapter peut maintenant relayer des payloads Discord plus precis:

- `target`
- `reply_to`
- `components`
- `account_id`

Ces champs restent optionnels.
Par defaut, on garde la livraison compacte par `channel_hint`.

## Ce qui est volontairement differe

- buttons Project OS metier complexes avec callback cache
- modals/forms riches comme voie principale
- approvals metier critiques deduites de labels Discord ambigus
- presence custom pilotee par une couche locale parallele

Quand un point est explicitement differe, la trace canonique ne doit pas rester dans une simple phrase de reponse.
Le format machine retenu dans les runbooks est:

```project-os-deferred
id: discord-business-components
scope: openclaw:pack2:discord_operations_ux
summary: Keep rich custom Discord business components and ambiguous Project OS approval buttons out of scope until callback semantics are provably unambiguous.
next_trigger: when Discord component callbacks can carry a stable action id or an equivalent replay-safe token
```

Ce bloc est synchronise automatiquement vers la couche learning avant les audits quand `learning_config.auto_sync_runbook_deferred` est active.

Commande retenue:

```powershell
py D:/ProjectOS/project-os-core/scripts/project_os_entry.py --config-path D:/ProjectOS/project-os-core/config/storage_roots.local.json --policy-path D:/ProjectOS/project-os-core/config/runtime_policy.local.json learning defer-decision --scope openclaw:pack2:discord_operations_ux --summary "..." --next-trigger "..."
```

Cette commande ecrit automatiquement:

- un `DecisionRecord`
- une promotion memoire
- une ligne journal
- un fichier runtime dans `runtime/learning/decision_records/`
- une ligne append-only dans `runtime/learning/deferred_decisions.jsonl`

Les audits `api-runs` et les revues "qu'est-ce qu'il manque" ne doivent pas repartir de zero:

- le bloc `learning_context` injecte maintenant automatiquement `deferred_decisions`
- ces points sortent dans le prompt comme `Known intentional deferrals / accepted gaps`
- la synchronisation explicite est disponible pour debug via:

```powershell
py D:/ProjectOS/project-os-core/scripts/project_os_entry.py --config-path D:/ProjectOS/project-os-core/config/storage_roots.local.json --policy-path D:/ProjectOS/project-os-core/config/runtime_policy.local.json learning sync-runbook-deferred
```

- on peut aussi les lire directement via:

```powershell
py D:/ProjectOS/project-os-core/scripts/project_os_entry.py --config-path D:/ProjectOS/project-os-core/config/storage_roots.local.json --policy-path D:/ProjectOS/project-os-core/config/runtime_policy.local.json learning list-deferred --scope-prefix openclaw:pack2
```

## Verification minimale

1. `openclaw doctor` doit etre `OK`
2. `project-os openclaw truth-health --channel discord` doit montrer la projection `thread_binding_projection`
3. la table `discord_thread_bindings` doit contenir au moins un bind recent apres un message Discord reel
4. la config runtime OpenClaw doit montrer:
   - `threadBindings`
   - `autoPresence`
   - `execApprovals`

## Fichiers relies

- `src/project_os_core/gateway/service.py`
- `src/project_os_core/gateway/openclaw_live.py`
- `src/project_os_core/database.py`
- `src/project_os_core/models.py`
- `integrations/openclaw/project-os-gateway-adapter/index.js`
- `runtime/openclaw/openclaw.json`
- `config/runtime_policy.local.json`
