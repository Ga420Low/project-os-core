# Project OS Mother Control Plane Architecture

## Statut

ACTIVE - Canonical architecture target after the V0.1 bootstrap

## But

Figer le modele cible de `Project OS` comme maison mere unique du projet:

- pilotage complet depuis la web app
- acces PC + iPad + iPhone
- agents libres mais isoles
- Windows protege
- etat projet centralise et lisible

## Decision nette

`Project OS` ne doit pas etre:

- un terminal fragile ouvert sur le PC
- une UI qui depend d'un shell local deja lance
- un simple proxy vers `Codex app`

`Project OS` doit devenir:

- une maison mere toujours disponible
- un control plane central
- un execution plane isole
- un data plane durable

Pour les arbitrages "meilleure option par branche", la reference canonique est
maintenant:

- `docs/architecture/PROJECT_OS_ARCHITECTURE_DECISION_MATRIX.md`

## Base technique retenue

Le socle technique cible n'est pas `Project OS` seul.

La pile retenue est:

- `OpenClaw` = substrate d'autonomie, orchestration et boucle agent
- `Codex CLI` = moteur officiel d'execution code, shell, patch et repo work
- `Project OS` = couche produit, maison mere, memoire, docs, audit et UI operateur

Regle:

- `OpenClaw` ne doit pas etre avale trop tot par un gros fork sale
- `Codex CLI` ne doit pas etre traite comme un simple chat secondaire
- `Project OS` doit rester la surcouche proprietaire qui apporte la vraie valeur produit

## Doctrine de merge progressive

Le merge propre se fait dans cet ordre:

1. garder `OpenClaw` le plus upstream possible
2. brancher `Codex CLI` comme executor officiel
3. remonter progressivement les briques proprietaires `Project OS`
4. mesurer avant de fusionner plus profond

Ce qu'il faut privilegier au debut:

- adapters
- wrappers
- bridges
- policies
- observabilite
- storage

Ce qu'il faut eviter:

- modifier upstream partout
- fusionner `OpenClaw` et `Project OS` trop tot
- mettre la logique metier `Project OS` dans le coeur agent
- perdre la lisibilite entre runtime, UI, memoire et policies

## Regle centrale

Le Windows host reste un PC normal.

Il peut fournir:

- puissance CPU
- RAM
- GPU plus tard si necessaire
- stockage local

Mais il ne doit pas heberger directement:

- des agents autonomes sur l'OS Windows
- un shell IA avec acces global au host
- la seule copie de l'etat du projet
- la seule surface d'acces distant

## Vue d'ensemble

```text
Clients humains
+-------------------------------------------------------------+
| PC Windows | iPad Pro | iPhone | navigateur de secours     |
+---------------------------+---------------------------------+
                            |
                            v
Control Plane - maison mere toujours on
+-------------------------------------------------------------------+
| PWA privee | chat Codex | timeline | docs | PDF | issues | logs   |
| terminal fallback | approvals | session state | auth | API        |
| base projet | index de recherche | object storage metadata         |
+---------------------------+---------------------------------------+
                            |
               +------------+-------------+-----------------------------+
               |                          |                             |
               v                          v                             v
Execution Plane                    Recovery Plane                 Data Plane
+--------------------------------+ +---------------------------+ +----------------------------------+
| runner distant minimal always-on| | home relay always-on     | | GitHub prive = code canonique    |
| runner local Linux VM           | | wake PC / restart VM     | | DB centrale = etat projet        |
| workspaces jetables             | | relance services locales | | object storage = PDF, artefacts  |
| shell, builds, tests, agents    | | health local et power    | | index/search = retrieval projet  |
+--------------------------------+ +---------------------------+ | 8 To local = miroir / archive    |
                                                                  +----------------------------------+
```

## Les 3 plans

### 1. Control Plane

Le control plane est la vraie maison mere.

Il porte:

- la web app unique
- le chat operateur
- la timeline des runs
- les taches et issues
- la memoire projet lisible humain
- les PDFs, documents, notes et preuves indexees
- les approvals et blocages
- le terminal fallback
- l'API et les sessions

Regle:

- le control plane doit rester disponible meme si un runner tombe
- il doit etre accessible depuis PC, iPad et iPhone
- il ne doit pas dependre d'une session terminal ouverte sur Windows

### 2. Execution Plane

Le execution plane est la zone ou les agents travaillent.

Il porte:

- `runner distant minimal always-on`
- `Codex CLI`
- shell
- builds
- tests
- scripts
- workspaces Git
- jobs lourds

