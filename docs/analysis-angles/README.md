# Analysis Angles V1

Ce dossier definit la couche de deliberation structuree de `Project OS`.

But:

- mieux arbitrer avant de coder, automatiser ou exposer une action
- reduire les angles morts
- organiser les contradictions utiles
- produire des sorties comparables, auditables et actionnables

Ce module ne remplace pas:

- le `Mission Router`
- le graphe canonique a 6 roles
- le `Guardian`
- la memoire canonique
- le runtime local

Il se branche au-dessus de ces briques pour aider:

- le `Planner`
- le `Critic`
- le `Guardian`
- le `Memory Curator`
- l'operateur fondateur quand un arbitrage important est requis

## V1 retenue

Angles actifs:

1. `Vision Strategy`
2. `Product Value`
3. `Technical Architecture`
4. `Execution Delivery`
5. `Operations Workflow`
6. `Security Governance`
7. `Red Team`
8. `Clarity Anti-Bullshit`
9. `Research Exploration`

Angles reserves mais documentes:

10. `Financial Leverage`
11. `Legal Compliance`
12. `Brand Trust`

Regle dure:

- les angles sont des fonctions cognitives bornees
- ce ne sont pas des personnages
- ils ne debattent jamais librement
- ils n'ont aucune autorite d'execution directe
- leur sortie doit converger vers une synthese arbitree puis vers une decision nette

## Ordre de lecture

1. `00-framework.md`
2. `01-design-principles.md`
3. `02-debate-protocol.md`
4. `03-output-schema.md`
5. `04-conflict-matrix.md`
6. `05-evaluation-rubric.md`
7. `06-activation-policy.md`
8. `07-meeting-types.md`
9. `08-decision-records.md`
10. `angles/`
11. `examples/`

## Regle d'integration

La verite courante reste dans:

- `AGENTS.md`
- `PROJECT_OS_MASTER_MACHINE.md`
- les ADR
- le runtime local

Toute implementation future doit:

- rester compatible avec `Discord` comme surface operateur
- garder `OpenClaw` comme shell operateur et non comme source de verite
- respecter la dualite `GPT API` lane code / `Claude API` lane audit et traduction
- ne jamais contourner le `Mission Router`
