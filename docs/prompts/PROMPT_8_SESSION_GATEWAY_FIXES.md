# Mission : Fixer les 3 bugs critiques Session State + Gateway

## Contexte

L'audit cross-model a trouvé 3 bugs P1 dans le flux Discord → Session State → Gateway.
Ces 3 bugs doivent être fixés ENSEMBLE car ils sont liés au même flux.

## Bug 1 : Ambiguïté non escaladée (session/state.py)

### Le problème

Dans `resolve_intent()` (ligne 285-354), quand le fondateur dit "go" et qu'il y a
à la fois UN contrat en attente ET UNE clarification en attente, le système répond
à la clarification et ignore le contrat. Il devrait escalader (retourner None).

La règle fondamentale : si le système n'est pas sûr à 100%, il NE DEVINE PAS.

### Le code actuel (lignes 292-309)

```python
if len(snapshot.pending_clarifications) == 1 and self._matches_approve(normalized_text):
    # → prend la clarification
elif len(snapshot.pending_contracts) == 1 and self._matches_approve(normalized_text):
    # → prend le contrat
```

Le problème : si `pending_clarifications == 1` ET `pending_contracts >= 1`, la première
branche gagne sans vérifier si le contrat existe aussi. Le fondateur voulait peut-être
approuver le contrat, pas la clarification.

### Le fix

Ajouter un garde d'ambiguïté AU DÉBUT de resolve_intent(), AVANT tout pattern matching :

```python
def resolve_intent(self, message_text: str, *, snapshot: SessionSnapshot | None = None) -> ResolvedIntent | None:
    normalized_text = self._normalize_text(message_text)
    snapshot = snapshot or self.load()

    # NOUVEAU : garde d'ambiguïté
    # Si un message simple (approve/reject) est reçu avec plusieurs choses en attente,
    # on ne peut pas savoir laquelle le fondateur vise → escalade vers Claude API
    total_pending = len(snapshot.pending_contracts) + len(snapshot.pending_clarifications)
    is_simple_message = self._matches_approve(normalized_text) or self._matches_reject(normalized_text)
    if is_simple_message and total_pending > 1:
        self.api_runs.logger.log(
            "INFO",
            "session_intent_ambiguous",
            message_text=message_text,
            pending_contracts=len(snapshot.pending_contracts),
            pending_clarifications=len(snapshot.pending_clarifications),
            reason="multiple_pending_items_with_simple_message",
        )
        return None  # escalade vers Claude API qui demandera une clarification

    # ... le reste du code existant continue inchangé ...
```

Note : les patterns "force" et "status" ne sont PAS affectés par ce garde car ils ont
une sémantique claire même avec plusieurs items en attente (force = guardian, status = snapshot).

### Tests à ajouter/modifier

```python
def test_ambiguity_escalation_approve_with_contract_and_clarification():
    """go + 1 contrat + 1 clarification → None (escalade)"""
    snapshot = SessionSnapshot(
        pending_contracts=[{"contract_id": "c1", ...}],
        pending_clarifications=[{"report_id": "r1", ...}],
    )
    result = session_state.resolve_intent("go", snapshot=snapshot)
    assert result is None  # escalade, pas de devinette

def test_ambiguity_escalation_reject_with_contract_and_clarification():
    """non + 1 contrat + 1 clarification → None (escalade)"""
    snapshot = SessionSnapshot(
        pending_contracts=[{"contract_id": "c1", ...}],
        pending_clarifications=[{"report_id": "r1", ...}],
    )
    result = session_state.resolve_intent("non", snapshot=snapshot)
    assert result is None

def test_single_contract_still_works():
    """go + 1 contrat + 0 clarification → approve_contract"""
    snapshot = SessionSnapshot(pending_contracts=[{"contract_id": "c1", ...}])
    result = session_state.resolve_intent("go", snapshot=snapshot)
    assert result.action == "approve_contract"
```

---

## Bug 2 : Approbation contrat sans lancement (gateway/service.py)

### Le problème

`_approve_contract()` (ligne 143-162) appelle `approve_run_contract()` mais ne lance PAS
`execute_run()`. Le fondateur voit "Execution prete" mais le run ne démarre jamais.

Le workflow attendu est : fondateur dit "go" → contrat approuvé → run exécuté automatiquement.
C'est documenté dans DAILY_OPERATOR_WORKFLOW.md et API_RUN_CONTRACT.md.

### Le code actuel (lignes 143-162)

```python
def _approve_contract(self, contract_id: str | None) -> dict[str, object]:
    if not contract_id:
        return {"action": "approve_contract", "status": "missing_target"}
    contract = self.session_state.api_runs.approve_run_contract(
        contract_id=contract_id,
        founder_decision="go",
        notes="Approved from Discord persistent session state.",
    )
    self.journal.append(...)
    return {
        "action": "approve_contract",
        "status": "approved",
        "contract_id": contract.contract_id,
        "branch_name": contract.branch_name,
        "estimated_cost_eur": contract.estimated_cost_eur,
    }
    # PROBLÈME : le run n'est jamais lancé !
```