Regles:

- jamais d'agent autonome directement sur l'hote Windows
- les agents vivent dans des VMs Linux ou runners isoles
- un run peut casser son workspace, pas la machine perso
- les workspaces sont recreables
- le runner distant minimal garde le systeme utile quand le PC est eteint
- le runner local sert d'accelerateur et de zone de puissance, pas de dependance unique

### 3. Recovery Plane

Le `home relay` est une brique de reprise locale, pas une maison mere bis.

Il porte:

- wake-on-lan
- verification que le PC repond
- relance VM locale
- relance services locaux
- remontes d'etat locales simples

Regles:

- il ne porte ni la verite du code ni la verite operateur
- il ne remplace ni le control plane ni le runner distant minimal
- il sert a recuperer plus vite la puissance locale quand le PC est joignable

### 4. Data Plane

Le data plane porte l'etat durable.

Il se compose de:

- `GitHub prive` pour le code canonique
- `Postgres` ou DB centrale pour l'etat projet
- `object storage` pour les PDF, exports, captures, artefacts
- `index/search` pour la recherche documentaire et la memoire projet
- miroir local sur le disque `8 To` pour archive, cache et evidence froide

Regles:

- le code n'est pas canonique dans la VM
- la VM n'est pas la base de donnees du projet
- le disque 8 To n'est pas la seule source de verite
- la web app lit l'etat central, pas des JSON perdus dans un runtime

## Les 4 couches produit

### Couche A - Runtime noyau

- `OpenClaw`
- quasi upstream
- peu modifie
- responsable de la logique autonome et de l'orchestration

### Couche B - Execution adapters

- bridge `OpenClaw -> Codex CLI`
- repo adapter
- shell adapter
- task adapter
- evidence adapter

### Couche C - Project OS core

- memory
- docs
- PDF
- timeline
- issue/task model
- approvals
- audit
- search
- control APIs

### Couche D - Operator surface

- PWA
- mobile/tablet UX
- chat
- terminal fallback
- project views
- docs explorer
- run inspector

Regle:

- cette separation est la condition pour garder le systeme tenable dans le temps

## Frontieres de confiance

```text
Zone 1 - Clients humains
- PC Windows
- iPad
- iPhone

Zone 2 - Control plane
- surface visible
- auth
- API
- terminal fallback

Zone 3 - Runners
- execution risquee
- shell
- build
- agents

Zone 4 - Data plane
- code
- DB
- documents
- artefacts
- recherche
```

Regle de confiance:

- plus on descend de la zone 1 vers la zone 4, plus l'acces doit etre scope
- les runners ne recoivent que l'acces necessaire a leur run
- les clients humains ne parlent jamais directement au runner si le control plane est vivant
- le `home relay` n'a qu'un perimetre de reprise locale borne

## Repartition concrete des roles

### Windows host

Doit garder:

- navigateur
- VS Code
- Git local de travail humain
- outils graphiques
- Tailscale
- Hyper-V ou hyperviseur equivalent
- clones locaux de developpement
- miroir/archives sur le disque 8 To

Ne doit pas garder:

- agent autonome permanent sur l'OS host
- shell IA root sur Windows
- DB centrale du projet
- seule copie des PDFs et documents projet

### Runner local Linux VM

Doit garder:

- `Codex CLI`
- environnements de build
- workspaces Git jetables
- tests
- jobs agents
- acces controle a des dossiers de memoire/data

Ne doit pas garder:

- la verite unique du projet
- les credentials humains globaux
- le seul historique de docs, issues ou runs

### Runner distant minimal always-on

Doit garder:

- `Codex CLI`
- shell de secours
- workspaces Git standards
- jobs utiles quand le PC local est eteint
- bridge chat/utilitaire toujours disponible

Ne doit pas garder:

- toute la puissance lourde locale si elle peut rester sur le PC
- la seule copie des donnees projet
- des privileges broad sur le reseau maison

### Home relay

Doit garder:

- Tailscale
- wake/restart du PC
- relance du runner local et de la VM
- health checks locaux elementaires

Ne doit pas garder:

- la DB projet
- l'object storage
- le chat principal
- la verite projet

### Control plane distant toujours on

Doit garder:

- web app
- backend/API
- auth
- sessions
- historique des runs
- docs
- index
- terminal fallback

Ne doit pas executer seul:

- tout le travail lourd si le runner local existe
- les jobs a risque directement sur le host Windows

