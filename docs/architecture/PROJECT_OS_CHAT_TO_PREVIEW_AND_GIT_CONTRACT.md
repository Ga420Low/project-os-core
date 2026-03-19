# Project OS Chat To Preview And Git Contract

## Statut

ACTIVE - Operator workflow clarification

## But

Rendre explicite le workflow operateur quand un chat demande une modification, en
particulier pour eviter deux erreurs:

- croire qu'il faut pousser sur `GitHub` pour voir une diff
- croire qu'un simple message chat doit toujours modifier le repo

## Regle racine

Par defaut, le chat ne modifie rien.

Il faut distinguer:

1. `discuss`
2. `try in preview`
3. `save branch`
4. `open PR`
5. `merge`

Ces cinq actions ne sont pas equivalentes et ne doivent pas etre fusionnees.

## Mode 1 - Discuss

L'operateur demande:

- une idee
- une comparaison
- un audit
- une explication

Effet:

- aucune ecriture repo
- aucune branche
- aucun preview runtime

## Mode 2 - Try In Preview

L'operateur demande:

- "essaie"
- "fais une preview"
- "change ce bouton pour voir"

Effet:

1. creation d'un workspace runner isole
2. creation d'une branche de travail locale au runner
3. modification des fichiers dans ce workspace
4. build/test/preview si possible
5. publication dans `Project OS` de:
   - diff
   - preview URL ou preuve equivalente
   - screenshots si utile
   - logs/tests

Regle dure:

- aucun push `GitHub` n'est requis pour voir le resultat

## Mode 3 - Save Branch

L'operateur confirme:

- "ok garde"
- "sauvegarde cette version"
- "push la branche"

Effet:

- la branche de travail runner devient une branche distante `GitHub`
- la proposition reste encore non mergee

## Mode 4 - Open PR

L'operateur confirme:

- "ouvre une PR"

Effet:

- la branche est convertie ou reliee a une `PR`
- les reviews et checks prennent le relais

## Mode 5 - Merge

L'operateur confirme:

- "merge"

Effet:

- integration dans la branche cible selon la policy repo

Regle dure:

- pas de merge implicite
- pas de merge parce qu'un preview est joli

## Preview policy

### Cas UI / frontend

Le preview doit essayer de fournir:

- URL preview
- screenshots
- diff

### Cas backend / logique

Le preview peut etre non visuel.

Dans ce cas, il doit fournir:

- tests
- logs
- smoke checks
- rapport de comportement

## Regle de verite

- le preview sert a juger
- `GitHub` sert a conserver
- `Project OS` sert a piloter et tracer

## Interdits

Le systeme ne doit pas:

- pousser pour tester
- merger pour tester
- modifier le clone humain Windows
- faire passer un workspace runner temporaire pour la verite du code

## Acceptance checks

Le workflow est considere clair et respecte quand:

1. une demande de discussion n'ecrit rien
2. une demande de preview cree un workspace sans push obligatoire
3. l'operateur peut voir une diff avant push
4. un push de branche n'implique pas merge
5. un merge demande une validation explicite distincte

## References

- `docs/workflow/PROJECT_OS_AGENTIC_GIT_WORKFLOW_CONTRACT.md`
- `docs/architecture/PROJECT_OS_CANONICAL_DATA_MODEL_CONTRACT.md`
- `docs/roadmap/PROJECT_OS_AUTOPILOT_PACK_PLAN.md`

