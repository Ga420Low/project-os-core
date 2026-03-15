# System Dossier Authoring Standard

## Objet

Ce document fixe le format minimal des dossiers systeme canoniques dans `Project OS`.

Un dossier systeme sert a suivre:

- des systemes externes
- des repos GitHub
- des benchmarks
- des bridges
- des stacks produit
- des outils a tester ou a laisser de cote

Il ne remplace pas une roadmap.

La roadmap dit:

- dans quel ordre on construit
- pourquoi cet ordre
- comment cela s'integre dans le repo

Le dossier systeme dit:

- quoi tester d'abord
- quoi seulement etudier
- quoi rejeter pour l'instant
- pourquoi chaque source merite ou non une integration

## Emplacement canonique

Les dossiers systeme vivent dans:

- `docs/systems/`

Le standard vit dans:

- `docs/workflow/SYSTEM_DOSSIER_AUTHORING_STANDARD.md`

## Regle simple

Un dossier systeme ne doit pas etre un dump de liens.

Il doit permettre a une autre conversation ou a un autre agent de comprendre:

- ce qui vaut une action concrete maintenant
- ce qui reste seulement prometteur
- ce qui est trop riske, trop flou ou trop cher

## Sections minimales obligatoires

Tout dossier systeme canonique doit contenir au minimum:

1. `Statut`
2. `But`
3. `Point de depart reel`
4. `Hypothese de travail`
5. `A faire`
6. `A etudier`
7. `Sources`

Sections optionnelles mais recommandees:

- `A rejeter pour maintenant`
- `Ordre de test`
- `Preuves a obtenir`
- `Risques`

## Contrat d'une entree systeme

Chaque entree doit utiliser au minimum ce schema:

```md
### Nom du systeme

Etat:

- `A_FAIRE` ou `A_ETUDIER` ou `REJECT`

Pourquoi il compte:

- raison 1
- raison 2

Ce qu'on recupere:

- pattern 1
- outil 1

Ce qu'on n'importe pas:

- limite 1
- dette 1

Preuves a obtenir:

- preuve 1
- preuve 2

Ou ca entre dans Project OS:

- `package`, `pack`, `service` ou `workflow`

Sources primaires:

- lien 1
- lien 2
```

## Contrat de priorisation

Une entree va en `A faire` seulement si:

- elle ferme un risque ou une inconnue immediate
- elle peut etre testee rapidement
- elle a une utilite plausible dans le repo reel

Une entree va en `A etudier` si:

- elle est prometteuse mais non prouvee
- elle depend d'une preuve technique absente
- elle est trop lourde pour etre branchee tout de suite

Une entree va en `REJECT` si:

- elle duplique une brique deja adequate
- elle force une seconde verite
- elle est trop cloud-first, trop opaque ou hors budget

## Contrat des sources

Un dossier systeme doit privilegier:

- docs officielles
- repos officiels
- papiers originaux
- benchmarks officiels

Il doit eviter de baser une decision importante sur:

- un fork sans activite claire
- une video seule
- un post Reddit seul
- un resume secondaire sans source primaire

## Contrat repo-first

Avant de classer un systeme, le dossier doit dire:

- ce qui existe deja dans le repo
- ce qui manque reellement
- pourquoi ce systeme est utile ici et pas seulement "impressionnant"

## Contrat de preuve

Pour `A_FAIRE`, la preuve attendue doit etre ecrite noir sur blanc.

Exemples:

- `ouvre UEFN et retourne la liste des assets d'un niveau`
- `parse un screenshot UEFN et retrouve 80% des controles attendus`
- `rejoue une macro de 10 etapes sans divergence`

## Reference

- `AGENTS.md`
- `docs/workflow/ROADMAP_AUTHORING_STANDARD.md`
