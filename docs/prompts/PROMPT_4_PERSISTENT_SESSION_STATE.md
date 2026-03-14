# Mission : Implémenter PersistentSessionState — Mémoire de session continue

## Vision du projet

Project OS est un agent autonome persistant. Quand le fondateur dit "go" sur Discord,
le système doit savoir IMMÉDIATEMENT ce qui est en attente — sans appel API.

Le principe : la DB SQLite EST la mémoire. Les appels API sont pour PENSER, pas pour SE SOUVENIR.

Référence : docs/decisions/0013-dual-model-operating-model.md (section Persistent Session State)

## Ce qui existe déjà

### Base de données (database.py) — tables existantes pertinentes

```sql
-- Runs en cours avec statut
api_run_results(run_id, run_request_id, model, mode, status, estimated_cost_eur, created_at, updated_at)

-- Contrats en attente de décision fondateur
api_run_contracts(contract_id, status, founder_decision, founder_decision_at, objective, estimated_cost_eur)

-- Clarifications en attente de réponse
api_run_clarification_reports(report_id, run_id, cause, question_for_founder, requires_reapproval)

-- Messages Discord en attente d'envoi
api_run_operator_deliveries(delivery_id, status, channel_hint, payload, next_attempt_at)

-- Budget du jour
api_run_results WHERE created_at >= today AND status != 'failed' → SUM(estimated_cost_eur)

-- Sessions de mission
mission_runs(mission_run_id, intent_id, objective, status, created_at)

-- Approbations en attente
approval_records(approval_id, action_name, risk_class, status, created_at)
```

### Gateway inbound existant (gateway/service.py)

Le `GatewayService.dispatch_event()` reçoit un `ChannelEvent` depuis Discord via OpenClaw.
Il crée un `OperatorEnvelope`, le route via `MissionRouter`, et retourne un `GatewayDispatchResult`.

PROBLÈME ACTUEL : dispatch_event() traite chaque message comme un message NEUF.
Il ne sait pas si le fondateur répond à une clarification en cours, approuve un contrat,
ou démarre une nouvelle demande. C'est ce trou que PersistentSessionState comble.

### Modèles existants (models.py)

```python
class ChannelEvent:
    event_id: str
    surface: str           # "discord"
    event_type: str        # "message.received"
    message: OperatorMessage
    raw_payload: dict
    created_at: str

class OperatorMessage:
    message_id: str
    actor_id: str
    channel: str           # nom du channel Discord
    text: str
    thread_ref: ConversationThreadRef
    attachments: list[MessageAttachment]
    metadata: dict

class ConversationThreadRef:
    surface: str
    provider: str
    originating_channel: str
    parent_thread_id: str | None
    guild_id: str | None
    channel_name: str | None
    thread_id: str | None
```

### AppServices factory (services.py)

```python
@dataclass(slots=True)
class AppServices:
    config: RuntimeConfig
    paths: ProjectPaths
    database: CanonicalDatabase
    journal: LocalJournal
    memory: MemoryStore
    learning: LearningService
    runtime: RuntimeStore
    router: MissionRouter
    gateway: GatewayService
    openclaw: OpenClawLiveService
    orchestration: CanonicalMissionGraph
    api_runs: ApiRunService
    logger: StructuredLogger
```

## Ce que tu dois faire

### 1. Créer le fichier `src/project_os_core/session/state.py`

```python
class PersistentSessionState:
    """Mémoire continue du système — sait toujours ce qui est en cours."""

    def __init__(self, *, database: CanonicalDatabase, api_runs: ApiRunService) -> None:
        self.database = database
        self.api_runs = api_runs
```

### 2. Méthode `load()` — snapshot instantané de l'état du système

```python
def load(self) -> SessionSnapshot:
    """Charge l'état complet du système depuis SQLite. 0 appel API."""
```

Retourne un `SessionSnapshot` (dataclass) contenant :

