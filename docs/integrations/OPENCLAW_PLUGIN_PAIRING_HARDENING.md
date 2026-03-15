# OpenClaw Plugin Pairing Hardening

Ce document fige le lot `Pack 1 - Plugin And Pairing Hardening`.

## Objet

Prouver localement que la frontiere `OpenClaw` reste bornee sur deux axes:

- quels plugins ont le droit d'etre actifs
- comment les credentials de pairing restent courts, locaux et non exposes

## Commande canonique

```bash
py D:/ProjectOS/project-os-core/scripts/project_os_entry.py --config-path D:/ProjectOS/project-os-core/config/storage_roots.local.json --policy-path D:/ProjectOS/project-os-core/config/runtime_policy.local.json openclaw trust-audit
```

Le rapport canonique est ecrit dans:

- `D:/ProjectOS/runtime/openclaw/live/latest_trust_audit.json`

## Politique retenue

- aucun secret long terme ne doit rester en clair dans `runtime/openclaw/openclaw.json`
- seuls les plugins explicitement approuves peuvent etre consideres sains
- le plugin local `project-os-gateway-adapter` doit rester installe depuis un chemin local explicite
- la provenance plugin doit rester reproductible via `load.paths` + `plugins.installs`
- les tokens de bootstrap de pairing doivent rester courts, jetables et hors thread public
- les tokens device persistants restent autorises uniquement dans le store sensible local `OpenClaw`

## Allowlist retenue

Le trust audit borne actuellement les plugins actifs a:

- `project-os-gateway-adapter`
- `discord`
- `device-pair`
- `memory-core`

Tout autre plugin actif ou charge hors de cette allowlist doit faire echouer le lot.

## Preuve plugin retenue

Le trust audit verifie:

- `plugins.allow` explicite dans `openclaw.json`
- catalogue plugin actif via `openclaw plugins list --json`
- ids, origines et chemins charges
- enregistrement `plugins.installs.project-os-gateway-adapter`
- version locale attendue du plugin Project OS
- absence de source d'installation hors policy

Pour le plugin local Project OS, la preuve minimale attendue est:

- `source = path`
- `sourcePath = D:/ProjectOS/project-os-core/integrations/openclaw/project-os-gateway-adapter`
- `installPath = D:/ProjectOS/project-os-core/integrations/openclaw/project-os-gateway-adapter`
- `version` egale a la version du `package.json` local

## Preuve pairing retenue

Le trust audit verifie:

- coherence de `devices/paired.json`
- coherence de `devices/pending.json`
- coherence de `identity/device-auth.json`
- alignement entre token `device-auth` et token approuve dans `paired.json`
- scopes token inclus dans la baseline approuvee
- absence de fuite des tokens dans les surfaces visibles scannees

Les secrets de pairing autorises localement vivent uniquement dans:

- `D:/ProjectOS/runtime/openclaw/devices/paired.json`
- `D:/ProjectOS/runtime/openclaw/identity/device-auth.json`

Leur presence locale est attendue. Leur presence dans des logs, transcripts, sessions ou events visibles est interdite.

## Rotation retenue

Fenetre actuelle:

- `30 jours` max pour les tokens device operateur

Si un token depasse cette fenetre:

1. revoquer ou faire tourner le device
2. re-pair si necessaire
3. rerun `openclaw trust-audit`

## Surfaces scannees

Le trust audit scanne notamment:

- `D:/ProjectOS/runtime/openclaw/agents/**`
- `D:/ProjectOS/runtime/openclaw/logs/**`
- les fichiers texte/json/jsonl/log/md visibles sous `D:/ProjectOS/runtime/openclaw`
- `D:/ProjectOS/runtime/journal/events.jsonl`

Il exclut volontairement les emplacements sensibles autorises:

- `devices/paired.json`
- `identity/device-auth.json`

## Critere de succes

Le lot est considere sain quand:

- `openclaw trust-audit` retourne `OK`
- `latest_trust_audit.json` ne contient aucune `actionable_fixes`
- aucun secret plugin/pairing n'est retrouve dans les surfaces visibles scannees
- la rotation pairing reste dans la fenetre retenue
- aucun plugin actif ne sort de l'allowlist

## Limite volontaire

Le trust audit ne prouve pas que `OpenClaw` n'a aucun bug interne.
Il prouve que notre posture locale reste bornee et auditable sans devoir relire tout le code plugin ou tout l'upstream `OpenClaw`.
