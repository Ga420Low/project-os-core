# Mission : Implémenter Mission Chaining — Objectifs multi-étapes

## Vision du projet

Aujourd'hui, chaque run est isolé. Le fondateur dit "refactorise le module X" et le système
fait UN seul run. Mais un vrai objectif multi-étapes c'est :
1. Audit du module X (run mode=audit)
2. Plan de refactoring (run mode=design)
3. Génération du patch (run mode=generate_patch)
4. Review cross-model (automatique)

C'est une MISSION = une séquence de runs liés par un objectif commun.

## Ce qui existe déjà

### MissionRun (models.py ligne 388)

```python
@dataclass(slots=True)
class MissionRun:
    mission_run_id: str
    intent_id: str
    objective: str
    profile_name: str | None
    status: MissionStatus = MissionStatus.QUEUED
    execution_class: MissionExecutionClass | None = None
    routing_decision_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
```

PAS de `parent_mission_id` — les missions sont toutes orphelines.

### MissionStatus (models.py)

```python
class MissionStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
```

### Table DB existante

```sql
CREATE TABLE IF NOT EXISTS mission_runs(
    mission_run_id TEXT PRIMARY KEY,
    intent_id TEXT NOT NULL,
    objective TEXT NOT NULL,
    profile_name TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    execution_class TEXT,
    routing_decision_id TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
```

### MissionRouter (router/service.py)

Crée des `MissionRun` via `route_intent()` :
```python
def route_intent(self, intent, *, persist=True) -> tuple[RoutingDecision, RoutingDecisionTrace, MissionRun | None]:
    # ... routing logic ...
    mission_run = MissionRun(
        mission_run_id=new_id("mission_run"),
        intent_id=intent.intent_id,
        objective=intent.objective,
        profile_name=intent.target_profile,
        status=MissionStatus.QUEUED,
        execution_class=decision.execution_class,
        routing_decision_id=decision.decision_id,
    )
```

### CanonicalMissionGraph (orchestration/graph.py — 253 lignes)

Exécute les 6 rôles séquentiels (OPERATOR_CONCIERGE → PLANNER → ... → EXECUTOR_COORDINATOR).
`prepare_execution()` crée un ExecutionTicket pour un MissionRun.

### ApiRunRequest (models.py)

```python
@dataclass(slots=True)
class ApiRunRequest:
    run_request_id: str
    context_pack_id: str
    prompt_template_id: str
    mode: ApiRunMode
    objective: str
    branch_name: str
    contract_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    # PAS de mission_run_id
```

## Ce que tu dois faire

### 1. Ajouter `parent_mission_id` et `step_index` à MissionRun

Dans `models.py` :

```python
@dataclass(slots=True)
class MissionRun:
    mission_run_id: str
    intent_id: str
    objective: str
    profile_name: str | None
    parent_mission_id: str | None = None          # NOUVEAU
    step_index: int = 0                            # NOUVEAU (0 = premier step)
    total_steps: int = 1                           # NOUVEAU
    status: MissionStatus = MissionStatus.QUEUED
    execution_class: MissionExecutionClass | None = None
    routing_decision_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
```

### 2. Ajouter les colonnes dans la table DB

Dans `database.py`, ajouter les colonnes à la création de la table :

```sql
CREATE TABLE IF NOT EXISTS mission_runs(
    mission_run_id TEXT PRIMARY KEY,
    intent_id TEXT NOT NULL,
    objective TEXT NOT NULL,
    profile_name TEXT,
    parent_mission_id TEXT,              -- NOUVEAU
    step_index INTEGER NOT NULL DEFAULT 0,  -- NOUVEAU
    total_steps INTEGER NOT NULL DEFAULT 1, -- NOUVEAU
    status TEXT NOT NULL DEFAULT 'queued',
    execution_class TEXT,
    routing_decision_id TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
```

Ajouter aussi une migration si la table existe déjà :

