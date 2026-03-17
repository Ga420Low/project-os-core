# ADR 0013 - Dual Model Operating Model

## Statut

DECISION CHANGED - supersede ADR 0010

## Contexte

Le modele operatoire ADR 0010 reposait sur:

- `GPT API` grande fenetre = Lead Agent
- une surface locale manuelle = Command Board (inspection, integration, verification)

Ce modele atteint ses limites:

1. une surface locale manuelle ne peut pas etre un agent autonome dans le pipeline
2. une surface locale manuelle ne peut ni aller sur Discord, ni etre appelee par API
3. un seul modele (`gpt-5.4`) qui code ET qui review son propre code = memes angles morts, memes biais
4. le fondateur a besoin d'un systeme qui tourne sans lui devant l'ecran

## Decision

Le modele operatoire devient un duo de modeles complementaires:

### GPT API (gpt-5.4, 1M contexte) - Le Cerveau / Le Dev

- code les gros lots
- planifie les missions
- brainstorme l'architecture
- produit du structured output (JSON)
- 1M tokens de contexte = voit tout le projet

Personnalite: technique, precis, executant.

### Claude API (opus/sonnet, 1M contexte) - L'Auditeur / Le Traducteur

Role 1 - Auditeur:

- review le code produit par GPT (vrai regard exterieur cross-model)
- challenge les decisions
- detecte ce que GPT ne voit pas (angles morts du meme modele)
- produit des signaux de qualite et de risque

Role 2 - Traducteur:

- recoit les questions structurees de GPT au format `structured_question`
- traduit en francais humain simple pour le fondateur
- filtre le bruit (decide quoi envoyer, quoi garder silencieux)
- traduit les reponses du fondateur en retour au format `founder_decision`

Personnalite: critique, humain, protecteur.

### Supervision locale (terminal + dashboard) - Hors pipeline

- reste disponible pour inspecter un run, comprendre un resultat, ou suivre un incident
- n'est pas une lane produit autonome
- ne remplace ni `Discord`, ni `Claude API`, ni le runtime local

### Theo (le fondateur) - Direction et decision

- parle en humain, en francais
- donne la vision, les ambitions, les decisions
- ne code jamais, ne lit jamais de code brut
- interagit via Discord (mobile) ou terminal + dashboard (PC)

## Format d'echange structure entre GPT et Claude

### structured_question (GPT -> Claude)

```json
{
  "type": "question_for_founder",
  "run_id": "api_run_xxx",
  "branch": "codex/project-os-refactor-memory",
  "context": "description courte du probleme",
  "impact": "consequence si pas de reponse",
  "options": [
    {
      "key": "A",
      "label": "description option A",
      "pros": "avantages",
      "cons": "inconvenients",
      "recommended": true
    },
    {
      "key": "B",
      "label": "description option B",
      "pros": "avantages",
      "cons": "inconvenients"
    }
  ],
  "urgency": "low | medium | high",
  "can_wait_hours": 4,
  "fallback_if_no_answer": "A"
}
```

### founder_decision (Claude -> GPT)

```json
{
  "type": "founder_decision",
  "run_id": "api_run_xxx",
  "chosen_option": "A",
  "raw_answer": "ok",
  "interpreted_as": "Accepte la recommandation (option A)"
}
```

### run_summary (GPT -> Claude pour traduction)

```json
{
  "type": "run_summary",
  "run_id": "api_run_xxx",
  "branch": "codex/project-os-refactor-memory",
  "status": "completed | failed | clarification_required",
  "decision_summary": "ce qui a ete decide",
  "files_changed": 5,
  "cost_eur": 0.28,
  "next_action": "review disponible au retour"
}
```

## Trois niveaux de langage

1. **Machine** (JSON, code, schemas) - entre GPT API et le runtime, jamais montre au fondateur
2. **Prompt structure** (structured_question / founder_decision) - entre GPT API et Claude API
3. **Humain** (francais simple, max 3 lignes) - de Claude API vers le fondateur via Discord

## Regles de filtrage (Claude decidant quoi envoyer)

