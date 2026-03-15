# Discord Channel Topology

`Discord` est le hub humain de `Project OS`.

Le but n'est pas de tout melanger dans un seul salon.
Le but est d'avoir une topologie simple, lisible et scalable.

## Salons cibles

### `#general`

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

Note:

- `#general` devient l'entree fondatrice par defaut
- a terme, c'est le salon intuitif principal pour parler a `Project OS`

### `#pilotage`

Usage:

- compatibilite de transition
- anciens workflows ou habitudes encore vivants
- quelques syntheses republiables tant que la migration vers `#general` n'est pas finie

Style:

- meme voix que `#general`
- pas de logique differente

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

- `#general` -> `discussion`, `architecte`
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
- `meeting_thread` -> thread visible depuis `#general`, `#pilotage` ou `#incidents`, format structure
- `founder_synthesis` -> `#general`, recap final concis apres une reunion ou un arbitrage dense

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
