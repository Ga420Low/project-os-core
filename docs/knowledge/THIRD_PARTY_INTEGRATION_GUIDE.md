# Third-Party Integration Guide

Ce document detaille comment chaque outil ou repo tiers est utilise dans Project OS.

Pour la liste complete, voir `EXTERNAL_STACK_REFERENCE.md`. Ce document explique le **comment** et le **pourquoi** de chaque integration.

## Core Stack - Decisions fermes

### OpenClaw

- **Role**: Shell operateur, surface Discord, inbox de missions
- **Integration**: `third_party/openclaw/` + `integrations/openclaw/`
- **Utilise pour**: recevoir les messages du fondateur, envoyer les notifications, gerer la file d'attente de missions
- **Interface**: ingress `OpenClaw -> gateway ingest-openclaw-event -> Mission Router`
- **Etat**: branche en live sur le poste cible via le plugin `project-os-gateway-adapter`, `openclaw doctor`, `truth-health` et `validate-live`

### LangGraph

- **Role**: Orchestration durable du graphe a 6 roles (ADR 0008)
- **Integration**: `third_party/langgraph/` + `integrations/langgraph/`
- **Utilise pour**: execution durable des missions multi-etapes, checkpointing, reprise apres crash
- **Interface**: Six-role graph (Operator Concierge, Planner, Memory Curator, Critic, Guardian, Executor Coordinator)
- **A connecter**: live graph execution (actuellement le routage est fait manuellement)

### SQLite

- **Role**: Source de verite canonique (ADR 0004)
- **Integration**: native Python `sqlite3` + `src/project_os_core/database.py`
- **Utilise pour**: state des runs, budgets, approbations, decisions, sessions
- **Regles**: transactions explicites, pas de `check_same_thread=False` en production, pas de `INSERT OR REPLACE`

### sqlite-vec

- **Role**: Recherche vectorielle locale
- **Integration**: extension SQLite
- **Utilise pour**: recherche semantique dans la memoire, matching de contexte
- **Avantage**: pas de serveur externe, tout reste local

### OpenMemory

- **Role**: Moteur de memoire primaire
- **Integration**: `third_party/openmemory/`
- **Utilise pour**: stocker et retrouver les souvenirs episodiques, proceduraux et semantiques
- **Apprentissage**: les preferences du fondateur sont promues en memoire durable via OpenMemory
- **Tiering**: hot (7j) -> warm (decisions confirmees) -> cold (archive)

### GPT API (OpenAI, gpt-5.4)

- **Role**: Le Cerveau / Le Dev (ADR 0013)
- **Integration**: `src/project_os_core/api_runs/service.py` via `_call_openai()`
- **Utilise pour**: audit, design, patch_plan, generate_patch - les 4 modes de run
- **Contexte**: 1M tokens, structured output JSON
- **Politique**: `high` par defaut, `xhigh` sur escalade, `pro` avec approbation (ADR 0003)

### Claude API (Anthropic)

- **Role**: L'Auditeur + Le Traducteur (ADR 0013)
- **Integration**: `src/project_os_core/api_runs/service.py` via `_call_reviewer()` et `_call_translator()`
- **Utilise pour**:
  1. Review cross-model du code produit par GPT
  2. Traduction des questions structurees en francais simple pour Discord
  3. Filtrage du bruit (decider quoi envoyer au fondateur)
- **Contexte**: 1M tokens (opus/sonnet)

### Infisical

- **Role**: Gestion des secrets (ADR 0005)
- **Integration**: `src/project_os_core/secrets/infisical_provider.py`
- **Utilise pour**: stocker et recuperer OPENAI_API_KEY, DISCORD_TOKEN, ANTHROPIC_API_KEY, etc.
- **Mode**: `infisical_required` avec `Universal Auth` machine-first
- **Regles**: jamais de secret dans SQLite, jamais dans les logs, jamais dans le repo