| Signal | Envoyer au fondateur ? |
|---|---|
| `run_started` | Non (bruit) |
| `run_completed` | Oui (resume court) |
| `clarification_required` | Oui (question + options) |
| `run_failed` + auto-retry en cours | Non (attendre le resultat) |
| `run_failed` + no retry | Oui (raison simple) |
| `budget_alert < 70%` | Non |
| `budget_alert >= 80%` | Oui |
| `contract_proposed` | Oui (besoin d'approbation) |

## Cout estime

Journee type avec 5 runs:

- GPT API (cerveau): 5 runs x ~100k tokens input x ~2k output = ~2.50$/jour
- Claude API (auditeur): 5 reviews x ~30k tokens input x ~3k output = ~1.20$/jour
- Claude API (traducteur): ~10 traductions x ~500 tokens = ~0.01$/jour
- Total: ~3.70$/jour = ~3.40EUR/jour

## Pourquoi deux modeles differents

- deux modeles = deux facons de penser = vrais bugs trouves
- GPT est bon en execution et en code massif
- Claude est bon en analyse critique et en communication humaine
- un modele qui s'auto-review a les memes angles morts que quand il a code
- le challenge cross-model est la base du systeme critic/guardian

## Consequences

### Positives

- vrai audit cross-model (pas d'auto-validation)
- traduction humaine naturelle integree au pipeline
- filtre anti-bruit pour Discord (5 messages/jour au lieu de 60)
- le fondateur peut piloter depuis son telephone
- la supervision locale reste disponible pour l'inspection et la preuve
- le traducteur est remplacable (si un meilleur modele arrive demain, on change juste cette couche)

### Contraintes

- deux factures API a gerer
- le format structured_question doit etre respecte par les prompts GPT
- la latence augmente (GPT -> Claude -> Discord -> fondateur -> Discord -> Claude -> GPT = 6 hops)
- `can_wait_hours` et `fallback_if_no_answer` doivent toujours etre remplis pour eviter les blocages indefinis

## Extension de deliberation structuree

Cette ADR reste compatible avec une couche de deliberation multi-angles sur les sujets importants.

Principes:

- aucune nouvelle identite produit
- aucun nouveau cerveau autonome
- les angles d'analyse sont des prismes bornes, pas des modeles separes
- `Discord` reste la surface lisible
- le runtime reste la trace canonique

Quand cette couche est activee:

- `GPT API` peut alimenter l'analyse et le plan
- `Claude API` peut auditer, clarifier et traduire la synthese pour le fondateur
- le `Moderator` reste une fonction procedurale du systeme

References:

- `docs/analysis-angles/README.md`
- `docs/integrations/DISCORD_MEETING_SYSTEM_V1.md`

## Principe d'autonomie fondateur

Le fondateur ne s'adapte pas au systeme. Le systeme s'adapte au fondateur.

- le fondateur parle comme il veut, dans ses mots, a son rythme
- le systeme comprend l'intention, pas les mots-cles
- le fondateur ne doit rien sentir: pas de format, pas de commande a retenir
- tout est autonome: le systeme gere seul et ne derange que quand c'est necessaire
- le systeme apprend progressivement les habitudes du fondateur via OpenMemory
- premiere semaine: confirmation plus frequente
- apres un mois: le systeme connait le style et agit avec moins de friction

## Persistent Session State

Le systeme est un agent persistant qui vit dans sa DB SQLite.
Les appels API sont exceptionnels: le systeme SE SOUVIENT via la DB, il ne PENSE via l'API que quand c'est necessaire.

Le state persistant maintient en permanence (cout: 0 EUR, latence: <100ms):

- quels runs sont actifs (id, branche, status, phase)
- quel contrat attend une approbation
- quelle question attend une reponse du fondateur
- le budget du jour (depense, limite)
- les 10 derniers echanges Discord
- les decisions recentes du fondateur
- les preferences apprises (via OpenMemory)

Quand un message Discord arrive:

1. le state sait ce qui est en cours (zero API call)
2. si l'intention est claire en contexte ("ouais" alors qu'un contrat est en attente) -> action directe
3. si l'intention est ambigue -> escalade a Claude API avec un context brief minuscule (~500 tokens)
4. si le message demande du travail reel -> GPT API est appele pour executer

Les appels API (GPT ou Claude) sont reserves au TRAVAIL et a la PENSEE, jamais a la MEMOIRE.

## Integration dans le code

```
Phase EXECUTE   -> GPT API (comme aujourd'hui)
Phase REVIEW    -> Claude API (nouveau)
Phase TRANSLATE -> Claude API (nouveau, appels minuscules)
```

Dans `service.py`:

```python
result = self._call_openai(request, prompt, context)          # GPT code
review = self._call_reviewer(result, context)                  # Claude audite
brief  = self._call_translator(lifecycle_event, review)        # Claude traduit
```

Nouveau composant: `DiscordContextManager` / `PersistentSessionState`

```python
# Quand un message Discord arrive:
state = session_state.load()                    # SQLite, 0 API call
action = state.resolve_intent(message)          # pattern + contexte
if action:
    execute_action(action)                      # direct, 0 API call
else:
    brief = state.build_context_brief()         # ~500 tokens
    decision = call_claude(brief, message)      # rare, ~0.001 EUR
    execute_action(decision)
```

## References

- ADR 0010 (supersede)
- `docs/workflow/ROLE_MAP.md`
- `docs/workflow/LANGUAGE_LEVELS.md`
- `docs/workflow/DAILY_OPERATOR_WORKFLOW.md`
- `docs/workflow/DISCORD_MESSAGE_TEMPLATES.md`
- `docs/analysis-angles/README.md`
