# Quality Standards

Ce document definit les normes de qualite de Project OS.

Objectif: un agent autonome de qualite production, fiable, auditable et evolutif.

## Principes de qualite

1. **Robuste** - le systeme ne casse pas silencieusement
2. **Auditable** - chaque decision a une trace
3. **Verifiable** - chaque sortie peut etre rejouee et validee
4. **Pas de spaghetti** - chaque module a une responsabilite claire
5. **Pas de doublon** - une seule source de verite par concept

## Review cross-model obligatoire

Tout code produit par GPT API passe par une review Claude API avant integration (ADR 0013).

Criteres de review:

| Critere | Description |
|---------|-------------|
| Coherence | Le code respecte l'architecture existante |
| Interfaces | Les contrats d'entree/sortie sont respectes |
| Risques | Pas de failles de securite, pas de regression |
| Tests | Les tests couvrent les cas principaux |
| Boucles | Pas de boucle infinie, pas de recursion non bornee |
| Degradation | Pas de degradation de qualite par rapport au code existant |

Verdicts possibles:
- `accepted` - pret a merger
- `accepted_with_reserves` - mergeable apres correction mineure
- `rejected` - a refaire
- `needs_clarification` - question a poser au fondateur

## Acceptance criteria par type de run

### Audit

- toutes les zones identifiees sont couvertes
- les severites (P0, P1, P2) sont coherentes
- les recommandations sont actionables

### Design

- les interfaces sont definies (entrees, sorties, erreurs)
- les dependances sont explicites
- les alternatives considerees sont documentees

### Patch plan

- chaque fichier a modifier est identifie
- l'ordre des modifications est specifie
- les risques de regression sont evalues

### Generate patch

- le code compile et les tests passent
- les conventions du projet sont respectees
- pas de code mort, pas de TODO non resolu

## Classification des defauts

| Severite | Definition | Action |
|----------|------------|--------|
| P0 | Securite, perte de donnees, corruption d'etat | Correction immediate, bloquer le merge |
| P1 | Bug fonctionnel, comportement incorrect | Correction avant merge |
| P2 | Style, performance non critique, amelioration | Correction au prochain lot |

## Standards de code

### Python

- type hints sur toutes les fonctions publiques
- docstrings sur les classes et fonctions complexes
- pas de `# type: ignore` sans justification
- pas de `try: ... except: pass`
- imports absolus depuis `project_os_core`
- pas de dependance circulaire entre modules

### SQL (SQLite)

- transactions explicites pour les ecritures multiples
- `INSERT OR REPLACE` interdit - utiliser `INSERT` strict avec gestion de conflit
- pas de `check_same_thread=False` en production
- index sur les colonnes filtrees frequemment

### JSON (schemas)

- tous les champs documentes
- valeurs par defaut explicites
- validation de schema avant ecriture

## Couverture de tests

### Objectifs

| Type | Couverture cible |
|------|-----------------|
| Unit tests | Toutes les fonctions publiques des modules core |
| Integration tests | Tous les flux end-to-end (run, review, learning) |
| Contract tests | Tous les schemas JSON (entrees et sorties) |
| Security tests | Tous les P0 identifies dans les audits |

### Verification actuelle

- cartographie lisible des surfaces de test et d'audit: `docs/architecture/TEST_AND_REVIEW_SURFACES.md`
- boucle rapide fiable: `py scripts/project_os_tests.py --suite smoke`
  - couvre seulement les surfaces critiques (`router`, `mission chain`, `api runs`, `dashboard`)
- gateway/OpenClaw: `py scripts/project_os_tests.py --suite gateway`
- validation complete fiable: `py scripts/project_os_tests.py --suite full --with-strict-doctor --with-openclaw-doctor`
- audit documentaire canonique: `py scripts/project_os_entry.py docs audit`
- cloture d'issue / lot / roadmap step: `py scripts/project_os_tests.py --suite full --with-strict-doctor --with-openclaw-doctor --with-doc-audit` quand la surface touche runtime, policy, interfaces, docs ou OpenClaw
- `py -m pytest -q` doit rester borne au coeur du repo via `pytest.ini` et ne plus collecter `third_party`
- completer au besoin avec des suites ciblees par sous-systeme
- garder les chiffres de tests hors de cette doc pour eviter le drift

### Discipline d'execution des verifications

- choisir un budget de temps explicite avant de lancer une suite; ne pas supposer qu'un run combine "passera vite"
- ne pas grouper plusieurs fichiers `pytest` moyens ou lourds dans une seule commande avec un timeout court
- pour les surfaces `gateway`, `prompt`, `orchestration` et `Discord`, preferer:
  - des runs par fichier
  - ou les suites canoniques `scripts/project_os_tests.py`
- si une commande timeoute, la verification reste `non concluante` tant qu'un rerun adapte n'a pas rendu un verdict vert explicite
- preferer des resultats incrementaux fiables a une grosse commande combinee mal budgetee

### Outil

- `pytest` avec fixtures locales
- `scripts/project_os_tests.py` comme entree canonique pour eviter la dependance a la policy PowerShell et standardiser les suites
- `scripts/project_os_tests.cmd` comme wrapper Windows sans policy; `scripts/project_os_tests.ps1` reste un wrapper de compatibilite
- Pas de CI/CD externe en v1 - les tests tournent localement avant merge

## Performance

### Latences acceptables

| Operation | Cible |
|-----------|-------|
| Lecture SQLite (state) | <100ms |
| Resolution d'intention Discord | <3s (avec escalade Claude si necessaire) |
| Context pack assembly | <5s |
| MegaPrompt render | <2s |
| API run execution | variable (depende du mode et du contexte) |
| Dashboard refresh | <1s |

### Memoire

- le processus principal ne doit pas depasser 500 Mo en usage normal
- les context packs sont streames, pas charges en memoire entiere

## Politique de dette technique

- la dette technique est acceptee si documentee (ADR ou commentaire)
- chaque dette a un lot de remediation planifie
- les P0 de l'audit ne sont pas de la dette - ce sont des blocages

## References

- `docs/audits/CLAUDE_OPUS_46_AUDIT_TRIAGE_2026-03-13.md`
- `docs/decisions/0013-dual-model-operating-model.md`
- `docs/integrations/API_RUN_CONTRACT.md`
- `docs/architecture/TEST_AND_REVIEW_SURFACES.md`
- `config/api_run_templates.json`
