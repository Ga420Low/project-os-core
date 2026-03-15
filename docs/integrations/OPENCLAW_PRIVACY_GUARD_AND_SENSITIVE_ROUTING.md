# OpenClaw Privacy Guard And Sensitive Routing

## Objet

Ce runbook decrit `Pack 4 - Privacy Guard And Sensitive Routing`.

Le but est simple:

- classer les messages operateur en `S1`, `S2` ou `S3`
- ne jamais laisser un contenu `S3` partir au cloud par erreur
- garder une memoire exploitable sans dupliquer n'importe quoi

## Regles canoniques

- `S1 passthrough`
  Le contenu suit la policy normale.
- `S2 desensitize`
  Le runtime garde une copie `full` locale et une copie `clean` exploitable.
- `S3 local`
  Le contenu reste local. S'il existe une voie locale sure, le routage execute localement. Sinon, le routage bloque.

Regles dures:

- `S3` ne downgrade jamais vers le cloud par commodite.
- la copie `full` reste locale et ne passe ni par `OpenMemory` ni par embeddings cloud
- la recherche memoire standard ne remonte pas les vues `full` par defaut

## Implementation retenue

- classification et sanitization partagees dans `src/project_os_core/privacy_guard.py`
- selective sync enrichi dans `src/project_os_core/gateway/promotion.py`
- blocage/routage `S3` dans `src/project_os_core/router/service.py`
- memoire `full / clean` et garde de reindex/search dans `src/project_os_core/memory/store.py`
- Discord simple chat desensitize `S2` avant appel cloud dans `src/project_os_core/gateway/service.py`
- execution inline locale `S3` via la voie locale Windows-first dans `src/project_os_core/local_model.py`

## Heuristiques V1

`S3`

- secret assigne `token=...`, `password=...`, `client_secret=...`
- bearer token
- cle OpenAI/GitHub/Slack/AWS detectee
- JWT detecte
- bloc de cle privee
- nom de piece jointe sensible `.env`, `.pem`, `secrets.json`, `id_rsa`, etc.

`S2`

- email
- numero de telephone
- reference a un secret sans valeur brute
- nom de variable d'environnement sensible

## Preuves d'acceptation

### 1. Le doctor live doit garder la policy active

```powershell
py D:\ProjectOS\project-os-core\scripts\project_os_entry.py --config-path D:\ProjectOS\project-os-core\config\storage_roots.local.json --policy-path D:\ProjectOS\project-os-core\config\runtime_policy.local.json openclaw doctor
```

Le check `privacy_guard_policy` doit etre `ok`.

### 2. La recherche standard ne doit pas exposer les vues `full`

```powershell
py D:\ProjectOS\project-os-core\scripts\project_os_entry.py --config-path D:\ProjectOS\project-os-core\config\storage_roots.local.json --policy-path D:\ProjectOS\project-os-core\config\runtime_policy.local.json memory search --user-id founder --query "local only"
```

Pour auditer aussi les copies `full`, utiliser:

```powershell
py D:\ProjectOS\project-os-core\scripts\project_os_entry.py --config-path D:\ProjectOS\project-os-core\config\storage_roots.local.json --policy-path D:\ProjectOS\project-os-core\config\runtime_policy.local.json memory search --user-id founder --query "local only" --include-private-full
```

### 3. Les preuves testables retenues

- `tests/unit/test_router.py`
- `tests/unit/test_gateway_and_orchestration.py`
- `tests/integration/test_memory_store.py`

### 4. Preuve locale `S3`

Une preuve locale `S3` saine doit montrer:

- `route_reason = s3_local_route`
- `model = qwen2.5:14b`
- `reply_kind = chat_response` ou `blocked` si la voie locale est tombee
- aucune reprise verbatim du secret dans la reponse
- metadata memoire:
  - `privacy_view = full`
  - `openmemory_enabled = false`
  - `cloud_route_blocked = true`

## Notes d'architecture

- la copie `full` n'est pas une seconde memoire canonique
- elle reste dans le meme runtime local, avec metadata stricte
- la copie `clean` sert a la recherche et au routage cloud quand `S2`
- `S3` utilise maintenant une vraie voie locale Windows-first sur le poste cible
- si cette voie locale n'est plus `ready`, la bonne valeur redevient le blocage propre
