# Language Levels

Ce document definit les trois niveaux de langage utilises dans Project OS.

Le principe est simple: chaque acteur parle dans le langage adapte a son interlocuteur.
Le fondateur ne recoit jamais de code. Les APIs ne recoivent jamais de prose floue.

## Niveau 1 — Machine

### Qui parle

GPT API et le runtime Project OS entre eux.

### Style

JSON, code, schemas, structured output.

### Quand

- pendant l'execution d'un run API
- dans les echanges avec la base de donnees
- dans les artefacts runtime
- dans les lifecycle events

### Exemple

```json
{
  "run_id": "api_run_2026_03_13_001",
  "status": "clarification_required",
  "blocking_question": "memory_bridge depends on learning_updater via _persist_memory_card which calls _resolve_embedding_vector routing back to MemoryCurator",
  "options": ["inject_curator_as_parameter", "extract_memory_write_port"],
  "recommended": "inject_curator_as_parameter"
}
```

### Regle

Jamais montre au fondateur. Jamais envoye sur Discord.

## Niveau 2 — Prompt structure

### Qui parle

GPT API vers Claude API (et retour).

### Style

JSON structure avec champs semantiques clairs.
Pas du code brut, pas de la prose floue.
Un format que Claude API peut lire et traduire mecaniquement.

### Format: structured_question (GPT -> Claude)

```json
{
  "type": "question_for_founder",
  "run_id": "api_run_xxx",
  "branch": "codex/project-os-refactor-memory",
  "context": "Deux modules memory se bloquent mutuellement par dependance circulaire",
  "impact": "Bloque le lot de refactoring en cours",
  "options": [
    {
      "key": "A",
      "label": "Separer via injection de dependance",
      "pros": "Plus propre, evolutif",
      "cons": "2h de travail supplementaire",
      "recommended": true
    },
    {
      "key": "B",
      "label": "Fusionner les deux modules",
      "pros": "Rapide",
      "cons": "Couplage futur, plus difficile a defaire"
    }
  ],
  "urgency": "low",
  "can_wait_hours": 4,
  "fallback_if_no_answer": "A"
}
```

### Format: founder_decision (Claude -> GPT)

```json
{
  "type": "founder_decision",
  "run_id": "api_run_xxx",
  "chosen_option": "A",
  "raw_answer": "ok",
  "interpreted_as": "Accepte la recommandation (option A)"
}
```

### Format: run_summary (GPT -> Claude pour traduction)

```json
{
  "type": "run_summary",
  "run_id": "api_run_xxx",
  "branch": "codex/project-os-refactor-memory",
  "status": "completed",
  "decision_summary": "Memory separe en bridge, store et curator",
  "files_changed": 5,
  "cost_eur": 0.28,
  "next_action": "Review disponible au retour"
}
```

### Format: review_result (Claude -> GPT apres audit)

```json
{
  "type": "review_result",
  "run_id": "api_run_xxx",
  "verdict": "accepted_with_reserves",
  "issues_found": 2,
  "critical": 0,
  "high": 1,
  "summary": "Code propre mais une fuite de connexion SQLite dans bridge.py ligne 142",
  "recommendation": "Corriger la fuite avant merge"
}
```

### Regle

Format stable et versionne. Chaque champ est semantique.
Claude API doit pouvoir traduire mecaniquement sans avoir besoin du contexte complet du run.

Implementation actuelle pour la voie operateur:

- le niveau 2 ne se limite plus a `structured_question`
- il inclut aussi un `handoff contract` minimal entre la voix gateway et le modele du tour
- ce contrat contient l'intention brute, le modele cible, le snapshot de contexte et les questions encore pendantes

References implementation:

- `src/project_os_core/gateway/handoff.py`
- `src/project_os_core/gateway/context_builder.py`

## Niveau 3 — Humain

### Qui parle

Claude API vers le fondateur (via Discord).

### Style

Francais simple. Phrases courtes. Pas de jargon.
Trois profils existent:

- `notification_card`: maximum 3 lignes. Jamais de code. Jamais de chemin de fichier.
- `meeting_thread`: format structure, pas de limite fixe en lignes, toujours lisible.
- `founder_synthesis`: recap humain concis dans `#pilotage`, non borne a 3 lignes si la clarte le demande.

### Exemples `notification_card` par situation

#### Run complete

```
codex/project-os-refactor-memory termine — Memory separe en 3 modules propres.
5 fichiers, 0.28EUR. Review dispo au retour.
```

#### Clarification requise

```
Question sur codex/project-os-refactor-memory —
Deux modules se bloquent mutuellement.
A) Separer proprement (recommande) B) Fusionner
Pas urgent, j'ai 4h. Si tu reponds pas je fais A.
```

#### Run echoue

```
codex/project-os-add-guardian echoue — l'API OpenAI a refuse la requete (quota depasse).
Aucune action requise, je reessaie dans 30 min.
```

#### Contrat propose

```
Nouveau lot propose — Refactor du module memory en 3 sous-modules.
Cout estime: 0.35EUR. On lance ?
```

#### Budget alert

```
Budget jour a 82% — 2.87EUR sur 3.50EUR.
Les runs non urgents attendront demain.
```

#### Review Claude (resume pour le fondateur)

```
Review du refactor memory — Code propre dans l'ensemble.
Un probleme a corriger avant merge (fuite de connexion).
GPT va corriger automatiquement.
```

### Regle

Si un message serait difficile a comprendre pour quelqu'un qui n'a jamais code,
il doit etre simplifie avant envoi.

Regles supplementaires actuelles:

- la voix publique est rendue depuis `config/project_os_persona.yaml`
- la verite runtime est injectee a chaque tour
- le ton s'adapte legerement au mood (`focused`, `brainstorming`, `casual`, `serious`, `urgent`, `frustrated`)
- cet ajustement ne doit jamais casser la clarte, la verite ou la sobriete

Golden checks retenus:

- `qui es-tu ?` -> doit parler comme `Project OS`, jamais comme un assistant numerique generique
- `quel modele utilises-tu ?` -> doit rester factuel selon le runtime du tour
- une blague legere peut etre reconnue, sans transformer la discussion en sketch
- un sujet sensible ou critique doit rendre le ton plus net, pas plus froidement robotique

## Regles de filtrage

Claude API decide quoi envoyer au fondateur:

| Signal | Envoyer ? | Raison |
|---|---|---|
| `run_started` | Non | Bruit pur, aucune action requise |
| `run_completed` | Oui | Le fondateur doit savoir |
| `clarification_required` | Oui | Besoin de decision |
| `run_failed` + auto-retry | Non | Attendre le resultat du retry |
| `run_failed` + no retry | Oui | Prevenir sans paniquer |
| `contract_proposed` | Oui | Besoin d'approbation |
| `budget_alert < 70%` | Non | Pas actionable |
| `budget_alert >= 80%` | Oui | Le fondateur peut ajuster |
| `review_accepted` | Oui | Resume court |
| `review_rejected` | Oui | Le fondateur doit savoir |

## Prompt Ops

Le comportement de la voix operateur n'est pas "artistique".
Il est traite comme un composant versionne et teste.

Cela implique:

- spec persona versionnee dans le repo
- renderers `Anthropic / OpenAI / local`
- tests golden sur la voix, la verite et les overrides modele
- tests de ton sur plusieurs moods
- docs alignees sur le comportement reel

## References

- `docs/decisions/0013-dual-model-operating-model.md`
- `docs/workflow/ROLE_MAP.md`
- `docs/workflow/DISCORD_MESSAGE_TEMPLATES.md`
- `docs/architecture/FRENCH_OPERATOR_OUTPUT_POLICY.md`