```python
# Dans _apply_migrations() ou équivalent
try:
    self.execute("ALTER TABLE mission_runs ADD COLUMN parent_mission_id TEXT", ())
except Exception:
    pass  # Colonne déjà existante
try:
    self.execute("ALTER TABLE mission_runs ADD COLUMN step_index INTEGER NOT NULL DEFAULT 0", ())
except Exception:
    pass
try:
    self.execute("ALTER TABLE mission_runs ADD COLUMN total_steps INTEGER NOT NULL DEFAULT 1", ())
except Exception:
    pass
```

### 3. Créer la table `mission_chains`

```sql
CREATE TABLE IF NOT EXISTS mission_chains(
    chain_id TEXT PRIMARY KEY,
    objective TEXT NOT NULL,
    steps_json TEXT NOT NULL,            -- [{"step_index": 0, "mode": "audit", "objective": "..."}, ...]
    current_step_index INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'running',  -- running, completed, failed, paused
    total_cost_eur REAL NOT NULL DEFAULT 0.0,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
```

### 4. Créer `src/project_os_core/mission/chain.py`

```python
from __future__ import annotations
from dataclasses import dataclass, field
from ..models import ApiRunMode, MissionStatus, new_id, utc_now_iso


@dataclass(slots=True)
class MissionStep:
    step_index: int
    mode: ApiRunMode
    objective: str
    depends_on_previous: bool = True     # Attend que le step précédent soit COMPLETED
    skip_on_previous_failure: bool = False  # Skip ce step si le précédent a échoué


@dataclass(slots=True)
class MissionChain:
    chain_id: str
    objective: str
    steps: list[MissionStep]
    current_step_index: int = 0
    status: str = "running"              # running, completed, failed, paused
    total_cost_eur: float = 0.0
    metadata: dict = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)


STANDARD_CHAINS: dict[str, list[MissionStep]] = {
    "full_refactor": [
        MissionStep(step_index=0, mode=ApiRunMode.AUDIT, objective="Audit complet du module ciblé"),
        MissionStep(step_index=1, mode=ApiRunMode.DESIGN, objective="Plan de refactoring basé sur l'audit"),
        MissionStep(step_index=2, mode=ApiRunMode.PATCH_PLAN, objective="Patch plan détaillé"),
        MissionStep(step_index=3, mode=ApiRunMode.GENERATE_PATCH, objective="Génération du patch"),
    ],
    "audit_then_patch": [
        MissionStep(step_index=0, mode=ApiRunMode.AUDIT, objective="Audit du code existant"),
        MissionStep(step_index=1, mode=ApiRunMode.GENERATE_PATCH, objective="Patch basé sur l'audit"),
    ],
    "design_only": [
        MissionStep(step_index=0, mode=ApiRunMode.AUDIT, objective="Audit rapide"),
        MissionStep(step_index=1, mode=ApiRunMode.DESIGN, objective="Design complet"),
    ],
}
```

### 5. Créer `MissionChainService`

```python
class MissionChainService:
    def __init__(self, *, database: CanonicalDatabase, api_runs: ApiRunService, journal: LocalJournal):
        self.database = database
        self.api_runs = api_runs
        self.journal = journal

    def create_chain(self, *, objective: str, chain_template: str | None = None, steps: list[MissionStep] | None = None) -> MissionChain:
        """Crée une mission chain à partir d'un template standard ou de steps custom."""

    def advance_chain(self, chain_id: str) -> dict:
        """Avance la chain au step suivant si le step courant est COMPLETED.

        Retourne le prochain run à lancer, ou un status 'completed' si la chain est finie.
        """

    def chain_status(self, chain_id: str) -> MissionChain:
        """Retourne l'état complet de la chain."""

    def fail_chain(self, chain_id: str, *, reason: str) -> MissionChain:
        """Marque la chain comme failed."""

    def pause_chain(self, chain_id: str) -> MissionChain:
        """Met la chain en pause (le fondateur reprendra quand il veut)."""
```

