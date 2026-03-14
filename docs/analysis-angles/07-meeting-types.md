# Types de reunion

## But

Standardiser les reunions multi-angles utiles.

## Catalogue des reunions

### `implementation_review`

Question:

- faut-il coder maintenant, dans quel ordre, avec quels garde-fous ?

Angles par defaut:

- `Product Value`
- `Technical Architecture`
- `Execution Delivery`
- `Operations Workflow`
- `Security Governance`
- `Red Team`
- `Clarity Anti-Bullshit`

### `architecture_review`

Question:

- est-ce que cette structure tient, reprend, evolue et reste auditable ?

Angles par defaut:

- `Technical Architecture`
- `Operations Workflow`
- `Security Governance`
- `Execution Delivery`
- `Red Team`
- `Clarity Anti-Bullshit`
- `Research Exploration`

### `strategy_council`

Question:

- faut-il aller dans cette direction, et pourquoi maintenant ?

Angles par defaut:

- `Vision Strategy`
- `Product Value`
- `Execution Delivery`
- `Research Exploration`
- `Red Team`
- `Clarity Anti-Bullshit`

Conditionnel:

- `Financial Leverage`

### `pre_mortem`

Question:

- comment ce choix peut-il foirer avant meme qu'on le lance ?

Angles par defaut:

- `Security Governance`
- `Red Team`
- `Operations Workflow`
- `Technical Architecture`
- `Clarity Anti-Bullshit`

Conditionnel:

- `Legal Compliance`
- `Financial Leverage`

### `trust_review`

Question:

- comment une action, un message ou une surface externe peut-elle nuire a la confiance ?

Angles par defaut:

- `Product Value`
- `Security Governance`
- `Red Team`
- `Clarity Anti-Bullshit`

Conditionnel:

- `Brand Trust`
- `Legal Compliance`

## Etats de reunion

- `draft`
- `opened`
- `brief_ready`
- `initial_round`
- `contradiction_round`
- `synthesis_ready`
- `awaiting_founder`
- `approved`
- `approved_with_conditions`
- `needs_narrower_scope`
- `needs_more_evidence`
- `blocked`
- `converted_to_implementation_plan`
- `archived`

## Sorties requises

Chaque reunion doit produire:

- un `MeetingBrief`
- zero ou plusieurs `AngleResponse`
- zero ou plusieurs `ContradictionReply`
- un `MeetingSynthesis`
- eventuellement un `DecisionRecord`

## Regle de completude

Aucune reunion n'est complete sans:

- un etat final
- une recommandation
- une prochaine etape ou une non-action explicite
