# Claude Opus 4.6 Audit Triage - 2026-03-13

Note historique: ce document capture l'etat du repo avant le lot 1 de nettoyage d'identite. Les references a `Codex` sont conservees comme trace d'audit.

Ce document ne reprend pas aveuglement l'audit externe.
Il fige ce qui a ete reverifie dans le code reel de `Project OS` au 13 mars 2026.

## Verdict global

L'audit est utile.

Il voit juste sur plusieurs faiblesses de securite et d'integrite de donnees.
Il exagere ou date sur quelques points de couverture et d'etat du projet.

Le bon usage de cet audit n'est pas:

- de tout casser pour repartir
- ni de le traiter comme parole d'evangile

Le bon usage est:

- prendre ses vrais `P0/P1`
- les revalider localement
- les convertir en lot de hardening explicite
- utiliser l'API grande fenetre pour produire un `patch_plan` fort
- garder `Codex` en inspection, integration et verification

## Points critiques confirmes

### 1. Bypass approval / budget via metadonnees operateur

Confirme dans:

- `src/project_os_core/router/service.py`

Constat:

- `founder_approved` vient aujourd'hui de `intent.metadata`
- `daily_spend_estimate_eur` et `monthly_spend_estimate_eur` viennent aussi de `intent.metadata`

Impact:

- un payload client ou operateur trop permissif peut influencer la gate approval
- le budget n'est pas encore derive de la verite canonique en base

Decision:

- a corriger en priorite `P0`

### 2. Cle OpenAI poussee dans `os.environ`

Confirme dans:

- `src/project_os_core/memory/adapter.py`

Constat:

- l'adaptateur `OpenMemory` ecrit `OPENAI_API_KEY` dans l'environnement global du process

Impact:

- fuite de surface vers sous-processus et libs tierces

Decision:

- a corriger en priorite `P0`

### 3. Parsing enum non protege sur input externe

Confirme dans:

- `src/project_os_core/gateway/openclaw_adapter.py`

Constat:

- `_as_risk_class()` fait `ActionRiskClass(text)` sans garde

Impact:

- un payload invalide peut faire remonter une erreur non geree

Decision:

- a corriger `P0`

### 4. Secret Infisical passe en argument CLI

Confirme dans:

- `src/project_os_core/secrets.py`

Constat:

- `push_to_infisical()` passe `NAME=value` sur la ligne de commande

Impact:

- visibilite possible dans les process Windows et certains journaux systeme

Decision:

- a corriger `P0`

### 5. Multi-ecritures non transactionnelles

Confirme sur plusieurs zones:

- `src/project_os_core/gateway/service.py`
- `src/project_os_core/memory/store.py`
- `src/project_os_core/learning/service.py`
- `src/project_os_core/orchestration/graph.py`
- `src/project_os_core/runtime/journal.py`

Constat:

- plusieurs operations ecrivent dans plusieurs tables ou dans fichier + DB sans transaction unifiee

Impact:

- etats partiels en cas de crash ou d'erreur a mi-course

Decision:

- a corriger `P1`

### 6. `INSERT OR REPLACE` trop large

Confirme dans de nombreux modules:

- `gateway`
- `router`
- `runtime`
- `learning`
- `orchestration`
- `api_runs`

Impact:

- ecrasement silencieux possible
- mauvais comportement pour les tables d'audit

Decision:

- a corriger `P1`

### 7. Expiration approval non appliquee

Confirme dans:

- `src/project_os_core/runtime/store.py`

Constat:

- `expires_at` est stocke
- mais ni `list_pending_approvals()` ni `resolve_approval()` ne filtrent les approvals expirees

Decision:

- a corriger `P1`

### 8. `resolve_approval()` ecrase les metadonnees

Confirme dans:

- `src/project_os_core/runtime/store.py`

Constat:

- `payload_json` est remplace par le nouveau payload
- les metadonnees initiales sont perdues

Decision:

- a corriger `P1`

### 9. Thread-safety SQLite insuffisante

Confirme dans:

- `src/project_os_core/database.py`

Constat:

- `check_same_thread=False`
- une seule connexion partagee
- pas de verrou global ni pool par thread

Decision:

- a corriger `P1/P2`

### 10. Lock de reindexation non atomique

Confirme dans:

- `src/project_os_core/memory/store.py`

Constat:

- le flag `embedding_reindex_state` est lu/ecrit en meta, sans verrou atomique inter-process

Decision:

- a corriger `P1/P2`

### 11. `latest_runtime_state()` sans scope de session

Confirme dans:

- `src/project_os_core/runtime/store.py`

Constat:

- retourne le dernier `runtime_state` global, toutes sessions confondues

Decision:

- a corriger `P1`

## Points de qualite confirmes mais moins prioritaires

- `memory/store.py:search()` fait bien un pattern `N+1`
- `runtime/journal.py` fait bien `fsync()` a chaque append
- `cli.py` utilise encore `os.system("cls")`
- `cli.py` lit encore un fichier sans `with`
- `gateway/promotion.py` repose bien sur du matching de sous-chaines fragile
- `orchestration/graph.py` n'est pas idempotent si relance sur la meme mission

## Points stale ou a nuancer

### Couverture de tests

L'audit dit `12 tests`.
Ce n'est plus vrai.

Etat reel au moment de ce triage:

- `27/27` tests verts

Le fond du reproche reste valable:

- il manque encore de vrais tests de securite
- il manque encore des tests de concurrence
- il manque encore des tests CLI et edge cases

### `storage_roots.example.json` incomplet

Le fichier a ete renforce.
Le reproche est partiellement stale.

Mais il reste un besoin reel:

- mieux expliciter tous les champs archive/roots et leur usage dans les exemples

## Ce qu'on ne doit pas faire

- ne pas melanger ce hardening avec `LangGraph live`
- ne pas repousser les `P0` sous pretexte que `OpenClaw` avance
- ne pas faire corriger tout cela directement sur `main` par l'API sans inspection locale

## Recommandation de workflow

Le meilleur workflow pour ce sujet est:

1. finir `OpenClaw live` jusqu'au premier vrai message Discord/WebChat
2. lancer ensuite un gros run API `patch_plan` focalise uniquement sur:
   - securite `P0`
   - integrite `P1`
3. faire produire a l'API:
   - un plan de patch detaille
   - l'ordre de correction
   - les tests a ajouter
   - les migrations DB a faire
4. laisser `Codex`:
   - verifier
   - decouper en lots propres
   - patcher
   - tester
   - rejeter ce qui n'est pas propre

## Lot recommande apres OpenClaw live

Nom propose:

- `Security and Data Integrity Hardening`

Scope recommande:

- budget derive de la DB, pas du payload client
- approval derivee du store interne, pas du payload client
- parsing input externe durci
- secret push sans arguments CLI
- transactions sur les ecritures multi-tables critiques
- expiration approval appliquee
- merge de metadonnees approval
- verrou ou strategie plus sure pour SQLite/reindex

## Decision

`DECISION CONFIRMED`

Cet audit externe est suffisamment bon pour servir de base a un vrai lot de hardening.
Il ne doit pas etre applique tel quel sans triage local, mais ses `P0/P1` doivent etre pris au serieux et traites avant toute pretention de production autonome large.
