# Memory, Storage and Ops Blueprint

## Statut

ACTIVE - Canonical doctrine aligned with the mother control plane

## But

Definir ou vit chaque type de memoire et de donnee pour que:

- la web app reste la maison mere
- le PC Windows reste protege
- les agents gardent une vraie capacite d'action
- l'etat du projet soit durable et consultable

## Decision nette

La memoire utile de `Project OS` n'est plus pensee comme `local-first sur le poste`.

La doctrine canonique est maintenant:

- `GitHub` = verite du code
- `DB centrale` = verite operatoire du projet
- `object storage` = verite des fichiers lourds et artefacts
- `runner Linux` = lieu d'execution et de travail jetable
- `8 To local` = miroir, archive, cold memory, pas source unique

## Role d'OpenClaw dans la memoire

`OpenClaw` peut renforcer la memoire sur:

- la discipline de session
- la continuite de contexte
- la compaction
- le routing runtime
- les hooks utiles a la memoire de travail

Mais `OpenClaw` ne remplace pas la memoire canonique `Project OS`.

`OpenClaw` n'est pas la source de verite pour:

- preferences fondateur
- decisions confirmees
- tasks
- docs operateur
- PDF
- timeline projet
- evidence canonique
- retrieval structure

Conclusion operative:

- `OpenClaw` = meilleur support runtime pour une memoire solide
- `Project OS` = vraie memoire d'entreprise
- la combinaison des deux est plus puissante que le systeme actuel seul

## Les 4 familles de memoire

### 1. Memoire code

Contenu:

- source code
- branches
- commits
- PR
- diffs

Source canonique:

- `GitHub prive`

Copies utiles:

- clone humain sur le PC
- workspace runner dans la VM Linux

### 2. Memoire projet

Contenu:

- docs
- notes
- PDF
- decisions
- preferences fondateur
- backlog
- issues
- timeline
- etat des runs
- references de fichiers

Source canonique:

- DB centrale du control plane

## Registre preferences et decisions

La maison mere doit garder un registre explicite de:

- preferences fondateur
- regles projet
- decisions confirmees
- decisions changees
- preferences remplacees

Objet vise:

- `scope`
- `rule`
- `status`
- `source`
- `applies_to`
- `created_at`
- `changed_at`
- `supersedes`

Statuts minimums:

- `proposed`
- `confirmed`
- `active`
- `superseded`
- `rejected`

Regle:

- une preference discutee n'existe vraiment pour le systeme que lorsqu'elle est promue dans ce registre

### 3. Memoire artefacts

Contenu:

- exports
- captures
- rapports
- PDFs generes
- bundles de preuve
- fichiers produits par les agents

Source canonique:

- object storage central

### 4. Memoire froide

Contenu:

- archives longues
- snapshots
- datasets
- historique lourd
- miroir de securite

Support principal:

- disque `8 To`

Regle:

- utile, important, mais jamais seule source de verite

## Repartition physique recommandee

### Control plane

Doit porter:

- DB centrale
- index de recherche
- metadata documents
- historique des runs
- etat temps reel rejouable

### Runner Linux

Doit porter:

- workspace de run
- cache de build
- logs temporaires
- artefacts avant promotion

Il ne doit pas porter:

- la seule base projet
- la seule copie des PDFs
- la seule copie de la memoire projet

### Windows host

Doit porter:

- clone humain
- outils dev
- cache de travail local
- archives locales utiles

Il ne doit pas porter:

- la seule source de verite du projet
- les agents autonomes directement sur l'OS

### Disque 8 To

Doit porter:

- `memory-code`
- `datasets`
- `archives`
- `exports`
- `snapshots`

Ne doit pas porter comme unique verite:

- la DB centrale
- les sessions vivantes
- les etats temps reel

## Regle speciale runners <-> 8 To

Le disque `8 To` ne doit pas etre monte sans contrat.

Decoupage recommande:

```text
8TB/
|-- memory-code/      (read-only par defaut)
|-- datasets/         (read-only par defaut)
|-- archives/         (read-only par defaut)
|-- exports/          (promotion controlee)
|-- workspace/        (ecriture runner)
`-- artifacts/        (ecriture runner)
```

Regles:

1. `read-only` par defaut pour les agents
2. ecriture seulement dans `workspace/` et `artifacts/`
3. promotion vers `archives/` ou le data plane par action explicite
4. pas de RW global sur tout le disque pour un agent

## Contrat temps reel

Le temps reel de la web app doit venir du control plane.

Cela veut dire:

- les evenements de runs doivent etre ecrits dans une source centrale
- la session operateur doit etre rejouable
- la coupure d'un websocket ne doit pas effacer l'historique

## Contrat de validation finale

Le data plane doit permettre de prouver:

- ce qui a ete propose
- ce qui a ete confirme
- par qui
- quand
- sur quelle base

Regle:

- pas d'evolution profonde du systeme sans trace de validation finale humaine

## Contrat PDF / docs / notion-like

Tout ce qui est lisible humain doit pouvoir vivre dans la maison mere:

- PDF
- doc projet
- readme internes
- notes de design
- plans
- artefacts de run utiles

Regle:

- un fichier produit par un agent n'existe vraiment pour le projet que lorsqu'il est:
  - soit dans `GitHub`
  - soit dans la DB/metadata centrale
  - soit dans l'object storage central

## Politique de verification

Chaque objet important doit etre verifiable par:

- un pointeur stable
- un auteur ou run source
- un horodatage
- un lien vers commit, issue, doc ou artefact

La maison mere doit montrer:

- qui a produit quoi
- dans quel contexte
- a partir de quel run
- ou vit l'objet reel

## Politique de backup

Backups minimaux:

1. `GitHub` comme sauvegarde de code distribuee
2. backup DB central
3. backup object storage
4. miroir local ou archive sur le disque `8 To`

Regle:

- les snapshots VM seuls ne suffisent pas
- les workspaces runner sont recreables, la DB et les objets non

## Phrase de reference

`La memoire de Project OS n'est pas un dossier magique sur le PC; c'est un systeme reparti entre GitHub pour le code, un control plane pour l'etat projet, un object storage pour les fichiers, et un disque 8 To pour l'archive et le miroir.`

## References

- `docs/architecture/PROJECT_OS_MOTHER_CONTROL_PLANE_ARCHITECTURE.md`
- `docs/architecture/HOST_WINDOWS_VM_LINUX_MATRIX.md`
- `docs/architecture/PHYSICAL_STORAGE_LAYOUT.md`
- `docs/roadmap/PROJECT_OS_PWA_VM_V0_1_PLAN.md`
