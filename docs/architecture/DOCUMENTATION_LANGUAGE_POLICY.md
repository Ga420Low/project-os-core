# Documentation Language Policy

## Objet

Eviter le bilinguisme flou.

La regle retenue pour `Project OS` est simple:

- francais pour la couche humaine et doctrinale
- anglais pour la couche machine et canonique

## Regle centrale

`French for doctrine, English for machine contracts.`

## Francais obligatoire

Le francais est la langue par defaut pour:

- doctrine produit
- ADR et decisions operatoires
- runbooks humains
- explications fondateur
- outputs operateur
- syntheses, arbitrages et policies d'usage

But:

- penser et arbitrer dans la langue naturelle du fondateur
- eviter une doc "traduite dans la tete"
- garder les regles operatoires claires

## Anglais obligatoire

L'anglais est obligatoire pour:

- code
- noms de types
- enums
- identifiants de champs
- schemas JSON
- payloads
- tables et colonnes DB
- noms de fichiers machine-first quand ils servent de contrat
- event names, statuses, route reasons, capability names

But:

- garder des contrats stables
- eviter les doubles noms selon la langue
- faciliter les integrations externes

## Regle de nommage

Un concept canonique ne doit pas changer de nom selon le contexte.

Exemples corrects:

- explication humaine: `preuve canonique enregistree`
- terme machine: `live_bridge_proof`

- explication humaine: `voie locale Windows-first`
- terme machine: `local_model_route`

- explication humaine: `route locale S3`
- terme machine: `s3_local_route`

Exemples a eviter:

- `thread binding`, `liaison de thread`, `thread link`, `binding de fil`
- `preuve live`, `preuve runtime`, `validation live`, sans distinguer le terme machine

## Regle d'introduction d'un concept

Quand un concept important apparait pour la premiere fois:

1. on introduit le terme humain en francais
2. on donne le terme canonique anglais entre backticks si necessaire
3. ensuite on reste stable

Exemple:

- `preuve canonique enregistree` (`live_bridge_proof`)

## Regle pour les docs mixtes

Une doc peut etre majoritairement en francais tout en gardant:

- les enums en anglais
- les noms de commandes exacts
- les noms de champs exacts
- les IDs et contrats exacts

Il ne faut pas "traduire" les contrats machine dans la prose au point de creer une seconde terminologie.

## Regle pour l'operateur

Les messages visibles par le fondateur restent en francais clair.

Les termes machine peuvent apparaitre seulement si:

- ils sont utiles pour diagnostiquer
- ils sont cites exactement
- ils restent secondaires par rapport a l'explication humaine

## Definition de mauvais etat

La langue devient un probleme quand:

- un meme concept a plusieurs noms
- une doc francaise contredit un contrat anglais
- un enum machine est "traduit" differemment selon les pages
- la taxonomie app / worker / profil / canal change selon le document

## Definition de bon etat

Le systeme est lisible si:

- la doctrine se lit naturellement en francais
- les contrats machine restent en anglais stable
- chaque concept important a un seul nom canonique
- la doc humaine n'introduit pas une deuxieme architecture lexicale
