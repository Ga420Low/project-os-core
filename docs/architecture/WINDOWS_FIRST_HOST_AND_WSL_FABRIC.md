# Windows-First Host And WSL Fabric

## Decision

`DECISION CONFIRMED`

`Project OS` reste `Windows-first`.

Le poste Windows est la verite operatoire principale du systeme.
`WSL2` n'est pas la fondation unique du produit.
Il devient un sous-systeme optionnel pour des cellules de travail isolees par projet quand cela apporte un vrai gain.

## Pourquoi cette decision

La cible finale n'est pas un simple gateway Linux.
La cible finale est un systeme capable de produire un vrai travail "humain" sur la machine du fondateur:

- travailler dans des applications Windows reelles
- agir dans l'editeur `UEFN`
- piloter le web, des apps metier, des fichiers et des workflows machine
- garder une verite runtime unique et auditable

Si le coeur du systeme bascule entierement dans `WSL2`, on cree une fracture inutile entre:

- la machine reelle (`Windows`)
- les applications a piloter (`UEFN`, navigateurs, outils locaux)
- la memoire et les preuves du systeme
- les workers et les chemins

Cette fracture est mauvaise pour:

- l'auditabilite
- la simplicite operatoire
- les integrations UI Windows
- la perception machine
- les automatismes "humains" sur le poste

## Ce qu'est `WSL2`

`WSL2` est un environnement Linux execute dans Windows.

Il est utile quand on veut:

- un outillage Linux propre
- des services plus naturels sous Linux
- des deps et workflows plus stables que sur Windows natif
- des environnements isoles par projet

Il n'est pas utile comme fondation unique si le produit doit agir en priorite sur l'hote Windows.

## Architecture cible

Le modele retenu est:

- `Windows host` = verite operatoire et machine principale
- `Project OS core` = cerveau, memoire, router, approvals, evidence
- `OpenClaw` = facade operateur et gateway channel
- `Discord` = surface operateur
- `GPT API` + `Claude API` = couches cognitives
- `WSL2` = cellules de travail optionnelles par projet ou par domaine

## Ce qui reste sur l'hote Windows

Les fonctions suivantes restent attachees a l'hote Windows:

- runtime canonique
- base SQLite canonique
- memoire primaire
- journal et evidence
- approvals
- supervision locale
- perception Windows
- workers Windows
- integration `UEFN`
- orchestration centrale
- source de verite Git du produit

En pratique, cela veut dire que les racines suivantes restent cote hote:

- `D:\ProjectOS\runtime`
- `D:\ProjectOS\memory_hot`
- `D:\ProjectOS\memory_warm`
- `E:\ProjectOSArchive`

## Ce qui peut vivre dans `WSL2`

`WSL2` peut heberger des cellules de travail specialisees, par exemple:

- un projet code/web avec deps Linux
- un worker browser auxiliaire
- un environnement de build ou de scraping
- un environnement de tests isole
- un projet secondaire qui ne doit pas polluer l'hote

Ces cellules ne deviennent jamais la verite canonique du systeme.

## Modele "WSL fabric"

Le futur vise n'est pas `un seul WSL`.
Le futur vise un `tissu` de cellules `WSL2`, potentiellement plusieurs en parallele.

Exemples:

- `wsl-project-os-core`
- `wsl-uefn-tools`
- `wsl-web-ops`
- `wsl-client-project-a`
- `wsl-client-project-b`

Chaque cellule a:

- son workspace
- ses dependances
- ses caches
- ses outils
- ses secrets projet si necessaire
- ses workers locaux

Mais toutes sont supervisees par le meme hote `Windows`.

## Regle de supervision

Le host Windows supervise les cellules `WSL2`.

Cela implique:

- lancement et arret depuis le host
- observation depuis le host
- handoff et preuves promues vers le host
- aucune cellule `WSL2` n'ecrit directement sa propre verite canonique sans passer par `Project OS`

En clair:

- `WSL2` produit du travail
- `Project OS` decide, journalise et conserve

## Role de `OpenClaw`

`OpenClaw` reste un composant d'interface et de transport.

Regles:

- il ne devient pas la verite machine
- il ne devient pas le gestionnaire principal de la memoire
- il ne decide pas seul des workers
- il peut pointer plus tard vers des workers ou projets vivant dans `WSL2`
- il peut rester natif Windows tant que cela sert mieux l'operateur et le pilotage machine

## Compatibilite avec `UEFN`

`UEFN` reste un cas decisif dans cette architecture.

Ici, `UEFN` doit etre lu comme:

- une app Windows cible
- et le futur nom d'un profil applicatif

Pas comme une categorie d'architecture a part entiere.

Cela force les points suivants:

- l'hote Windows garde la priorite
- les workers Windows restent de premiere classe
- la perception UI Windows ne doit pas dependre de Linux
- `WSL2` peut aider sur du code, des assets, des builds, des scripts, mais pas remplacer la machine operatoire

## Future-proofing retenu

Cette architecture reste future-proof parce qu'elle permet les deux:

- continuer en `Windows-first`
- ajouter des cellules `WSL2` sans refaire tout le coeur

Elle evite deux erreurs:

- tout mettre dans `WSL2` et perdre la proximite avec la machine reelle
- refuser `WSL2` et se priver d'isolations utiles par projet

## Strategie par phases

### Phase 1 - Host only

- `Project OS` et `OpenClaw` tournent sur Windows
- les workers vivent surtout sur l'hote
- aucune dependance structurelle a `WSL2`

### Phase 2 - First WSL cells

- ajout de 1 ou 2 cellules `WSL2` pour des projets ou workflows cibles
- orchestration toujours centralisee cote host
- evidences et resultats promus cote host

### Phase 3 - Multi-project fabric

- plusieurs cellules `WSL2` coexistent
- le `Mission Router` choisit si une mission reste sur host ou part vers une cellule
- chaque projet peut avoir sa cellule
- l'hote garde la vue globale et la priorite operateur

## Contrats a respecter plus tard

Quand le `WSL fabric` sera code, il faudra des contrats clairs:

- identite de cellule
- mapping projet -> cellule
- chemins promus host <-> WSL
- transfert d'artefacts
- journal d'execution
- health de cellule
- politique de secrets
- regles de destruction/recreation idempotentes

## Ce qu'on ne doit pas faire

- ne pas deplacer la memoire canonique dans `WSL2`
- ne pas faire de `WSL2` la seule voie d'execution
- ne pas casser les workers Windows pour suivre une mode Linux
- ne pas multiplier des cellules sans supervision centrale
- ne pas laisser un projet `WSL2` devenir un mini-systeme parallele non gouverne

## Resume operatoire

La vision cible est:

- `Windows` comme machine maitresse
- `Project OS` comme cerveau et verite
- `OpenClaw` comme facade operateur
- `UEFN` et les apps Windows comme terrain principal
- `WSL2` comme tissu futur de cellules de travail par projet

Ce choix garde le systeme compatible avec le vrai travail machine, tout en laissant la porte ouverte a un pilotage multi-projets plus propre dans le futur.
