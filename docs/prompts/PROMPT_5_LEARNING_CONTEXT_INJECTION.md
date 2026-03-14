# Mission : Implémenter Learning Context Injection — Les leçons remontent dans les runs

## Vision du projet

Project OS apprend de ses erreurs et succès. Le LearningService enregistre déjà des signaux
(patch accepté/rejeté, boucles détectées, decisions confirmées, refresh recommendations).
MAIS ces leçons ne remontent PAS dans les context packs des runs suivants.

Un run qui fait la même erreur 3 fois = le système n'apprend rien.
Cette mission ferme la boucle : les leçons passées sont injectées dans les prochains runs.

## Ce qui existe déjà

### LearningService (learning/service.py — 338 lignes)

Méthodes existantes qui ÉCRIVENT des signaux :

```python
class LearningService:
    def record_decision(*, status, scope, summary, source_run_id, metadata) -> DecisionRecord
    def record_signal(*, kind, severity, summary, source_ids, metadata) -> LearningSignal
    def record_loop_signal(*, repeated_pattern, impacted_area, recommended_reset, source_ids) -> LoopSignal
    def record_noise_signal(*, run_id, reason, evidence) -> NoiseSignal
    def recommend_refresh(*, cause, context_to_reload, next_step, source_ids) -> RefreshRecommendation
    def record_dataset_candidate(*, source_type, quality_score, export_ready, source_ids) -> DatasetCandidate
    def record_eval_candidate(*, scenario, target_system, expected_behavior, source_ids) -> EvalCandidate
```

AUCUNE méthode ne RELIT ces signaux pour les injecter dans un nouveau run.

### Tables DB existantes

```sql
-- Décisions confirmées/changées (leçons stratégiques)
decision_records(decision_record_id, status, scope, summary, source_run_id, metadata_json, created_at)

-- Signaux d'apprentissage (succès/erreurs/dérives)
learning_signals(signal_id, kind, severity, summary, source_ids_json, metadata_json, created_at)

-- Boucles détectées (erreurs répétées)
loop_signals(loop_signal_id, repeated_pattern, impacted_area, recommended_reset, source_ids_json, created_at)

-- Recommendations de rafraîchissement
refresh_recommendations(refresh_recommendation_id, cause, context_to_reload_json, next_step, source_ids_json, created_at)
```

### ApiRunService.build_context_pack() (service.py ligne 90)

```python
def build_context_pack(
    self, *, mode, objective, branch_name, skill_tags,
    target_profile=None, source_paths=None, constraints=None, acceptance_criteria=None, metadata=None,
) -> ContextPack:
    # ... construit les source_refs, repo_state, runtime_facts, constraints, acceptance_criteria
    context_pack = ContextPack(
        context_pack_id=new_id("context_pack"),
        mode=mode,
        objective=objective.strip(),
        branch_name=resolved_branch,
        source_refs=[self._read_context_source(path) for path in selected_sources],
        repo_state=self._repo_state(target_branch=resolved_branch),
        runtime_facts=self._runtime_facts(),
        constraints=list(constraints or self._default_constraints()),
        acceptance_criteria=list(acceptance_criteria or self._default_acceptance_criteria(mode)),
        skill_tags=normalized_skills,
        metadata=dict(metadata or {}),
    )
```

Le `runtime_facts` est un dict libre — c'est là qu'on injecte les leçons.

### ContextPack (models.py ligne 835)

```python
@dataclass(slots=True)
class ContextPack:
    context_pack_id: str
    mode: ApiRunMode
    objective: str
    branch_name: str
    target_profile: str | None = None
    source_refs: list[ContextSource] = field(default_factory=list)
    repo_state: dict[str, Any] = field(default_factory=dict)
    runtime_facts: dict[str, Any] = field(default_factory=dict)  # <-- ICI
    constraints: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    skill_tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
```

### _runtime_facts() existant (service.py)

```python
def _runtime_facts(self) -> dict[str, Any]:
    return {
        "repo_root": str(self.repo_root),
        "current_branch": self._current_branch(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
```

## Ce que tu dois faire

### 1. Ajouter `gather_learning_context()` dans LearningService

```python
def gather_learning_context(
    self,
    *,
    mode: str,
    branch_name: str,
    objective: str,
    limit: int = 10,
    lookback_hours: int = 72,
) -> dict[str, Any]:
    """Collecte les leçons pertinentes pour un nouveau run.

    Retourne un dict prêt à injecter dans runtime_facts["learning_context"].
    0 appel API — uniquement des SELECT SQLite.
    """
```

Contenu à collecter :

**a) Décisions récentes sur le même scope** :
```sql
SELECT * FROM decision_records
WHERE (scope LIKE '%' || ? || '%' OR scope LIKE '%' || ? || '%')
AND created_at >= ?
ORDER BY created_at DESC LIMIT ?
```
(paramètres : mode, branch_name, lookback cutoff, limit)