## Flux code et Git

```text
Humain sur PC
  -> modifie le repo local
  -> commit / push vers GitHub

Agent dans runner
  -> clone un workspace depuis GitHub
  -> modifie dans son workspace
  -> propose commit / branche / PR / patch

Control plane
  -> relie conversation, taches, runs et diffs
  -> garde l'historique humain et machine
```

Regles:

- `GitHub` = source de verite du code
- le clone Windows n'est pas la source globale
- le workspace runner n'est pas la source globale
- toute modif agent doit revenir vers Git via un chemin lisible

## Flux documents, PDF et memoire

```text
Import humain ou agent
  -> object storage
  -> index/search
  -> references dans la DB projet
  -> affichage dans la web app

Archive froide
  -> miroir sur le disque 8 To
  -> snapshots / exports / evidence
```

Regles:

- les PDF et docs utiles doivent etre consultables depuis la web app
- le disque 8 To sert de miroir, d'archive et de cold memory
- la navigation projet ne doit pas dependre d'un explorateur Windows a distance

## Regle speciale pour le disque 8 To

Le disque `8 To` est utile, mais il ne doit pas devenir une bombe.

Decoupage recommande:

- `memory-code/` = lecture seule par defaut
- `datasets/` = lecture seule par defaut
- `archives/` = lecture seule par defaut
- `exports/` = lecture seule ou promotion explicite
- `workspace/` = ecriture reservee aux runners
- `artifacts/` = ecriture reservee aux runners

Regles:

- montage `read-only` par defaut pour les agents
- ecriture seulement dans des zones dediees
- promotion manuelle ou controlee vers l'archive centrale

## Fallback et resilience

Si la web app ou le chat casse, l'operateur doit garder une trajectoire de reprise.

Niveaux obligatoires:

1. web app normale
2. terminal fallback integre dans la web app
3. acces d'urgence hors app au control plane

```text
Incident UI
  -> ouvrir terminal fallback
  -> demander un read-in au systeme
  -> relancer ou auditer le run

Incident runner
  -> control plane reste vivant
  -> status degrade mais visible
  -> bascule sur le runner distant minimal ou relance runner local

Incident PC Windows
  -> iPad/iPhone gardent acces au control plane
  -> le runner distant minimal continue a repondre
  -> le home relay peut tenter wake/restart/reprise locale

Incident maison locale
  -> control plane reste vivant
  -> home relay borne la reprise locale
  -> la maison mere ne depend pas du succes de cette reprise
```

## Contrat temps reel

La maison mere doit afficher en temps reel:

- etat du chat
- etat du runner distant
- etat du runner local
- etat du home relay
- etat des runs
- taches
- blocages
- artefacts produits
- modifications de fichiers et docs importantes

Regles:

- le temps reel ne doit pas casser la reprise
- tout event utile doit etre rejouable depuis la DB
- la session ne doit pas disparaitre si le websocket coupe

## Contrat humain final

Le dernier mot reste humain.

Regles:

- aucun changement structurel important n'est applique sans confirmation finale explicite
- un agent peut proposer, preparer, patcher, tester et documenter
- un agent ne decide pas seul d'un changement de doctrine, de style, de workflow ou de comportement produit
- le control plane doit rendre visible ce qui attend confirmation, ce qui est confirme et ce qui a ete refuse

Types d'actions qui demandent validation finale:

- changement d'architecture
- changement de ton ou de style global
- changement de policy runner
- auto-amelioration du systeme
- promotion d'une nouvelle convention de code ou de docs
- suppression ou migration de donnees importantes

## Founder preference engine

Le systeme doit accumuler les petits details perso dans un registre propre, pas dans un prompt geant.

Le control plane doit donc porter:

- `Founder Preferences`
- `Project Rules`
- `Decision Log`
- `Apply Engine`

Exemples:

- `jamais de smileys`
- `humour sec autorise si utile`
- `reponse courte d'abord`
- `toujours proposer la solution avant le detail`
- `sur ce projet, tel type de doc est obligatoire`

Ce registre doit etre lisible et exploitable par:

- `OpenClaw`
- `Codex CLI`
- `Project OS`

## Cycle de vie d'une preference

```text
Conversation humaine
  -> extraction d'une preference ou d'une regle
  -> statut proposed
  -> confirmation humaine
  -> statut confirmed
  -> activation dans chat / UI / agents
  -> historisation
  -> remplacement ou rollback si besoin
```

Statuts minimums:

