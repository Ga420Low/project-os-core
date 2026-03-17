# Test And Review Surfaces

Ce document est la carte lisible de ce que `Project OS` sait deja verifier localement.

But:

- se souvenir vite de ce qui existe
- savoir quelle commande lancer selon le besoin
- distinguer le gratuit/local du live/couteux
- garder une vue claire sur les surfaces de preuve du projet

## Lecture rapide

| Besoin | Commande canonique | Cout | Ce que ca prouve |
|---|---|---:|---|
| boucle rapide coeur | `py scripts/project_os_tests.py --suite smoke` | local | router, mission chain, api runs, dashboard |
| surfaces gateway/OpenClaw | `py scripts/project_os_tests.py --suite gateway` | local | adapter live, replay, gateway, api runs |
| validation repo complete | `py scripts/project_os_tests.py --suite full --with-strict-doctor --with-openclaw-doctor` | local | unit + integration + sante runtime/OpenClaw |
| derive documentaire | `py scripts/project_os_entry.py docs audit` | local | liens, encodage, drift des docs actives |
| sante runtime stricte | `py scripts/project_os_entry.py doctor --strict` | local | secrets, runtime, policy, prerequisites machine |
| debug system local | `py scripts/project_os_entry.py observability doctor` | local | correlation, quarantines, replays, incidents, evals, retention |
| repair debug | `py scripts/project_os_entry.py debug reconcile --repair` | local | marquage missing/stale et reparation soft |
| live OpenClaw | `py scripts/project_os_entry.py openclaw doctor` | local | trust, runtime, pairing, policy locale |
| preuve live Discord/OpenClaw | `py scripts/project_os_entry.py openclaw truth-health --channel discord` | local | preuve runtime recente sur la chaine live |
| validation live Discord/OpenClaw | `py scripts/project_os_entry.py openclaw validate-live --channel discord` | local | confirmation canonique d'un flux live observe |
| smoke facade Discord | `py scripts/project_os_tests.py --suite discord-facade-live` | faible | facade visible, flows proteges, Haiku live |
| regression persona Discord | `py scripts/project_os_tests.py --suite discord-persona-live` | faible | voix publique, ton, identite, anti-corporate |
| audit final Discord | `py scripts/project_os_entry.py debug discord-audit` | local | verdict `coherent / non_coherent / inconclusive` |
| memo projet global | `py scripts/project_os_entry.py review status` | local | done / partiel / oublie / non verifie / a revoir |

## 1. Suites de tests canoniques

### `scripts/project_os_tests.py`

Point d'entree standard pour les suites locales.

Suites utiles:

- `smoke`
  - rapide
  - surfaces critiques du coeur
- `gateway`
  - utile quand on touche `gateway`, `openclaw`, `router`, `api_runs`
- `full`
  - validation large `tests/unit + tests/integration`
- `discord-facade-live`
  - smoke Discord live cheap sur `Claude Haiku`
- `discord-persona-live`
  - regressions de voix/persona Discord live
- `discord-full-live`
  - facade + persona live

Gates utiles:

- `--with-strict-doctor`
- `--with-openclaw-doctor`
- `--with-doc-audit`

## 2. Doctors et audits de sante

### Runtime

- `py scripts/project_os_entry.py doctor --strict`
  - preflight machine/runtime
  - indispensable avant un verdict fort

### Documentation

- `py scripts/project_os_entry.py docs audit`
  - detecte les liens casses
  - detecte le mojibake
  - detecte certains drifts actifs connus

### Debug System

- `py scripts/project_os_entry.py observability doctor`
  - audit correlation spine
  - audit quarantines
  - audit replay health
  - audit incidents/evals
  - audit retention/privacy

- `py scripts/project_os_entry.py observability doctor --repair`
  - ajoute la reparation soft du debug

### OpenClaw live

- `py scripts/project_os_entry.py openclaw doctor`
- `py scripts/project_os_entry.py openclaw truth-health --channel discord`
- `py scripts/project_os_entry.py openclaw validate-live --channel discord`

Ces trois commandes sont la verite locale minimale sur la chaine Discord/OpenClaw.

## 3. Debug Discord

### Harness cheap live

- `py scripts/discord_facade_smoke.py`
- `py scripts/project_os_tests.py --suite discord-facade-live`
- `py scripts/project_os_tests.py --suite discord-persona-live`

Notes:

- les scenarios live passent par `Haiku` pour rester peu chers
- les cas proteges gateway-only ne consomment pas d'API
- les checks manuels restent necessaires pour la presence percue, le rendu live et certaines nuances UX

### Audit final Discord

- `py scripts/project_os_entry.py debug discord-audit`

Ce runner:

- lit un rapport existant ou le dernier rapport connu
- classe les scenarios en `PASS / FAIL / REGRESSION / FALSE POSITIVE / SKIP`
- integre les checks manuels
- rend un verdict:
  - `coherent`
  - `non_coherent`
  - `inconclusive`

Important:

- tant que le freeze `bot/app/dashboard` n'est pas leve ou que les checks manuels restent `pending`, le verdict final doit rester `inconclusive`

## 4. Project Review Loop

- `py scripts/project_os_entry.py review status`

Ce rapport sert de memoire automatique du projet.

Il agrege:

- la checklist build
- le docs audit
- le debug system doctor
- la resilience debug
- le dernier audit Discord
- l'etat des taches scheduler

Sorties:

- un rapport JSON `latest`
- un rapport Markdown `latest`

Sections ciblees:

- `Done`
- `Partiel`
- `Oublie`
- `Non verifie`
- `A revoir avec le fondateur`

## 5. Quand lancer quoi

### Tu viens de coder un petit lot local

- `py scripts/project_os_tests.py --suite smoke`

### Tu as touche `gateway`, `router`, `api_runs` ou `OpenClaw`

- `py scripts/project_os_tests.py --suite gateway`
- `py scripts/project_os_entry.py doctor --strict`

### Tu veux clore un lot important

- `py scripts/project_os_tests.py --suite full --with-strict-doctor --with-openclaw-doctor --with-doc-audit`

### Tu veux savoir ou le projet en est sans te fier a ta memoire

- `py scripts/project_os_entry.py review status`

### Tu veux juger la facade Discord

- `py scripts/project_os_tests.py --suite discord-facade-live`
- `py scripts/project_os_tests.py --suite discord-persona-live`
- `py scripts/project_os_entry.py debug discord-audit`

## 6. Ce qui est local vs ce qui coute

### Local / gratuit

- `doctor --strict`
- `docs audit`
- `observability doctor`
- `debug reconcile`
- `openclaw doctor`
- `truth-health`
- `validate-live`
- `project_os_tests.py --suite smoke`
- `project_os_tests.py --suite gateway`
- `project_os_tests.py --suite full`
- `review status`

### Faible cout live

- `discord-facade-live`
- `discord-persona-live`
- `discord-full-live`

### Manuel / humain

- checks `manual/live acceptance`
- jugement final de surface Discord
- relecture fondateur des points vraiment ambigus

## 7. Verite du projet

Si tu ne sais plus quoi croire:

1. `BUILD_STATUS_CHECKLIST.md` pour l'etat declare du build
2. `review status` pour la photo agregée du moment
3. `doctor / docs audit / observability doctor / debug discord-audit` pour les preuves

Ce document est un index. Il ne remplace pas les preuves canoniques.
