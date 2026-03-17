# Mission : Implémenter Scheduled Runs — Autonomie sans déclenchement humain

## Vision du projet

Un agent autonome ne doit pas attendre que le fondateur lui dise quoi faire.
Il doit pouvoir exécuter des tâches planifiées : audits quotidiens, compaction mémoire,
vérification santé, nettoyage des artefacts expirés.

Le fondateur dort, le système travaille.

## Ce qui existe déjà

### Polling existant dans OpenClaw plugin (index.js)

Le plugin OpenClaw a déjà un polling loop :
```javascript
setInterval(() => {
    void tick();  // flush operator deliveries toutes les 8 secondes
}, config.operatorPollingIntervalMs);
```

Ce même pattern peut servir pour les scheduled runs.

### CLI existant (cli.py)

Le CLI a déjà toutes les commandes pour lancer des runs :
```
api-runs execute --mode audit --objective "..." --branch-name codex/project-os-audit
api-runs execute --mode design --objective "..." --branch-name codex/project-os-design
memory compact-tiers --trigger scheduled
```

### ApiRunService.execute() (service.py)

La méthode execute() est complète : context_pack → prompt → API call → review → delivery.

### TierManagerService (memory/tiering.py)

```python
class TierManagerService:
    def compact(self, *, trigger: str, dry_run: bool = False) -> dict:
        """Migre les records warm anciens vers cold."""
    def analyze(self) -> dict:
        """Rapport sur la distribution mémoire."""
```

### RuntimeStore (runtime/store.py)

```python
class RuntimeStore:
    def record_runtime_state(self, *, session_id, verdict, blockers, status_summary, metadata) -> RuntimeState
    def latest_runtime_state(self) -> dict | None
```

### AppServices — tout est accessible

```python
class AppServices:
    database, journal, memory, tier_manager, learning,
    runtime, router, gateway, api_runs, logger, ...
```

## Ce que tu dois faire

### 1. Créer `src/project_os_core/scheduler/__init__.py`

Fichier vide.

### 2. Créer `src/project_os_core/scheduler/service.py`

```python
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from ..database import CanonicalDatabase, dump_json
from ..models import new_id, utc_now_iso
from ..runtime.journal import LocalJournal
from ..observability import StructuredLogger


@dataclass(slots=True)
class ScheduledTask:
    task_id: str
    name: str                          # "daily_audit", "memory_compact", "health_check"
    schedule_kind: str                 # "interval" ou "daily_at"
    interval_seconds: int | None       # pour "interval" : toutes les N secondes
    daily_at_hour: int | None          # pour "daily_at" : à quelle heure UTC
    daily_at_minute: int | None
    command: str                       # la commande CLI ou l'action à exécuter
    command_args: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    last_run_at: str | None = None
    next_run_at: str | None = None
    last_status: str | None = None     # "success", "failed", "skipped"
    last_error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)


class SchedulerService:
    """Gère les tâches planifiées du système."""

    def __init__(
        self,
        *,
        database: CanonicalDatabase,
        journal: LocalJournal,
        logger: StructuredLogger,
    ) -> None:
        self.database = database
        self.journal = journal
        self.logger = logger
        self._ensure_table()
        self._ensure_default_tasks()
```

### 3. Table DB

```python
def _ensure_table(self):
    self.database.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_tasks(
            task_id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            schedule_kind TEXT NOT NULL,
            interval_seconds INTEGER,
            daily_at_hour INTEGER,
            daily_at_minute INTEGER,
            command TEXT NOT NULL,
            command_args_json TEXT NOT NULL DEFAULT '{}',
            enabled INTEGER NOT NULL DEFAULT 1,
            last_run_at TEXT,
            next_run_at TEXT,
            last_status TEXT,
            last_error TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """, ())
```

### 4. Tâches par défaut

