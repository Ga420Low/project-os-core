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
