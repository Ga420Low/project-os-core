# 0010 - Hybrid Codex + API Operating Model

## Status

SUPERSEDED BY ADR 0013

Note: ce modele a ete remplace par le duo GPT API + Claude API.
Voir `docs/decisions/0013-dual-model-operating-model.md` pour le modele operatoire actuel.
Codex (l'app) n'est plus dans le pipeline autonome.

## Context

`Project OS` doit avancer vite sans perdre:

- la coherence
- la qualite
- la securite
- la verite locale

La grande fenetre de contexte de l'API OpenAI est plus adaptee aux gros runs:

- audit massif
- design systeme
- patch-plan de gros lot
- generation de branche sous forte contrainte

Mais le repo local, les tests reels et le runtime machine doivent rester sous controle strict.

## Decision

Le modele operatoire officiel devient:

- `OpenAI API` grande fenetre = `Lead Agent`
- `Codex` = `Command Board`
- `Project OS runtime` = verite machine et evidence

Le systeme suit donc un workflow hybride:

1. direction
2. context pack
3. mega prompt
4. run API
5. inspection locale
6. integration

## Consequences

### Positives

- meilleure exploitation du contexte long
- meilleur parallelisme de travail
- plus de puissance sur les gros arbitrages
- meilleure separation entre pensee large et integration reelle

### Contraintes

- les mega prompts doivent etre strictement cadres
- les sorties API doivent etre structurees
- aucune integration directe sans verification locale
- la memoire canonique et les decisions confirmees doivent rester explicites

## Rules

- les gros runs API declarent leurs skills de run
- `Codex` garde un role d'inspection severe
- le runtime local reste la verite finale
- les changements majeurs doivent etre notes en `DECISION CONFIRMED` ou `DECISION CHANGED`

## References

- `PROJECT_OS_MASTER_MACHINE.md`
- `docs/architecture/HYBRID_LARGE_CONTEXT_WORKFLOW.md`

