# Persona V2 And Context Integrity Plan

## Statut

Feuille de route canonique en cours.

Ce document cadre le prochain chantier voix / contexte de `Project OS`.
Il ne change pas la frontiere `OpenClaw` vs `Project OS`.
Il professionnalise la voix publique, la verite runtime et la continuite de contexte entre modeles.

## But

Faire de la voix `Project OS` une vraie presence utile:

- humaine
- directe
- exigeante
- adaptable au ton du fondateur
- factuelle sur le runtime et le modele reel du tour
- coherente quand plusieurs modeles se relaient

Le chantier doit fermer trois faiblesses:

- persona encore trop liee au code dur
- contexte recent encore trop distribue
- risque de telephone arabe entre message humain, scripts et modeles

## Regles d'architecture

Regles dures:

- `Project OS` garde la voix publique
- `OpenClaw` reste la facade / le transport, pas la personnalite canonique
- la persona doit devenir une source versionnee du repo, pas quelques phrases cachees dans `service.py`
- la verite runtime reste separee du style
- les handoffs entre modeles doivent etre structures, pas seulement resumes en texte libre
- aucune dependance `LangGraph` n'est ajoutee dans ce lot

References:

- `docs/architecture/AGENT_IDENTITY_AND_CHANNEL_MODEL.md`
- `docs/workflow/LANGUAGE_LEVELS.md`
- `docs/workflow/DISCORD_MESSAGE_TEMPLATES.md`
- `docs/workflow/DAILY_OPERATOR_WORKFLOW.md`
- `docs/decisions/0013-dual-model-operating-model.md`

## Ordre retenu

1. `Pack 1 - Persona V2`
2. `Pack 2 - Context Integrity`
3. `Pack 3 - Prompt Ops And Evals`

Pourquoi cet ordre:

- on fixe d'abord la voix et la source canonique
- on fiabilise ensuite la continuite du contexte
- on verrouille ensuite les regressions par les tests et la doc

## Pack 1 - Persona V2

### Statut

`IMPLEMENTE`

### Objet

Sortir la personnalite du code dur et en faire une source canonique testable.

### Livrables

- `config/project_os_persona.yaml`
- `src/project_os_core/gateway/persona.py`
- branchement dans `src/project_os_core/gateway/service.py`

### Contenu

- identite canonique
- role
- voix
- axes de style
- anti-patterns
- few-shot examples
- regles de verite
- regles de model override
- renderers `anthropic / openai / local`
- cache `Anthropic` sur le bloc persona statique

### Reuse explicite

Le pack doit reutiliser ce qui existe deja:

- `_simple_chat_system_prompt()` dans `gateway/service.py`
- `_local_system_prompt()` dans `gateway/service.py`
- logique `S1 / S2 / S3` deja posee dans le router

### Criteres d'acceptation

- la voix Discord vient de la spec, pas d'un prompt hardcode
- `qui es-tu ?` repond comme `Project OS`, pas comme un assistant generique
- `quel modele / provider utilises-tu ?` repond factuellement selon le runtime du tour
- la voix reste humaine sans perdre la rigueur ni la verite

## Pack 2 - Context Integrity

### Statut

`IMPLEMENTE`

### Objet

Eviter le telephone arabe entre message humain, scripts, modeles et reponses.

### Livrables

- `src/project_os_core/gateway/context_builder.py`
- `src/project_os_core/gateway/handoff.py`
- branchement avec `session/state.py` et `gateway/service.py`

### Contenu

- extraction de `_simple_chat_user_message()`
- enrichissement via `build_context_brief()`
- hint de mood leger
- handoff contract minimal
- continuite de contexte entre `Sonnet / Opus / GPT / local`
- overrides style / modele traites au meme endroit

### Reuse explicite

Le pack doit reutiliser ce qui existe deja:

- `_simple_chat_user_message()` dans `gateway/service.py`
- `build_context_brief()` dans `session/state.py`
- `RoutingDecision` et les metadonnees de routage deja disponibles

### Criteres d'acceptation

- le message brut utilisateur reste tracable
- les contraintes ne se perdent pas entre modeles
- les handoffs sont lisibles et structures
- la verite runtime, le ton et les overrides ne se contredisent pas

## Pack 3 - Prompt Ops And Evals

### Statut

`IMPLEMENTE`

### Objet

Verrouiller la qualite de la voix et de la verite dans le temps.

### Livrables

- tests golden persona
- tests verite runtime
- tests ton / humour leger / challenge / serieux
- docs realignees

### Contenu

- test `qui es-tu ?`
- test `quel modele utilises-tu ?`
- test message sec
- test brainstorming
- test humour leger
- test arbitrage dur
- mise a jour des docs d'identite et de workflow

### Criteres d'acceptation

- aucune reponse ne regresse vers une voix generique
- la reponse runtime reste exacte
- les changements de persona deviennent testables et reversibles

## Non-buts

- brancher `LangGraph` maintenant
- refaire la memoire long terme dans ce lot
- ajouter un classifieur mood lourd
- transformer la persona en couche marketing ou theatrale

## Definition of done globale

Le lot est considere termine quand:

1. la voix publique `Project OS` est canonique, versionnee et provider-aware
2. le contexte recent et les handoffs restent coherents d'un modele a l'autre
3. la verite runtime et le ton sont testes
4. les docs de reference correspondent au comportement reel
