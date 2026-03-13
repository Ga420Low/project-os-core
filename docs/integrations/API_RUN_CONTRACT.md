# API Run Contract

Un gros run API ne part pas directement.

Il passe par un contrat de run.

## But

Eviter:

- les runs flous
- les runs qui depensent sans cadre
- les runs qui partent sur la mauvaise branche
- les runs qui parlent beaucoup mais produisent peu

## Contenu obligatoire

Un contrat de run doit contenir:

- but
- lot vise
- branche cible
- mode (`audit`, `design`, `patch_plan`, `generate_patch`)
- ce que le run fera
- ce qu'il ne fera pas
- modele prevu
- cout estime
- criteres de reussite

## Decision humaine

Reponses autorisees:

- `go`
- `go avec correction`
- `stop`

Sans validation:

- pas de run reel

## Vie du contrat

Statuts:

- `proposed`
- `approved`
- `rejected`
- `executed`

## Politique de parole

Une fois le contrat approuve:

- le run se tait
- l'UI et les cartes prennent le relais
- le texte naturel revient seulement:
  - en cas de blocage reel
  - a la fin avec le rapport final

## Rapport final associe

A la fin, le run doit produire un rapport en francais simple:

- verdict
- ce qui a ete fait
- ce qui a reussi
- ce qui bloque
- cout
- risques
- suite recommandee

## Review obligatoire

Le run ne donne jamais l'autorisation de pousser seul.

Il faut ensuite:

- revue `Codex`
- verification locale
- tests
- integration ou rejet