- `proposed`
- `confirmed`
- `active`
- `superseded`
- `rejected`

## Auto-improvement sous garde-fous

Le systeme peut s'ameliorer, mais jamais en aveugle.

Ordre canonique:

1. detecter un probleme ou une opportunite
2. proposer une amelioration
3. preparer patch, config, doc ou PR
4. lancer tests et preuves
5. demander confirmation finale
6. appliquer
7. journaliser la decision et le resultat

Regle:

- pas d'auto-merge silencieux sur la couche critique
- pas de reecriture de la doctrine sans trace
- pas d'evolution profonde du systeme sans evidence et sans validation finale

## Autolearning decompose proprement

Le mot `autolearning` ne doit pas rester flou.

Il faut le decomposer en 4 lanes:

### 1. Memory learning

- retenir decisions
- retenir erreurs
- retenir patterns de correction
- retenir preferences projet

### 2. Policy learning

- ajuster les garde-fous
- ajuster les seuils d'approbation
- ajuster les workflows qui marchent

### 3. Execution learning

- reutiliser les playbooks qui reussissent
- preferer les strategies deja validees
- renforcer les chemins de run efficaces

### 4. Self-improvement

- proposer d'ameliorer sa propre stack
- preparer patch, PR, tests et docs
- ne jamais s'auto-reecrire en prod sans controle

## Fine-tuning - ordre retenu

Le fine-tuning n'est pas la premiere brique a poser.

Ordre canonique:

1. grounding sur les docs
2. retrieval sur repo + docs + decisions
3. memory structuree
4. evals
5. dataset d'erreurs et de reussites
6. fine-tuning seulement si les evals le justifient

Regle:

- si le systeme parait "bete", il faut d'abord verifier le contexte, pas lancer un fine-tune reflexe

## Contrat mobile et iPad

### iPhone

Role:

- supervision
- relance simple
- approbation
- lecture docs, timeline, PDF
- commandes courtes

### iPad Pro

Role:

- vraie surface de travail distante
- lecture et ecriture plus longues
- revue docs
- gestion taches
- pilotage runs
- terminal fallback avec clavier/souris

Regle:

- la maison mere doit etre pensée desktop-first mais tablet-credible
- le telephone n'est pas la surface complete, mais il reste operable

## Capacites que la web app doit concentrer

La maison mere doit, a terme, reunir:

- chat Codex
- terminal fallback
- arbre projet et fichiers lisibles
- docs type notion-like
- PDFs
- backlog / issues / tasks
- timeline
- logs de run
- approvals
- dashboard runner
- memory/search
- vues projet multi-plans
- historique des decisions

## Ce qu'il ne faut pas faire

- faire de Windows le runner principal d'agents
- faire dependre l'acces distant d'un terminal local ouvert
- donner un acces RW global du disque 8 To aux agents
- stocker la verite du projet seulement sur le PC
- traiter une VM locale comme seule maison mere

## Cible de mise en oeuvre

### Phase A - Bootstrap actuel

- PC Windows stable
- VM Linux runner locale
- PWA privee deja exploitable
- control plane encore trop proche du poste

### Phase B - Cible immediate propre

- control plane toujours on, separe du poste
- runner distant minimal toujours on
- runner local Linux sur le PC pour la puissance
- home relay pour wake/restart/reprise locale
- `GitHub` comme verite code
- DB + object storage centraux
- terminal fallback integre

### Phase C - Cible mature

- runner distant minimal + runner local + home relay robuste
- voice layer
- workspaces plus jetables
- approvals plus fines
- meilleure indexation docs/PDF

## Phrase de reference

`Project OS = maison mere distante toujours on ; runner distant minimal = continuite utile ; home relay = reprise locale ; runner Linux local = puissance isolee ; Windows = atelier humain protege ; GitHub + DB + object storage = verite durable du projet.`

## References

- `docs/architecture/PROJECT_OS_ARCHITECTURE_DECISION_MATRIX.md`
- `docs/roadmap/PROJECT_OS_AUTOPILOT_ROADMAP.md`
- `README.md`
- `PROJECT_OS_MASTER_MACHINE.md`
- `docs/architecture/FOUNDER_SURFACE_MODEL.md`
- `docs/architecture/HOST_WINDOWS_VM_LINUX_MATRIX.md`
- `docs/architecture/MEMORY_STORAGE_AND_OPS_BLUEPRINT.md`
- `docs/roadmap/PROJECT_OS_PWA_VM_V0_1_PLAN.md`