```python
DEFAULT_TASKS = [
    {
        "name": "memory_compact",
        "schedule_kind": "interval",
        "interval_seconds": 3600 * 6,           # Toutes les 6 heures
        "command": "memory_compact",
        "command_args": {"trigger": "scheduled"},
    },
    {
        "name": "health_check",
        "schedule_kind": "interval",
        "interval_seconds": 3600,                # Toutes les heures
        "command": "health_check",
        "command_args": {},
    },
    {
        "name": "daily_audit",
        "schedule_kind": "daily_at",
        "daily_at_hour": 6,                      # 6h UTC (8h Paris)
        "daily_at_minute": 0,
        "command": "daily_audit",
        "command_args": {"mode": "audit", "objective": "Audit quotidien automatique du repo"},
        "enabled": False,                         # Désactivé par défaut, le fondateur l'active quand il veut
    },
    {
        "name": "cleanup_expired_deliveries",
        "schedule_kind": "interval",
        "interval_seconds": 3600 * 12,           # Toutes les 12 heures
        "command": "cleanup_deliveries",
        "command_args": {"max_age_hours": 48},
    },
]

def _ensure_default_tasks(self):
    for task_def in DEFAULT_TASKS:
        existing = self.database.fetchone(
            "SELECT task_id FROM scheduled_tasks WHERE name = ?",
            (task_def["name"],),
        )
        if existing is None:
            task = ScheduledTask(
                task_id=new_id("sched_task"),
                name=task_def["name"],
                schedule_kind=task_def["schedule_kind"],
                interval_seconds=task_def.get("interval_seconds"),
                daily_at_hour=task_def.get("daily_at_hour"),
                daily_at_minute=task_def.get("daily_at_minute"),
                command=task_def["command"],
                command_args=task_def.get("command_args", {}),
                enabled=task_def.get("enabled", True),
            )
            task.next_run_at = self._compute_next_run(task)
            self._persist_task(task)
```

### 5. Méthodes principales

```python
def get_due_tasks(self) -> list[ScheduledTask]:
    """Retourne les tâches dont next_run_at est dans le passé et qui sont enabled."""
    now = datetime.now(timezone.utc).isoformat()
    rows = self.database.fetchall(
        "SELECT * FROM scheduled_tasks WHERE enabled = 1 AND next_run_at <= ? ORDER BY next_run_at ASC",
        (now,),
    )
    return [self._row_to_task(row) for row in rows]

def mark_task_executed(self, task_id: str, *, status: str, error: str | None = None) -> None:
    """Marque une tâche comme exécutée et calcule le prochain run."""
    task = self.get_task(task_id)
    now = datetime.now(timezone.utc).isoformat()
    next_run = self._compute_next_run(task)
    self.database.execute(
        """
        UPDATE scheduled_tasks
        SET last_run_at = ?, last_status = ?, last_error = ?, next_run_at = ?, updated_at = ?
        WHERE task_id = ?
        """,
        (now, status, error, next_run, now, task_id),
    )
    self.journal.append("scheduled_task_executed", "scheduler", {
        "task_id": task_id, "name": task.name, "status": status, "next_run_at": next_run,
    })

def enable_task(self, name: str) -> ScheduledTask:
    """Active une tâche planifiée."""

def disable_task(self, name: str) -> ScheduledTask:
    """Désactive une tâche planifiée."""

def list_tasks(self) -> list[ScheduledTask]:
    """Liste toutes les tâches planifiées."""

def _compute_next_run(self, task: ScheduledTask) -> str:
    now = datetime.now(timezone.utc)
    if task.schedule_kind == "interval" and task.interval_seconds:
        return (now + timedelta(seconds=task.interval_seconds)).isoformat()
    if task.schedule_kind == "daily_at" and task.daily_at_hour is not None:
        target = now.replace(hour=task.daily_at_hour, minute=task.daily_at_minute or 0, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target.isoformat()
    return (now + timedelta(hours=1)).isoformat()  # fallback
```

### 6. Créer le tick scheduler (appelé par le polling)

```python
def tick(self, *, executor) -> list[dict]:
    """Appelé périodiquement. Exécute les tâches dues.

    executor est un callable qui prend (command: str, args: dict) et retourne un dict result.
    """
    due_tasks = self.get_due_tasks()
    results = []
    for task in due_tasks:
        self.logger.log("INFO", "scheduled_task_starting", task_id=task.task_id, name=task.name)
        try:
            result = executor(task.command, task.command_args)
            self.mark_task_executed(task.task_id, status="success")
            results.append({"task_id": task.task_id, "name": task.name, "status": "success", "result": result})
        except Exception as exc:
            self.mark_task_executed(task.task_id, status="failed", error=str(exc))
            self.logger.log("WARNING", "scheduled_task_failed", task_id=task.task_id, name=task.name, error=str(exc))
            results.append({"task_id": task.task_id, "name": task.name, "status": "failed", "error": str(exc)})
    return results
```

### 7. Commande CLI `scheduler tick`

```python
# Dans cli.py
scheduler_parser = subparsers.add_parser("scheduler")
scheduler_sub = scheduler_parser.add_subparsers(dest="scheduler_command", required=True)

scheduler_tick = scheduler_sub.add_parser("tick")
scheduler_list = scheduler_sub.add_parser("list")
scheduler_enable = scheduler_sub.add_parser("enable")
scheduler_enable.add_argument("--name", required=True)
scheduler_disable = scheduler_sub.add_parser("disable")
scheduler_disable.add_argument("--name", required=True)
```

