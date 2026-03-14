# Mission : Fixer les bugs OpenClaw polling + Chain dead code + Chain guardian bypass

## Bug 4 : Scheduler polling casse les tests (index.js)

### Le problème

`startSchedulerPolling()` (ligne 293-318 de index.js) installe un `setInterval(60000)`
permanent. Quand le harness de test appelle `plugin.register(api)`, le process Node ne
termine jamais → timeout dans `test_openclaw_live.py`.

### Le code actuel

```javascript
function startSchedulerPolling(api) {
  let busy = false;
  const tick = async () => { ... };
  setTimeout(() => { void tick(); }, 2500);
  setInterval(() => { void tick(); }, 60000);  // ← ne s'arrête jamais
}

const plugin = {
  register(api) {
    startOperatorDeliveryPolling(api);
    startSchedulerPolling(api);  // ← toujours activé
    api.registerHook("message_received", ...);
  },
};
```

### Le fix

Ajouter un flag `enableSchedulerPolling` dans la config, désactivé quand on est en mode
test/replay. Même pattern pour `startOperatorDeliveryPolling` (qui a le même problème
potentiel mais ne timeout pas car son interval est plus court).

```javascript
function resolveConfig(api) {
  const raw = api.pluginConfig && typeof api.pluginConfig === "object" ? api.pluginConfig : {};
  // ... tout le code existant ...

  // NOUVEAU : flag pour désactiver les pollers en mode test
  const enablePolling = raw.enablePolling !== false;  // true par défaut, false pour les tests

  return {
    // ... tous les champs existants ...
    enablePolling,
  };
}
```

Modifier `register()` :

```javascript
register(api) {
    const config = resolveConfig(api);
    if (config.enablePolling) {
      startOperatorDeliveryPolling(api);
      startSchedulerPolling(api);
    } else {
      api.logger.info("[project-os-gateway-adapter] polling disabled (enablePolling=false)");
    }
    api.registerHook("message_received", async (event, ctx) => {
      // ... inchangé ...
    });
  },
```

Aussi, stocker les interval IDs pour pouvoir les nettoyer si besoin :

```javascript
function startSchedulerPolling(api) {
  let busy = false;
  const tick = async () => {
    if (busy) return;
    busy = true;
    try {
      const config = resolveConfig(api);
      const { result } = await runProjectOsJsonCommand(api, config, ["scheduler", "tick"], undefined);
      if (result.code !== 0) {
        api.logger.warn(`[project-os-gateway-adapter] scheduler tick failed: ${result.stderr || "no stderr"}`);
      }
    } catch (error) {
      api.logger.warn(`[project-os-gateway-adapter] scheduler tick error: ${String(error)}`);
    } finally {
      busy = false;
    }
  };
  const initialId = setTimeout(() => { void tick(); }, 2500);
  const intervalId = setInterval(() => { void tick(); }, 60000);

  // Exposer pour cleanup en test
  if (!api._projectOsIntervals) api._projectOsIntervals = [];
  api._projectOsIntervals.push(initialId, intervalId);
}
```

Même chose pour `startOperatorDeliveryPolling()` — stocker les IDs.

---

## Bug 5 : Dead code dans chain.py (ligne 151)

### Le problème

Dans `advance_chain()` (ligne 131-171 de mission/chain.py), après avoir vérifié que
`last_status` est COMPLETED ou REVIEWED (ligne 131), le code vérifie ensuite :

```python
if current_step.depends_on_previous and last_status not in {ApiRunStatus.COMPLETED.value, ApiRunStatus.REVIEWED.value}:
    return {"status": "running", "action": "wait", "chain_id": chain.chain_id}
```

Cette condition est TOUJOURS fausse car on est dans le bloc `if last_status in {COMPLETED, REVIEWED}`.
C'est du dead code qui rend le flux plus confus qu'il ne devrait l'être.

### Le code actuel (lignes 131-171)

```python
if last_status in {ApiRunStatus.COMPLETED.value, ApiRunStatus.REVIEWED.value}:
    next_index = chain.current_step_index + 1
    if next_index >= len(chain.steps):
        # chain terminée
        ...
    next_step = chain.steps[next_index]
    if current_step.depends_on_previous and last_status not in {ApiRunStatus.COMPLETED.value, ApiRunStatus.REVIEWED.value}:
        return {"status": "running", "action": "wait", "chain_id": chain.chain_id}  # DEAD CODE
    advanced = self._update_chain(...)
    launched = self._launch_step(...)
    return {...}
```

