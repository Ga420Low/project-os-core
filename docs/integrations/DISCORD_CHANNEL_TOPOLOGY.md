# Discord Channel Topology

`Discord` est le hub humain de `Project OS`.

Le but n'est pas de tout melanger dans un seul salon.
Le but est d'avoir une topologie simple, lisible et scalable.

## Salons cibles

### `#pilotage`

Usage:

- discussion normale
- idees
- direction
- arbitrages
- syntheses finales de reunion
- go / stop
- doutes

Style:

- humain
- souple
- clair

### `#runs-live`

Usage:

- feed compact des runs
- cartes d'etat
- progression
- cout
- verdicts
- ouverture ou lien vers un thread si un run demande plus qu'une carte compacte

Style:

- peu de texte
- compact
- visible

### `#approvals`

Usage:

- validations de risque
- demandes budget exceptionnel
- permissions speciales
- approvals sensibles
- miroir des decisions de reunion seulement si le sujet est sensible

### `#incidents`

Usage:

- blocages reels
- erreurs
- reprises
- alertes

### Threads par mission

Usage:

- isoler une mission longue
- regrouper contexte, cartes, rapports et arbitrages
- porter les `meeting_thread` multi-angles visibles

## Regles

- `Discord` n'est pas la memoire canonique
- `Discord` n'est pas la verite machine
- `Discord` est l'interface operateur
- les promotions vers la memoire durable sont selectives

## Mapping salon -> mode

- `#pilotage` -> `discussion`, `architecte`
- `#runs-live` -> `builder`, `reviewer`, `incident`
- `#approvals` -> `gardien`
- `#incidents` -> `incident`, `gardien`

## Cartes de run

Dans `#runs-live`, le format cible est une carte compacte avec:

- nom du lot
- branche
- phase
- cout
- tests
- verdict
- lien artefact ou dashboard

Pas de long texte par defaut.

## Profils de sortie Discord

- `notification_card` -> `#runs-live`, validations courtes, clarifications courtes, 3 lignes max
- `meeting_thread` -> thread visible depuis `#pilotage` ou `#incidents`, format structure
- `founder_synthesis` -> `#pilotage`, recap final concis apres une reunion ou un arbitrage dense

## Voix

Les vocaux ne creent pas de voie parallele.

Pipeline:

- vocal
- transcription
- classification
- passage dans le meme pipeline Discord

## Cible

Le systeme doit permettre:

- discussion fluide
- execution silencieuse
- supervision visuelle
- approvals clairs
- incidents propres