```python
@dataclass(slots=True)
class SessionSnapshot:
    # Runs actifs (status = RUNNING)
    active_runs: list[dict]       # [{run_id, mode, branch_name, started_at}]

    # Clarifications en attente de réponse du fondateur
    pending_clarifications: list[dict]  # [{report_id, run_id, question, created_at}]

    # Contrats en attente d'approbation
    pending_contracts: list[dict]  # [{contract_id, objective, estimated_cost, created_at}]

    # Approbations en attente
    pending_approvals: list[dict]  # [{approval_id, action_name, risk_class, created_at}]

    # Messages Discord en attente d'envoi
    pending_deliveries: int        # COUNT

    # Budget du jour
    daily_spend_eur: float
    daily_budget_limit_eur: float

    # Dernière activité
    last_run_completed_at: str | None
    last_founder_message_at: str | None

    # Missions en cours
    active_missions: list[dict]    # [{mission_run_id, objective, status, created_at}]

    created_at: str  # timestamp du snapshot
```

Implémentation : 5-6 requêtes SQL simples, toutes en lecture seule.

### 3. Méthode `resolve_intent()` — résolution d'intention SANS appel API

```python
def resolve_intent(self, message_text: str, *, snapshot: SessionSnapshot | None = None) -> ResolvedIntent | None:
    """Essaie de résoudre l'intention du message par pattern matching + contexte.

    Retourne ResolvedIntent si résolu (0 appel API).
    Retourne None si ambiguë (escalade vers Claude API nécessaire).
    """
```

Logique :

```python
@dataclass(slots=True)
class ResolvedIntent:
    action: str                    # "approve_contract", "answer_clarification", "approve_override", etc.
    target_id: str | None          # contract_id, report_id, approval_id
    confidence: float              # 0.0-1.0
    raw_message: str
    metadata: dict
```

**Patterns d'intention** (le fondateur parle comme il veut) :

```python
APPROVE_PATTERNS = {"go", "vas-y", "envoie", "lance", "c'est bon", "ouais", "ok", "oui",
                    "allez", "fonce", "send", "let's go", "yep", "valide", "on lance"}
REJECT_PATTERNS = {"stop", "non", "bof", "pas maintenant", "annule", "cancel", "nah",
                   "attend", "attends", "pas encore", "pas la"}
FORCE_PATTERNS = {"force", "quand meme", "quand même", "override", "je sais", "tant pis",
                  "on s'en fout", "yolo"}
STATUS_PATTERNS = {"status", "quoi de neuf", "ou on en est", "où on en est", "ca donne quoi",
                   "ça donne quoi", "résumé", "resume"}
```

