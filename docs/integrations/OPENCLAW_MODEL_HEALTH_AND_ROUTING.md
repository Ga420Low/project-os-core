# OpenClaw Model Health And Routing

Ce document fige le lot `Pack 3 - Model Health And Routing`.

## Objet

Rendre visibles et exploitables quatre choses avant un run:

- l'etat du stack modele
- le tier de route retenu `fast / local / api`
- l'escalade automatique hors `local` si la voie locale n'est pas configuree
- un recap borne des sessions recentes sur la meme branche ou le meme profil

`OpenClaw` reste une facade.
La verite canonique du routage reste dans `Project OS`.

## Commandes canoniques

Snapshot du stack modele:

```powershell
py D:/ProjectOS/project-os-core/scripts/project_os_entry.py --config-path D:/ProjectOS/project-os-core/config/storage_roots.local.json --policy-path D:/ProjectOS/project-os-core/config/runtime_policy.local.json router model-health
```

Briefing recent borne:

```powershell
py D:/ProjectOS/project-os-core/scripts/project_os_entry.py --config-path D:/ProjectOS/project-os-core/config/storage_roots.local.json --policy-path D:/ProjectOS/project-os-core/config/runtime_policy.local.json router proactive-briefing --branch-name project-os/ma-branche
```

## Tiers retenus

- `fast`
  - deterministic first
  - Discord compact `chat/status`
  - reformulation / ops simple
- `local`
  - voie locale Windows-first quand elle est explicitement configuree et prouvee
  - provider actuel sur le poste cible: `Ollama`
  - modele actuel sur le poste cible: `qwen2.5:14b`
- `api`
  - GPT / Claude via API
  - code, arbitrage, review, traduction, runs plus lourds

## Politique retenue

- `Discord` simple reste route sur `Claude API`
- le deterministic fast path reste la voie `fast` par defaut hors besoin LLM fort
- la voie `local` ne casse rien si elle n'est pas configuree
- si `local_model_enabled = true`, `doctor --strict` exige maintenant une voie locale `ready`
- si `prefer_local_model = true` mais que la voie locale est absente, le systeme escalade explicitement vers `api`
- si un contenu `S3` dispose d'une voie locale `ready`, le routage retient `s3_local_route`

Raison canonique d'escalade:

- `local_unavailable_escalated_to_api`

## Preuves runtime

Le stack modele est maintenant visible:

- dans `router model-health`
- dans `doctor`
- dans `health snapshot`
- dans `context_pack.runtime_facts.model_stack_health`

Le recap recent est visible:

- dans `router proactive-briefing`
- dans `context_pack.runtime_facts.recent_session_briefing`

## Format utile

Le snapshot modele expose:

- `tiers.fast`
- `tiers.local`
- `tiers.api`
- `providers.openai`
- `providers.anthropic`
- `providers.local`

Sur le poste cible actuel, la voie locale expose en plus:

- `provider = ollama`
- `base_url = http://127.0.0.1:11434`
- `model = qwen2.5:14b`
- `latency_ms`
- `available_models`

Le briefing recent expose:

- `count`
- `items[]`
- `summary`

Chaque item garde seulement:

- `branch_name`
- `mode`
- `objective`
- `target_profile`
- `request_status`
- `result_status`
- `model`
- `updated_at`
- `run_id`

## Limites volontaires

- la voie locale n'est pas universelle: elle sert d'abord la privacy et certains runs bornes
- `Discord` simple compact reste route sur `Claude API`
- la voie locale n'autorise jamais un fallback cloud implicite pour `S3`
- on n'injecte pas un briefing si aucun run recent utile n'existe
- le briefing reste borne pour ne pas polluer le context pack

## Critere de succes

Le lot est considere sain quand:

- `router model-health` distingue bien `fast`, `local`, `api`
- `doctor` et `health snapshot` exposent le meme snapshot modele
- si `local_model_enabled = true`, le tier `local` est reellement `ready` ou le strict doctor echoue
- un `context pack` porte `model_stack_health`
- un `context pack` peut porter `recent_session_briefing` quand une branche a deja un historique recent
- `prefer_local_model` sans voie locale configuree n'entraine ni crash ni silence, mais une escalation explicite
- un `S3` route localement si la voie locale est prete
