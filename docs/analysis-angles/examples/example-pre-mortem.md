# Exemple - Pre-Mortem

## Topic

Systeme de reunion Discord semi-visible avant preuve complete de confiance operateur live.

## Meeting type

`pre_mortem`

## Activated angles

- `Security Governance`
- `Red Team`
- `Operations Workflow`
- `Technical Architecture`
- `Clarity Anti-Bullshit`

## Brief

- objective: identifier comment le systeme de reunion pourrait echouer avant implementation
- constraints:
  - ne doit pas inonder Discord
  - ne doit pas creer de fausse source de verite
  - ne doit pas contourner les approvals
- risk: high
- requested output: carte d'echec et garde-fous

## Main risks found

- Discord devient par accident une seconde memoire
- le debat visible cree une fausse profondeur sans decision
- trop d'angles s'activent par defaut
- le fondateur voit plus de bruit, pas un meilleur jugement
- le moderator devient un dictateur implicite

## Recommendation

- un seul bot
- reunions basees sur thread
- strict message templates
- etat final obligatoire
- decision record promu, pas le transcript

## Final decision state

`approved_with_conditions`