## Core Stack - Execution (workers)

### UFO

- **Role**: Reference pour le worker Windows desktop
- **Integration**: architecture de reference, pas d'import direct
- **Utilise pour**: comprendre les patterns d'interaction Windows (UIA, accessibility tree)
- **Status**: lot 6 - le worker Windows s'inspirera de UFO mais sera une implementation Project OS

### Stagehand

- **Role**: Execution web fiable pour le worker Browser
- **Integration**: `third_party/stagehand/`
- **Utilise pour**: navigation web, remplissage de formulaires, extraction de donnees
- **Status**: lot 7 - le worker Browser sera base sur Stagehand

### pywinauto

- **Role**: Actions structurees Windows via UIA
- **Integration**: dependance Python directe
- **Utilise pour**: clic, saisie, navigation dans les applications Windows
- **Avantage**: plus fiable que les coordonnees screen pour les elements UI connus

### OmniParser

- **Role**: Perception visuelle fallback
- **Integration**: `third_party/omniparser/`
- **Utilise pour**: quand pywinauto ne trouve pas un element, OmniParser analyse le screenshot
- **Pipeline**: screenshot -> OmniParser -> detection d'elements -> coordonnees -> action

## Support Stack - Observabilite

### Langfuse

- **Role**: Traces LLM, datasets, evaluations
- **Integration**: a connecter
- **Utilise pour**: tracer chaque appel API (tokens, cout, latence, qualite)
- **Objectif**: visibilite complete sur les couts et la qualite des runs

### OpenTelemetry

- **Role**: Logs, traces, metriques standard
- **Integration**: a connecter
- **Utilise pour**: monitoring systeme (CPU, memoire, latence, erreurs)

## Support Stack - Methodologie

### gstack

- **Role**: Methodologie de processus et roles
- **Integration**: reference documentaire
- **Utilise pour**: structurer les roles du graphe a 6 noeuds

## Benchmarks

### WindowsAgentArena

- **Role**: Benchmark agent Windows
- **Utilise pour**: evaluer le worker Windows sur des taches reelles
- **Status**: reference, a integrer quand le worker est pret

### OSWorld

- **Role**: Benchmark agent OS generique
- **Utilise pour**: evaluation globale de l'agent

### WorldGUI

- **Role**: Benchmark GUI desktop
- **Utilise pour**: evaluation des interactions desktop

## Research / Future

Ces repos sont des references pour des evolutions futures:

| Repo | Interet | Quand |
|------|---------|-------|
| Letta | Memoire stateful alternative | Si OpenMemory insuffisant |
| Zep | Sessions conversationnelles | Si Discord context trop limite |
| Mem0 | Memoire AI legere | Comparaison avec OpenMemory |
| Temporal | Orchestration durable alternative | Si LangGraph insuffisant |
| Qdrant / LanceDB | Vector DB alternatives | Si sqlite-vec trop lent |
| Agent-S | Agent desktop generique | Reference architecture |
| gui-agent | Agent GUI | Reference patterns |

## Regles d'integration

1. **Pas de dependance cachee** - chaque integration est explicite dans les imports et la doc
2. **Facade obligatoire** - chaque outil externe est enveloppe dans un adapter Project OS
3. **Remplacable** - si un outil est meilleur demain, on change l'adapter, pas le core
4. **Local first** - tout tourne en local, pas de dependance cloud sauf les APIs LLM
5. **Auditable** - chaque appel a un outil externe est logue

## References

- `docs/knowledge/EXTERNAL_STACK_REFERENCE.md` (liste complete)
- `docs/decisions/0003-model-policy-gpt54-high-default.md`
- `docs/decisions/0004-sqlite-canonical-store.md`
- `docs/decisions/0005-infisical-secrets-management.md`
- `docs/decisions/0008-canonical-six-role-mission-graph.md`
- `docs/decisions/0013-dual-model-operating-model.md`