**Résolution contextuelle** (la clé — le contexte détermine l'action) :

```python
text = message_text.strip().lower()
snapshot = snapshot or self.load()

# 1. Si UNE SEULE clarification en attente et le fondateur approuve → répondre à cette clarification
if len(snapshot.pending_clarifications) == 1 and self._matches_approve(text):
    return ResolvedIntent(
        action="answer_clarification",
        target_id=snapshot.pending_clarifications[0]["report_id"],
        confidence=0.95,
        raw_message=message_text,
        metadata={"answer": "approved"},
    )

# 2. Si UN SEUL contrat en attente et le fondateur approuve → approuver ce contrat
if len(snapshot.pending_contracts) == 1 and self._matches_approve(text):
    return ResolvedIntent(
        action="approve_contract",
        target_id=snapshot.pending_contracts[0]["contract_id"],
        confidence=0.95,
        raw_message=message_text,
        metadata={},
    )

# 3. Si le fondateur dit "force" et qu'il y a une clarification guardian → override
if self._matches_force(text) and any(
    c.get("metadata", {}).get("guardian_blocking_reason") for c in snapshot.pending_clarifications
):
    guardian_clarification = next(
        c for c in snapshot.pending_clarifications
        if c.get("metadata", {}).get("guardian_blocking_reason")
    )
    return ResolvedIntent(
        action="guardian_override",
        target_id=guardian_clarification["report_id"],
        confidence=0.90,
        raw_message=message_text,
        metadata={"override": True},
    )

# 4. Si le fondateur demande le status → retourner le snapshot
if self._matches_status(text):
    return ResolvedIntent(
        action="status_request",
        target_id=None,
        confidence=0.95,
        raw_message=message_text,
        metadata={},
    )

# 5. Si le fondateur refuse et qu'il y a UN truc en attente → refuser
if self._matches_reject(text):
    if len(snapshot.pending_contracts) == 1:
        return ResolvedIntent(action="reject_contract", target_id=snapshot.pending_contracts[0]["contract_id"], ...)
    if len(snapshot.pending_clarifications) == 1:
        return ResolvedIntent(action="reject_clarification", target_id=snapshot.pending_clarifications[0]["report_id"], ...)

# 6. AMBIGUÏTÉ : plusieurs trucs en attente, ou message non reconnu → None (escalade API)
return None
```

### 4. Méthode `build_context_brief()` — briefing compact pour escalade API

```python
def build_context_brief(self, *, snapshot: SessionSnapshot | None = None) -> str:
    """Construit un résumé compact (~500 tokens) de l'état pour Claude API.

    Utilisé uniquement quand resolve_intent() retourne None (message ambigu).
    """
```

Le brief contient :
- Nombre de runs actifs et leurs modes/branches
- Clarifications en attente avec les questions
- Contrats en attente avec les objectifs et coûts
- Budget du jour (dépensé / limite)
- Dernière activité

Format retourné : texte structuré, pas JSON (c'est un prompt pour Claude).

### 5. Intégrer dans GatewayService.dispatch_event()

AVANT la ligne `intent = self.router.envelope_to_intent(envelope)`, ajouter :

```python
# PersistentSessionState : essayer de résoudre l'intention sans API
resolved = self.session_state.resolve_intent(event.message.text)
if resolved is not None:
    # Exécuter l'action directement
    action_result = self._execute_resolved_intent(resolved)
    # Construire un dispatch result simplifié (pas de routing, pas d'API)
    return self._build_session_dispatch(event, resolved, action_result)

# Si non résolu → continuer le flux normal (routing → API)
```

### 6. Méthode `_execute_resolved_intent()` dans GatewayService

```python
def _execute_resolved_intent(self, resolved: ResolvedIntent) -> dict:
    if resolved.action == "approve_contract":
        return self._approve_contract(resolved.target_id)
    if resolved.action == "answer_clarification":
        return self._answer_clarification(resolved.target_id, resolved.metadata.get("answer"))
    if resolved.action == "guardian_override":
        return self._guardian_override(resolved.target_id)
    if resolved.action == "status_request":
        snapshot = self.session_state.load()
        return {"snapshot": to_jsonable(snapshot)}
    if resolved.action == "reject_contract":
        return self._reject_contract(resolved.target_id)
    # ... etc
    return {"action": resolved.action, "status": "unhandled"}
```

### 7. Ajouter dans AppServices et build_app_services()

```python
# Dans AppServices:
session_state: PersistentSessionState

# Dans build_app_services():
from .session.state import PersistentSessionState
session_state = PersistentSessionState(database=database, api_runs=api_runs)
# Passer session_state au gateway
gateway = GatewayService(database=database, journal=journal, router=router, memory=memory, session_state=session_state)
```

### 8. Créer le fichier `src/project_os_core/session/__init__.py`

Fichier vide ou avec `from .state import PersistentSessionState`.

### 9. Ajouter la table `session_snapshots` dans database.py (optionnel mais recommandé)

```sql
CREATE TABLE IF NOT EXISTS session_snapshots(
    snapshot_id TEXT PRIMARY KEY,
    active_runs_json TEXT NOT NULL DEFAULT '[]',
    pending_clarifications_json TEXT NOT NULL DEFAULT '[]',
    pending_contracts_json TEXT NOT NULL DEFAULT '[]',
    pending_approvals_json TEXT NOT NULL DEFAULT '[]',
    pending_deliveries INTEGER NOT NULL DEFAULT 0,
    daily_spend_eur REAL NOT NULL DEFAULT 0.0,
    active_missions_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
)
```

## Contraintes absolues

- `load()` et `resolve_intent()` font ZÉRO appel API — uniquement des SELECT SQLite
- Le fondateur ne doit jamais voir un message du type "de quoi tu parles ?" s'il n'y a qu'une seule chose en attente
- Les patterns sont en minuscules et normalisés (strip accents optionnel)
- `resolve_intent()` retourne None quand il y a ambiguïté — JAMAIS une mauvaise action
- Confidence < 0.70 → retourner None (escalade)
- Logger chaque résolution et chaque escalade

## Tests

1. `load()` retourne un snapshot complet avec les bonnes données
2. Un seul contrat en attente + "go" → approve_contract avec confidence 0.95
3. Une seule clarification + "ouais" → answer_clarification
4. "status" → status_request
5. Deux contrats en attente + "go" → None (ambiguïté, escalade)
6. Message non reconnu → None
7. "force" avec clarification guardian → guardian_override
8. Budget correct dans le snapshot