### Le fix

Après l'approbation, lancer `execute_run()` :

```python
def _approve_contract(self, contract_id: str | None) -> dict[str, object]:
    if not contract_id:
        return {"action": "approve_contract", "status": "missing_target"}
    contract = self.session_state.api_runs.approve_run_contract(
        contract_id=contract_id,
        founder_decision="go",
        notes="Approved from Discord persistent session state.",
    )
    self.journal.append(
        "session_contract_approved",
        "gateway",
        {"contract_id": contract.contract_id, "branch_name": contract.branch_name},
    )

    # NOUVEAU : lancer le run après approbation
    run_result: dict[str, object] = {}
    try:
        payload = self.session_state.api_runs.execute_run(contract_id=contract.contract_id)
        result = payload.get("result")
        run_result = {
            "run_launched": True,
            "run_id": getattr(result, "run_id", None),
            "run_status": getattr(result, "status", None),
            "estimated_cost_eur": getattr(result, "estimated_cost_eur", None),
        }
        self.journal.append(
            "session_contract_run_launched",
            "gateway",
            {
                "contract_id": contract.contract_id,
                "run_id": getattr(result, "run_id", None),
            },
        )
    except Exception as exc:
        run_result = {"run_launched": False, "run_error": str(exc)}
        self.journal.append(
            "session_contract_run_failed",
            "gateway",
            {"contract_id": contract.contract_id, "error": str(exc)},
        )

    return {
        "action": "approve_contract",
        "status": "approved_and_launched" if run_result.get("run_launched") else "approved",
        "contract_id": contract.contract_id,
        "branch_name": contract.branch_name,
        "estimated_cost_eur": contract.estimated_cost_eur,
        "run_id": run_result.get("run_id"),
        **run_result,
    }
```

Mettre aussi à jour le message summary :

```python
# Dans _session_reply_summary(), remplacer la ligne approve_contract :
if resolved.action == "approve_contract":
    branch = str(action_result.get("branch_name") or "ce lot")
    if action_result.get("run_launched"):
        return f"{branch}: contrat approuve. Run lance."
    return f"{branch}: contrat approuve. Lancement en attente."
```

---

## Bug 3 : Side effects avant persist (gateway/service.py)

### Le problème

Dans `dispatch_event()` lignes 85-111, l'ordre est :
1. `_execute_resolved_intent(resolved)` → side effects (DB writes, approbation, lancement)
2. `_persist_channel_event(event, candidate)` → persist l'event entrant
3. `_persist_dispatch(dispatch)` → persist le dispatch

Si l'étape 2 ou 3 échoue, le contrat est approuvé et le run est lancé MAIS il n'y a
aucune trace de l'event Discord qui l'a déclenché. Ça casse l'auditabilité.

### Le fix

Inverser l'ordre — persist AVANT les side effects :

```python
        snapshot = self.session_state.load()
        resolved = self.session_state.resolve_intent(event.message.text, snapshot=snapshot)
        if resolved is not None:
            # NOUVEAU : persister l'event entrant AVANT les side effects
            self._persist_channel_event(event, candidate)
            self._persist_promotion(candidate, promotion)

            # Ensuite exécuter les side effects
            action_result = self._execute_resolved_intent(resolved)
            promoted_memory_ids = self._apply_selective_sync(candidate, promotion)
            reply = self._build_session_reply(event, envelope.envelope_id, resolved, action_result)
            dispatch = self._build_session_dispatch(
                event=event,
                envelope=envelope,
                resolved=resolved,
                action_result=action_result,
                promoted_memory_ids=promoted_memory_ids,
                candidate_id=candidate.candidate_id,
                promotion_decision_id=promotion.promotion_decision_id,
                reply=reply,
                channel_class=channel_class,
                human_artifacts=human_artifacts,
            )
            # Persist le dispatch après
            self._persist_dispatch(dispatch)
            self.journal.append(
                "gateway_session_dispatch_completed",
                "gateway",
                {
                    "dispatch_id": dispatch.dispatch_id,
                    "channel_event_id": event.event_id,
                    "resolved_action": resolved.action,
                    "target_id": resolved.target_id,
                    "promoted_memory_count": len(promoted_memory_ids),
                },
            )
            return dispatch
```

## Contraintes

- Ne PAS toucher au flux non-session (le else qui continue vers router.envelope_to_intent)
- Ne PAS modifier les dataclasses dans models.py
- Logger chaque changement important
- Les tests existants doivent toujours passer