**`advance_chain()` logique** :

```python
def advance_chain(self, chain_id: str) -> dict:
    chain = self.chain_status(chain_id)
    if chain.status != "running":
        return {"status": chain.status, "action": "none"}

    current_step = chain.steps[chain.current_step_index]

    # Vérifier si le run du step courant est terminé
    step_runs = self._get_runs_for_step(chain_id, chain.current_step_index)
    if not step_runs:
        # Pas encore de run pour ce step → lancer le premier run
        return {"status": "ready", "action": "launch_step", "step": current_step}

    last_run = step_runs[-1]
    if last_run["status"] == "completed":
        # Step terminé → avancer
        next_index = chain.current_step_index + 1
        if next_index >= len(chain.steps):
            # Chain terminée !
            self._update_chain_status(chain_id, "completed")
            return {"status": "completed", "action": "none", "total_cost_eur": chain.total_cost_eur}
        else:
            # Avancer au step suivant
            self._update_chain_step(chain_id, next_index)
            next_step = chain.steps[next_index]
            # Injecter l'output du step précédent dans le contexte du suivant
            return {"status": "running", "action": "launch_step", "step": next_step,
                    "previous_output": last_run.get("structured_output")}

    if last_run["status"] == "failed":
        next_step = chain.steps[chain.current_step_index]
        if next_step.skip_on_previous_failure:
            # Skip ce step et avancer
            return self.advance_chain(chain_id)  # récursif
        else:
            self._update_chain_status(chain_id, "failed")
            return {"status": "failed", "action": "none", "reason": "step_failed"}

    # Run encore en cours
    return {"status": "running", "action": "wait"}
```

### 6. Ajouter `mission_chain_id` à ApiRunRequest

```python
# Dans models.py, ajouter à ApiRunRequest :
mission_chain_id: str | None = None
mission_step_index: int | None = None
```

### 7. Ajouter les commandes CLI

```python
# Dans cli.py
chain_parser = subparsers.add_parser("chain")
chain_sub = chain_parser.add_subparsers(dest="chain_command", required=True)

chain_create = chain_sub.add_parser("create")
chain_create.add_argument("--objective", required=True)
chain_create.add_argument("--template", choices=list(STANDARD_CHAINS.keys()))
chain_create.add_argument("--branch-name", required=True)

chain_advance = chain_sub.add_parser("advance")
chain_advance.add_argument("--chain-id", required=True)

chain_status = chain_sub.add_parser("status")
chain_status.add_argument("--chain-id", required=True)

chain_list = chain_sub.add_parser("list")
chain_list.add_argument("--status", choices=["running", "completed", "failed", "paused"])
```

### 8. Intégrer dans AppServices

```python
from .mission.chain import MissionChainService

# Dans build_app_services() :
chain_service = MissionChainService(database=database, api_runs=api_runs, journal=journal)

# Dans AppServices :
chain: MissionChainService
```

## Contraintes absolues

- Chaque step d'une chain crée un run normal (context_pack → prompt → execute → review)
- L'output du step N est injecté dans le context du step N+1 (via metadata ou runtime_facts)
- Si un step échoue et `skip_on_previous_failure=False` → la chain s'arrête
- Le fondateur peut mettre en pause et reprendre une chain quand il veut
- Les coûts de chaque step s'accumulent dans `total_cost_eur`
- Le guardian pre-spend check s'applique à CHAQUE step individuellement
- Logger chaque avancement de chain

## Tests

1. `create_chain()` avec template "full_refactor" crée 4 steps
2. `advance_chain()` sur un chain avec step 0 completed → retourne step 1
3. `advance_chain()` sur le dernier step completed → chain status = "completed"
4. Step failed + skip_on_previous_failure=False → chain failed
5. Step failed + skip_on_previous_failure=True → avance au step suivant
6. `chain_status()` retourne l'état complet
7. Les runs créés par la chain ont `mission_chain_id` et `mission_step_index` corrects
