# Politique d'activation

## But

Choisir peu d'angles, mais les bons.

## Activation axes

L'activation depend de:

1. type de sujet
2. niveau de risque
3. horizon temporel
4. cout potentiel de l'erreur
5. besoin de profondeur

## Regle par defaut

Ne jamais activer tous les angles par defaut.

## Questions d'activation

Avant d'ouvrir une session:

- est-ce une question simple ou une vraie decision ?
- y a-t-il de l'irreversible ?
- y a-t-il exposition externe ?
- y a-t-il argent, reputation, securite, conformite ?
- le sujet est-il local ou structurant ?
- une contradiction utile est-elle necessaire ?
- le gain analytique justifie-t-il le cout ?

## Matrice par sujet

### Proposition de feature

Haute:

- `Product Value`
- `Execution Delivery`
- `Vision Strategy`

Moyenne:

- `Technical Architecture`
- `Research Exploration`

Conditionnelle:

- `Security Governance`
- `Operations Workflow`

### Changement d'architecture

Haute:

- `Technical Architecture`
- `Operations Workflow`
- `Security Governance`

Moyenne:

- `Execution Delivery`
- `Red Team`
- `Clarity Anti-Bullshit`

Conditionnelle:

- `Vision Strategy`
- `Research Exploration`

### Workflow autonome

Haute:

- `Security Governance`
- `Operations Workflow`
- `Technical Architecture`
- `Execution Delivery`

Moyenne:

- `Red Team`
- `Clarity Anti-Bullshit`

Conditionnelle:

- `Vision Strategy`
- `Research Exploration`

### Priorisation roadmap

Haute:

- `Vision Strategy`
- `Product Value`
- `Execution Delivery`

Moyenne:

- `Technical Architecture`
- `Research Exploration`

Conditionnelle:

- `Operations Workflow`
- `Security Governance`

### Incident operationnel

Haute:

- `Operations Workflow`
- `Technical Architecture`
- `Security Governance`
- `Execution Delivery`

Moyenne:

- `Red Team`
- `Clarity Anti-Bullshit`

Basse:

- `Vision Strategy`
- `Research Exploration`

### Confiance ou comportement externe

Haute:

- `Security Governance`
- `Clarity Anti-Bullshit`
- `Product Value`

Moyenne:

- `Red Team`

Conditionnelle:

- `Brand Trust`
- `Legal Compliance`

## Regles de silence des angles

Exemples:

- `Vision Strategy` doit rester discret sur un hotfix sauf si la correction change la trajectoire structurelle.
- `Research Exploration` doit rester discret sur une stabilisation urgente.
- `Operations Workflow` doit rester discret sur un micro-ajustement de wording.
- `Clarity Anti-Bullshit` doit rester leger sur de la plomberie purement interne si la sortie est deja schema-bound.

## Surcharges de risque

Si le risque est `high` ou `critical`, forcer au minimum:

- `Security Governance`
- `Red Team`
- `Clarity Anti-Bullshit`

Si une representation externe est impliquee, considerer:

- `Product Value`
- `Brand Trust`
- `Legal Compliance`

Si la frontiere d'autonomie change, forcer:

- `Security Governance`
- `Operations Workflow`
- `Technical Architecture`
- `Red Team`

## Taille de reunion recommande

- reunion legere: 3 a 4 angles
- reunion standard: 5 a 7 angles
- grande reunion: 8 angles max en V1

Seuls les cas exceptionnels doivent depasser 8.
