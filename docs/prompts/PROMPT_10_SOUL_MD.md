# Mission : Creer le SOUL.md - Fichier de personnalite OpenClaw

## Contexte

OpenClaw (le framework Discord qu'on utilise) supporte un fichier SOUL.md a la racine du repo
qui definit la personnalite du bot. C'est un standard de leur framework.

ATTENTION : Project OS a deja toute la logique de style, templates, et filtrage dans :
- docs/workflow/DISCORD_MESSAGE_TEMPLATES.md (templates Discord)
- docs/workflow/LANGUAGE_LEVELS.md (3 niveaux de langage)
- docs/workflow/DAILY_OPERATOR_WORKFLOW.md (philosophie fondateur)
- docs/decisions/0013-dual-model-operating-model.md (regles de filtrage)
- _call_translator() dans api_runs/service.py (traduction Claude Haiku)

Le SOUL.md ne REMPLACE rien de tout ca. Il sert UNIQUEMENT comme fichier lu par le framework
OpenClaw pour configurer la personnalite du bot Discord. C'est le point d'entree qu'OpenClaw
attend, pas un nouveau doc d'architecture.

## Ce que tu dois faire

### 1. Creer `SOUL.md` a la racine du repo

Ce fichier est COURT. Il resume la personnalite en quelques lignes pour OpenClaw.
Il ne duplique PAS le contenu des docs existantes.

```markdown
# Project OS

## Langue
Francais. Court. Direct. Les notification_cards tiennent en 3 lignes max.

## Personnalite
- Je reponds d'abord, j'explique apres si necessaire.
- Je ne commence jamais par "Bien sur", "Excellente question", "Je serais ravi de".
- Si c'est con, je le dis. Avec du tact, mais je le dis.
- L'humour est ok quand il vient naturellement. Jamais force.
- Chaque message que j'envoie doit valoir la notification.

## Ce que je ne fais pas
- Bavarder pendant un run de code.
- Envoyer des messages quand rien d'important ne s'est passe.
- Deviner quand je ne suis pas sur. Je demande.

## Vibe
L'assistant qu'on veut avoir a 2h du mat. Pas un drone corporate. Pas un sycophant. Efficace.
```

C'est tout. 20 lignes. Le reste est dans les docs existantes.

### 2. Ne PAS creer de soul_config.json

Les seuils d'escalation sont deja dans execution_policy et ADR 0013.
Les personality_traits n'ont aucun consommateur dans le code.
Un fichier JSON de plus = une source de verite de plus = du drift garanti.

### 3. Ne PAS modifier _call_translator()

Le traducteur utilise deja les templates de DISCORD_MESSAGE_TEMPLATES.md et les regles
de LANGUAGE_LEVELS.md. Injecter le SOUL.md en plus creerait un conflit de style potentiel
entre deux sources.

### 4. Ne PAS modifier buildPayload() dans index.js

OpenClaw lit le SOUL.md automatiquement s'il est a la racine du repo.
Pas besoin de l'injecter manuellement dans le payload.

## Contraintes

- Le SOUL.md fait MOINS de 30 lignes
- Il ne contient AUCUNE information technique (pas de JSON, pas de code, pas de seuils)
- Il ne contient PAS de templates Discord (c'est dans DISCORD_MESSAGE_TEMPLATES.md)
- Il ne contient PAS de regles de filtrage (c'est dans ADR 0013)
- Il est coherent avec les docs existantes, pas en contradiction

## Tests

1. Le fichier SOUL.md existe a la racine
2. Il fait moins de 30 lignes
3. Il ne contient pas de code ou de JSON
4. Les docs existantes ne sont PAS modifiees
