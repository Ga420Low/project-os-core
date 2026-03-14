# Matrice de conflit

## But

Rendre les contradictions previsibles et utiles.

## Conflits naturels

| Angle A | Angle B | Pourquoi le conflit compte |
| --- | --- | --- |
| Vision Strategy | Research Exploration | La vision peut rejeter une exploration seduisante mais mal focalisee. |
| Vision Strategy | Execution Delivery | La vision veut du levier ; l'execution veut de la sequence et du fini. |
| Product Value | Technical Architecture | La valeur user peut pousser a livrer vite ; l'architecture peut exiger de la retenue structurelle. |
| Product Value | Security Governance | Le produit peut vouloir de la fluidite ; la securite peut imposer des frontieres plus dures. |
| Technical Architecture | Execution Delivery | L'architecture veut des frontieres propres ; l'execution veut un progres contraint maintenant. |
| Technical Architecture | Operations Workflow | L'architecture peut sur-idealiser ; l'ops verifie qui vivra avec le systeme au quotidien. |
| Operations Workflow | Research Exploration | La recherche ouvre l'espace ; l'ops protege la repetabilite et la maintenance. |
| Security Governance | Research Exploration | La recherche explore les capacites ; la securite bloque les extensions d'autonomie dangereuses. |
| Security Governance | Product Value | Le produit peut sur-prioriser la commodite ; la securite protege les frontieres. |
| Red Team | Tous | Red Team existe pour attaquer les hypotheses et les plans de chemin idealise. |
| Clarity Anti-Bullshit | Tous | Clarity force les affirmations a devenir explicites, falsifiables et operationnelles. |

## Allies naturels

| Angle | Allies naturels |
| --- | --- |
| Vision Strategy | Product Value, Research Exploration |
| Product Value | Vision Strategy, Execution Delivery |
| Technical Architecture | Operations Workflow, Security Governance |
| Execution Delivery | Product Value, Operations Workflow |
| Operations Workflow | Technical Architecture, Execution Delivery |
| Security Governance | Technical Architecture, Red Team |
| Red Team | Security Governance, Clarity Anti-Bullshit |
| Clarity Anti-Bullshit | Red Team, Technical Architecture |
| Research Exploration | Vision Strategy, Product Value |

## Contextes secondaires

Chaque angle doit avoir des contextes ou il devient secondaire:

- `Vision Strategy`: reparation urgente d'incident
- `Product Value`: correction infra profonde sans impact user
- `Technical Architecture`: micro-ajustement de wording
- `Execution Delivery`: cadrage de recherche long horizon
- `Operations Workflow`: choix lexical minuscule
- `Security Governance`: ideation interne sans exposition
- `Red Team`: correction de formatage triviale
- `Clarity Anti-Bullshit`: plomberie interne peu risquee quand les sorties sont deja strictes
- `Research Exploration`: stabilisation urgente de production

## Protocole de conflit

Quand une paire est selectionnee:

1. L'angle A pose sa position.
2. L'angle B pose sa position.
3. Le `Moderator` demande une contradiction.
4. Une reponse courte suit le schema de contradiction.
5. Le desaccord est ensuite:
   - garde ouvert dans la synthese
   - resolu par conditions
   - escalade a l'arbitrage fondateur

## A ne pas faire

- ne pas forcer chaque angle a repondre a tous les autres
- ne pas creer de desaccord decoratif
- ne pas prolonger un conflit quand il ne change plus la decision