**b) Signaux de sévérité haute sur la même branche** :
```sql
SELECT * FROM learning_signals
WHERE severity IN ('high', 'critical')
AND created_at >= ?
ORDER BY created_at DESC LIMIT ?
```

**c) Boucles détectées sur la même zone** :
```sql
SELECT * FROM loop_signals
WHERE impacted_area LIKE '%' || ? || '%'
AND created_at >= ?
ORDER BY created_at DESC LIMIT 3
```

**d) Refresh recommendations actives** :
```sql
SELECT * FROM refresh_recommendations
WHERE created_at >= ?
ORDER BY created_at DESC LIMIT 3
```

Retourne :
```python
{
    "decisions": [{"scope": ..., "summary": ..., "status": ..., "created_at": ...}],
    "high_severity_signals": [{"kind": ..., "summary": ..., "severity": ..., "created_at": ...}],
    "detected_loops": [{"pattern": ..., "area": ..., "recommended_reset": ...}],
    "refresh_recommendations": [{"cause": ..., "next_step": ...}],
    "summary": "3 decisions, 1 high signal, 0 loops, 1 refresh recommendation in last 72h.",
}
```

### 2. Modifier `_runtime_facts()` dans ApiRunService

```python
def _runtime_facts(self) -> dict[str, Any]:
    return {
        "repo_root": str(self.repo_root),
        "current_branch": self._current_branch(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
```

Ajouter l'injection des leçons. Le problème : `_runtime_facts()` n'a pas le contexte (mode, branch_name).
Solution : soit ajouter les paramètres, soit injecter dans `build_context_pack()` directement.

**Option recommandée** : injecter dans `build_context_pack()` après la construction :

```python
def build_context_pack(self, *, mode, objective, branch_name, ...):
    # ... construction existante ...
    context_pack = ContextPack(...)

    # NOUVEAU : injection des leçons
    try:
        learning_context = self.learning.gather_learning_context(
            mode=mode.value,
            branch_name=resolved_branch,
            objective=objective,
        )
        context_pack.runtime_facts["learning_context"] = learning_context
    except Exception as exc:
        self.logger.log("WARNING", "learning_injection_failed", error=str(exc))
        context_pack.runtime_facts["learning_context"] = {"error": str(exc), "decisions": [], "high_severity_signals": []}

    # ... persist, journal, return ...
```

### 3. Modifier le prompt template pour utiliser les leçons

Dans `_render_prompt_text()`, si `runtime_facts` contient `learning_context`,
ajouter une section au prompt :

```python
learning = context_pack.runtime_facts.get("learning_context", {})
if learning.get("decisions") or learning.get("high_severity_signals") or learning.get("detected_loops"):
    prompt_parts.append("\n## Learning Context (lessons from recent runs)\n")
    if learning.get("detected_loops"):
        prompt_parts.append("⚠️ DETECTED LOOPS (do NOT repeat these patterns):")
        for loop in learning["detected_loops"]:
            prompt_parts.append(f"  - Pattern: {loop['pattern']}")
            prompt_parts.append(f"    Reset: {loop['recommended_reset']}")
    if learning.get("high_severity_signals"):
        prompt_parts.append("\nHigh-severity signals from recent runs:")
        for signal in learning["high_severity_signals"]:
            prompt_parts.append(f"  - [{signal['kind']}] {signal['summary']}")
    if learning.get("decisions"):
        prompt_parts.append("\nRecent confirmed decisions:")
        for decision in learning["decisions"]:
            prompt_parts.append(f"  - [{decision['status']}] {decision['scope']}: {decision['summary']}")
    if learning.get("refresh_recommendations"):
        prompt_parts.append("\nRefresh recommendations:")
        for rec in learning["refresh_recommendations"]:
            prompt_parts.append(f"  - Cause: {rec['cause']}")
            prompt_parts.append(f"    Next step: {rec['next_step']}")
```

### 4. Vérifier `_render_prompt_text()` existant

Cherche la méthode `_render_prompt_text` dans service.py. Elle utilise probablement
`context_pack.runtime_facts` quelque part. Insère la section learning AVANT la section output_contract.

## Contraintes absolues

- `gather_learning_context()` fait ZÉRO appel API — uniquement des SELECT
- Si aucune leçon n'existe → le dict est vide, le run continue normalement
- Si la DB a un problème → catch l'exception, log un warning, continuer sans leçons
- Les leçons injectées ne doivent pas dépasser ~1000 tokens (limiter les résultats)
- Le prompt de learning est en anglais technique (c'est pour GPT, pas pour le fondateur)
- Logger l'injection : combien de leçons injectées, de quel type

## Tests

1. `gather_learning_context()` avec des données → retourne le bon nombre de leçons
2. `gather_learning_context()` sans données → retourne un dict vide
3. `build_context_pack()` injecte learning_context dans runtime_facts
4. Le prompt rendu contient la section "Learning Context" quand il y a des leçons
5. Le prompt rendu ne contient PAS la section quand il n'y a pas de leçons
6. Si `gather_learning_context()` raise → le context pack est quand même créé