Implémentation du tick dans le CLI :

```python
if args.command == "scheduler":
    if args.scheduler_command == "tick":
        def executor(command, args_dict):
            if command == "memory_compact":
                return services.tier_manager.compact(trigger=args_dict.get("trigger", "scheduled"))
            if command == "health_check":
                state = services.runtime.latest_runtime_state()
                return {"runtime_state": state}
            if command == "daily_audit":
                # Lancer un run audit autonome
                context_pack = services.api_runs.build_context_pack(
                    mode=ApiRunMode.AUDIT,
                    objective=args_dict.get("objective", "Audit quotidien"),
                    branch_name=f"codex/project-os-scheduled-audit-{datetime.now().strftime('%Y%m%d')}",
                    skill_tags=["audit", "scheduled"],
                )
                prompt = services.api_runs.render_prompt(context_pack_id=context_pack.context_pack_id)
                # Exécuter sans contrat (autonome)
                result = services.api_runs.execute(
                    context_pack_id=context_pack.context_pack_id,
                    prompt_template_id=prompt.prompt_template_id,
                )
                return {"run_id": result.get("result", {}).run_id if result.get("result") else None}
            if command == "cleanup_deliveries":
                max_age = args_dict.get("max_age_hours", 48)
                cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age)).isoformat()
                services.database.execute(
                    "UPDATE api_run_operator_deliveries SET status = 'expired' WHERE status = 'pending' AND created_at < ?",
                    (cutoff,),
                )
                return {"cleaned": True}
            return {"error": f"Unknown command: {command}"}

        results = services.scheduler.tick(executor=executor)
        print(json.dumps(results, indent=2, ensure_ascii=True))
        return 0
```

### 8. Intégrer le tick dans le plugin OpenClaw (polling)

Ajouter dans le plugin `index.js` un second polling pour le scheduler :

```javascript
// Après startOperatorDeliveryPolling(api):
function startSchedulerPolling(api) {
    const schedulerTick = async () => {
        try {
            const config = resolveConfig(api);
            const { result } = await runProjectOsJsonCommand(api, config, ["scheduler", "tick"], undefined);
            if (result.code !== 0) {
                api.logger.warn(`[project-os-gateway-adapter] scheduler tick failed: ${result.stderr || "no stderr"}`);
            }
        } catch (error) {
            api.logger.warn(`[project-os-gateway-adapter] scheduler tick error: ${String(error)}`);
        }
    };
    // Tick toutes les 60 secondes (les tâches elles-mêmes ont leur propre interval)
    setInterval(schedulerTick, 60000);
}
```

Dans `register(api)` :
```javascript
register(api) {
    startOperatorDeliveryPolling(api);
    startSchedulerPolling(api);          // NOUVEAU
    api.registerHook("message_received", async (event, ctx) => { ... });
}
```

### 9. Intégrer dans AppServices

```python
from .scheduler.service import SchedulerService

# Dans build_app_services() :
scheduler = SchedulerService(database=database, journal=journal, logger=logger)

# Dans AppServices :
scheduler: SchedulerService
```

## Contraintes absolues

- Le scheduler ne fait PAS d'appel API lui-même — il délègue à executor()
- Le guardian pre-spend check s'applique aux runs scheduled (pas de bypass budget)
- Les tâches scheduled doivent être loggées et traçables
- Le fondateur peut activer/désactiver n'importe quelle tâche
- daily_audit est DÉSACTIVÉ par défaut (le fondateur l'active quand il est prêt)
- Le tick est IDEMPOTENT — si appelé deux fois de suite, il ne lance pas deux fois la même tâche
- Si une tâche échoue, elle est simplement marquée "failed" et réessayée au prochain cycle

## Tests

1. `_ensure_default_tasks()` crée les 4 tâches par défaut
2. `get_due_tasks()` retourne uniquement les tâches dont next_run_at est passé
3. `mark_task_executed()` met à jour last_run_at et calcule next_run_at
4. `tick()` avec une tâche due → executor appelé → tâche marquée success
5. `tick()` avec une tâche due qui échoue → tâche marquée failed
6. `tick()` sans tâches dues → rien ne se passe
7. `enable_task()` / `disable_task()` bascule le flag enabled
8. `_compute_next_run()` pour interval = maintenant + interval_seconds
9. `_compute_next_run()` pour daily_at = demain si l'heure est passée
