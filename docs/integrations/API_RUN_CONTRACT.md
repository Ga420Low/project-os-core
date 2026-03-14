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

Si le fondateur dit explicitement dans la conversation courante de lancer l'API:

- `Claude API` peut traduire l'intention operateur en contrat exploitable
- le runtime peut enregistrer le `go` correspondant
- `GPT API` peut lancer le run sans demander une deuxieme action manuelle

Ce `go` doit rester trace dans les notes d'approbation du contrat.

## Contradiction guard

Un run API a le droit de contredire le brief si celui-ci est:

- contradictoire
- dangereux
- sous-specifie
- hors scope
- en conflit avec la verite repo/runtime

Dans ce cas:

- il ne doit pas deviner et continuer
- il doit passer en `clarification_required`
- il doit produire une question bloquante minimale
- il doit recommander l'amendement du contrat
- il ne doit pas presenter un patch final comme si le lot etait valide

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
  - en cas de clarification requise
  - a la fin avec le rapport final

## Reprise apres clarification

Le modele retenu est:

- contrat amende
- nouveau `go` ou `go avec correction`
- nouvelle execution

La reprise libre sans nouvelle validation n'est pas autorisee.

## Visibilite obligatoire

Avant tout run reel:

- le dashboard local doit etre disponible sur le PC
- `Project OS` doit le lancer automatiquement si necessaire
- l'operateur doit pouvoir voir le run vivre en direct sans devoir le lancer a la main

Si cette visibilite ne peut pas etre fournie:

- le run doit etre bloque

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

- review cross-model par Claude API (audit du code produit par GPT API)
- verification locale (tests, coherence repo)
- rapport traduit en francais humain pour le fondateur
- integration ou rejet par le fondateur (via Discord ou terminal)
