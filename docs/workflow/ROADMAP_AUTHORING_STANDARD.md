# Roadmap Authoring Standard

## Objet

Ce document fixe le format minimal des feuilles de route canoniques dans `Project OS`.

But:

- rendre une roadmap portable dans une autre conversation
- expliciter d'ou viennent les idees retenues
- expliquer pourquoi un ordre d'execution est choisi
- eviter les roadmaps jolies mais pauvres en preuves

## Regle simple

Une roadmap ne doit pas seulement dire `quoi faire`.
Elle doit aussi dire:

- `pourquoi`
- `a partir de quoi`
- `de qui on s'inspire`
- `ce qu'on garde ou adapte`
- `comment cela entre dans le repo reel`

## Sections minimales obligatoires

Toute roadmap canonique doit contenir au minimum:

1. `Statut`
2. `But`
3. `Point de depart reel`
4. `Regles d'architecture`
5. `Pourquoi cet ordre`
6. `Packs`, `phases` ou `lots`
7. `Sources` ou `Cartographie externe`

## Contrat des sources

Quand une roadmap s'appuie sur des sources externes, elle doit expliciter:

- `Sources primaires`
- `Ce qu'on recupere`
- `Ce qu'on n'importe pas`
- `Ou ca entre`
- `Decision`

Format recommande:

```md
### Nom de la source

Sources primaires:

- lien 1
- lien 2

Ce qu'on recupere:

- pattern 1
- pattern 2

Ce qu'on n'importe pas:

- limite 1
- limite 2

Ou ca entre:

- `Pack X`
- `Pack Y`

Decision:

- `KEEP` ou `ADAPT` ou `DEFER`
```

## Contrat du pourquoi

Chaque pack, lot ou phase doit dire:

- pourquoi il vient maintenant
- pourquoi il ne vient pas avant
- quelle dette ou quel risque il ferme
- quel composant existant il reutilise
- quelle case devra etre cochee a sa fermeture dans la roadmap canonique et dans `docs/roadmap/BUILD_STATUS_CHECKLIST.md`

Le `pourquoi` ne doit pas etre seulement implicite dans les bullets.

## Contrat de fermeture

Quand un pack, lot ou phase est termine:

- cocher immediatement sa case dans la roadmap canonique
- cocher immediatement sa case miroir dans `docs/roadmap/BUILD_STATUS_CHECKLIST.md`
- si tous les sous-items d'un lot sont termines, cocher aussi le parent
- lancer ensuite `py scripts/project_os_entry.py docs audit`

Une cloture n'est pas complete tant que ces cases ne sont pas synchronisees.

## Contrat repo-first

Avant de proposer une nouvelle couche, la roadmap doit dire:

- ce qui existe deja dans le repo
- ce qui existe deja hors du coeur mais reste reutilisable
- ce qui manque reellement

Une roadmap doit preferer:

- `extraire`
- `canonicaliser`
- `etendre`

plutot que:

- `recreer`
- `dupliquer`
- `introduire une seconde verite`

Si la roadmap depend fortement de systemes externes, de stacks GitHub ou de benchmarks, elle doit pointer vers un dossier systeme canonique dans `docs/systems/` ou en creer un.

## Contrat de precision

Quand une roadmap parle de refactor ou d'implementation, elle doit nommer:

- les packages a ajouter
- les packages a etendre
- les tables a ajouter si la DB change
- les services a brancher

Elle ne doit pas rester au niveau slogan si une proposition structurelle est faite.

## Contrat de decision

Si plusieurs inspirations existent, la roadmap doit dire clairement:

- ce qu'on `KEEP`
- ce qu'on `ADAPT`
- ce qu'on `DEFER`
- ce qu'on `REJECT`

## Non-buts

Le document ne force pas:

- un format unique de markdown
- un nombre fixe de packs
- des citations academiques si elles n'apportent rien

Mais il force:

- des sources quand elles existent
- un `pourquoi` explicite
- un ancrage dans le repo reel

## Reference

- `AGENTS.md`
- `docs/workflow/SYSTEM_DOSSIER_AUTHORING_STANDARD.md`