### Le fix

Supprimer la condition morte (lignes 151-152). Le code après `if next_index >= len(chain.steps):`
doit directement passer à `_update_chain` et `_launch_step` :

```python
if last_status in {ApiRunStatus.COMPLETED.value, ApiRunStatus.REVIEWED.value}:
    next_index = chain.current_step_index + 1
    if next_index >= len(chain.steps):
        completed = self._update_chain(...)
        self.journal.append(...)
        return {"status": "completed", ...}
    next_step = chain.steps[next_index]
    # SUPPRIMÉ : condition morte (depends_on_previous check ici était toujours false)
    advanced = self._update_chain(
        chain,
        current_step_index=next_index,
        total_cost_eur=self._compute_total_cost_eur(chain.chain_id),
    )
    launched = self._launch_step(
        chain=advanced,
        step=next_step,
        previous_output=last_run.get("structured_output"),
        response_runner=response_runner,
    )
    return {
        "status": "running",
        "action": "launch_step",
        ...
    }
```

Note : `depends_on_previous` est déjà géré implicitement par le fait que `advance_chain()`
est appelé APRÈS que le step courant soit terminé. Si le step n'est pas terminé, on retourne
`{"action": "wait"}` à la ligne 204.

---

## Bug 6 : Chain bypass le Guardian (chain.py)

### Le problème

Dans `_launch_step()` (ligne 270-346), les runs de chain sont auto-approuvés :

```python
self.api_runs.approve_run_contract(
    contract_id=contract.contract_id,
    founder_decision="go",
    notes=f"Auto-approved from mission chain {chain.chain_id} step {step.step_index}.",
)
payload = self.api_runs.execute_run(contract_id=contract.contract_id, ...)
```

Le problème : `execute_run()` contient le guardian pre-spend check. MAIS le contrat est
déjà approuvé, donc si le guardian bloque, le système crée une clarification pour un contrat
déjà marqué "approved". C'est incohérent mais pas catastrophique.

Le VRAI problème serait si `execute_run()` ne passait pas par le guardian du tout pour les
chains. Vérifions : `execute_run()` appelle `_guardian_pre_spend_check()` qui vérifie le
budget et les boucles. Si le guardian bloque, le run passe en CLARIFICATION_REQUIRED.

### Le fix

Ajouter un metadata flag pour identifier les runs de chain, et dans `_launch_step()`,
catch le cas où le guardian bloque :

```python
def _launch_step(self, *, chain, step, previous_output, response_runner):
    # ... code existant jusqu'à execute_run() ...
    payload = self.api_runs.execute_run(
        contract_id=contract.contract_id,
        metadata=step_metadata,
        response_runner=response_runner,
        mission_chain_id=chain.chain_id,
        mission_step_index=step.step_index,
    )
    result = payload.get("result")

    # NOUVEAU : si le guardian a bloqué ce step, mettre la chain en pause
    if result and hasattr(result, "status"):
        from ..models import ApiRunStatus
        if result.status == ApiRunStatus.CLARIFICATION_REQUIRED:
            guardian_blocked = result.metadata.get("guardian_blocked", False)
            if guardian_blocked:
                self.pause_chain(chain.chain_id)
                self.journal.append(
                    "mission_chain_guardian_blocked",
                    "mission_chain",
                    {
                        "chain_id": chain.chain_id,
                        "step_index": step.step_index,
                        "blocking_reason": result.metadata.get("blocking_reason"),
                    },
                )

    # ... reste du code existant ...
```

Cela garantit que :
- Le guardian fonctionne normalement sur chaque step de chain
- Si le guardian bloque un step, la chain est mise en pause automatiquement
- Le fondateur recevra la notification de clarification via Discord
- Il pourra overrider ou attendre, et la chain reprendra

## Contraintes

- Ne PAS supprimer les features existantes, uniquement fixer les bugs
- Le plugin OpenClaw doit toujours fonctionner en mode production (polling activé par défaut)
- Les tests existants doivent passer (le fix polling est là pour ça)
- Logger chaque décision importante
