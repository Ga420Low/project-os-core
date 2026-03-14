# Physical Storage Layout

Ce document cartographie l'integralite du stockage physique de Project OS.

## Principe

- **SQLite** = verite canonique (state, decisions, budgets, approvals)
- **Runtime directories** = artefacts temporaires et preuves (context packs, prompts, resultats, logs)
- **Repo** = code, config, docs validees — jamais de donnees runtime
- **Hot/Warm/Cold** = tiering memoire pour performance et archivage

## Racines de stockage

Defini dans `config/storage_roots.local.json`:

| Tier | Chemin | Contenu |
|------|--------|---------|
| Hot | `D:\ProjectOS\runtime` | API runs, journal, logs, learning, DB canonique |
| Hot | `D:\ProjectOS\memory_hot` | Memoire episodique recente (TTL 7 jours) |
| Hot | `D:\ProjectOS\indexes` | Index vectoriels sqlite-vec |
| Hot | `D:\ProjectOS\sessions` | Sessions actives |
| Hot | `D:\ProjectOS\cache` | Cache temporaire (prompts, embeddings) |
| Warm | `D:\ProjectOS\memory_warm` | Memoire consolidee (decisions confirmees, patterns) |
| Cold | `E:\ProjectOSArchive\runs` | Runs archives (>30 jours) |
| Cold | `E:\ProjectOSArchive\memory` | Memoire ancienne (>90 jours) |
| Cold | `E:\ProjectOSArchive\logs` | Logs anciens |

## Runtime principal — `D:\ProjectOS\runtime\`

```
runtime/
├── api_runs/
│   ├── blockage_reports/       # rapports de blocage
│   ├── clarification_reports/  # rapports de clarification
│   ├── completion_reports/     # rapports de completion
│   ├── context_packs/          # paquets de contexte assembles
│   ├── contracts/              # contrats de run signes
│   ├── failed_results/         # resultats echoues
│   ├── prompts/                # MegaPrompts rendus
│   ├── raw_results/            # reponses brutes de l'API
│   ├── review_packages/        # paquets de revue
│   ├── reviews/                # verdicts de revue
│   └── structured_results/     # sorties structurees validees
├── artifacts/
│   └── evidence/               # preuves d'execution
├── bootstrap/                  # enregistrements de bootstrap
├── health/                     # snapshots de sante systeme
├── journal/                    # journal d'activite
├── learning/
│   └── tier_manager/           # signaux de promotion learning
├── logs/                       # logs d'execution
├── openclaw/
│   ├── extensions/             # extensions OpenClaw
│   ├── live/                   # sessions OpenClaw actives
│   ├── logs/                   # logs OpenClaw
│   ├── replay/                 # replays OpenClaw
│   └── reports/                # rapports OpenClaw
└── project_os_core.db          # base SQLite canonique (~8 Mo)
```

## Base SQLite canonique

Fichier: `D:\ProjectOS\runtime\project_os_core.db`

C'est la seule source de verite pour:

- etat des runs (id, branche, status, phase)
- contrats et approbations
- budget (depense journaliere, limite)
- decisions du fondateur
- signaux learning
- sessions actives
- preferences apprises (OpenMemory)

Regle: aucune logique ne doit lire l'etat depuis les fichiers JSON runtime.
Les fichiers JSON sont des artefacts de preuve, pas une interface de lecture.

## Repo — `D:\ProjectOS\project-os-core\`

```
project-os-core/
├── config/                     # configuration statique
│   ├── api_run_templates.json  # templates de run
│   ├── runtime_policy.example.json
│   └── storage_roots.local.json
├── docs/                       # documentation validee
├── memory/                     # squelette memoire (repo-tracked)
│   ├── episodic/
│   ├── procedural/
│   └── semantic/
├── runtime/                    # squelette runtime (repo-tracked, vide)
│   ├── approvals/
│   ├── evidence/
│   ├── sessions/
│   └── state/
├── src/project_os_core/        # code source
├── tests/                      # tests
├── workers/                    # workers (squelettes)
│   ├── windows/
│   ├── browser/
│   ├── media/
│   └── uefn/
└── profiles/                   # profils (squelettes)
    ├── desktop/
    ├── uefn/
    └── web/
```

Distinction importante:
- `project-os-core/runtime/` = squelette vide dans le repo (reference)
- `D:\ProjectOS\runtime/` = donnees live reelles (hors repo, dans .gitignore)

## Third-party clones

```
D:\ProjectOS\project-os-core\third_party/
├── langgraph/      # orchestration durable
├── letta/          # memoire stateful (reference)
├── omniparser/     # perception visuelle (reference)
├── openclaw/       # shell operateur + Discord
├── openmemory/     # moteur memoire primaire
└── stagehand/      # execution web fiable
```

## Politique d'archivage

| Condition | Action |
|-----------|--------|
| Run termine depuis >30 jours | Deplacer vers `E:\ProjectOSArchive\runs` |
| Memoire episodique >90 jours sans acces | Deplacer vers cold |
| Logs >14 jours | Comprimer et archiver |
| Cache >7 jours | Purger |

## Regles de securite

- `project_os_core.db` ne contient jamais de secrets (Infisical = seule source)
- les fichiers `raw_results/` peuvent contenir du contenu sensible (ne pas exposer)
- les fichiers `config/*.local.*` ne sont jamais commites
- les sauvegardes de la DB doivent exclure le WAL temporaire

## References

- `config/storage_roots.local.json`
- `docs/architecture/MEMORY_STORAGE_AND_OPS_BLUEPRINT.md`
- `docs/decisions/0004-sqlite-canonical-store.md`
- `docs/decisions/0005-infisical-secrets-management.md`
