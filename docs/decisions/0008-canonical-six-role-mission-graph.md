# ADR 0008 - Canonical Six Role Mission Graph

## Decision

L'orchestration de `Project OS` part sur un graphe mission canonique unique avec 6 roles:

- `Operator Concierge`
- `Planner`
- `Memory Curator`
- `Critic`
- `Guardian`
- `Executor Coordinator`

Le graphe est d'abord implemente comme contrat interne et service canonique.
`LangGraph` sera branche ensuite sur cette forme, pas l'inverse.

## Why

- garder une structure lisible sur 6 mois
- separer clairement accueil operateur, planification, memoire, critique, policy et execution
- eviter de multiplier trop tot les graphes metier

## Consequences

- toute mission longue devra pouvoir etre projetee sur cette sequence
- `ExecutionTicket` ne peut etre emis que par `Executor Coordinator`
- `LangGraph` ne remplacera ni la DB canonique ni la memoire canonique
