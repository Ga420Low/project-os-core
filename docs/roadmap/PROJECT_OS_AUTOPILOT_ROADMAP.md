# Project OS Autopilot Roadmap

## Statut

ACTIVE - Canonical roadmap after the architecture decision matrix

## But

Transformer `Project OS` d'une surface encore trop dependante du poste en une maison
mere presque autopilotee:

- utile quand le PC est eteint
- plus puissante quand le PC est allume
- reprenable quand la partie locale casse
- toujours gouvernee par validation finale humaine

## Mantra

- centraliser la verite
- isoler le risque
- rendre chaque action rejouable
- garder Windows ennuyeux et stable
- ne jamais confondre prototype qui marche et systeme tenable

## Topologie cible retenue

Le systeme vise maintenant explicitement:

1. `control plane distant always-on`
2. `runner distant minimal always-on`
3. `runner local Linux sur le PC`
4. `home relay always-on`

## Override d'implementation V1

La topologie ci-dessus reste la cible logique.

Mais la `V1` canonique n'est pas encore un split physique distant.

La `V1` retenue est:

1. `un noeud distant unique OVH`
2. `control plane + runner distant minimal` sur ce meme noeud
3. `home relay`
4. `runner local Linux`

La `V2` robuste reportee plus tard:

1. separera `control plane` et `runner distant`
2. sortira les artefacts vivants vers un stockage externe

## Ce qui doit marcher PC eteint

Quand le PC est eteint ou indisponible, `Project OS` doit garder:

- la web app
- le login
- les docs, PDF, notes et historique
- les tasks, issues internes, preferences et decisions
- le chat utile sur runner distant minimal
- le terminal fallback
- la timeline des runs
- l'etat degrade du runner local

## Ce qui est seulement booste quand le PC est allume

Quand le PC est allume, `Project OS` gagne:

- jobs lourds
- build/test plus rapides
- acces controle au disque `8 To`
- workspaces plus volumineux
- futures lanes GPU ou media plus lourdes

## Ce que le home relay fait

Le `home relay` ne doit pas etre une mini maison mere.

Il doit seulement:

- verifier si le PC repond
- envoyer un wake-on-lan si besoin
- relancer le runner local
- relancer la VM locale
- relancer les services locaux critiques
- remonter un statut local simple au control plane

Il ne doit pas:

- porter la verite du projet
- remplacer le control plane
- remplacer le runner distant minimal

## Phases

### Phase 0 - Verrouillage des contrats

Objectif:

- fermer les interfaces avant le gros code

A verrouiller:

1. `control plane contract`
2. `remote runner contract`
3. `local runner contract`
4. `home relay contract`
5. `canonical data model`
6. `git workflow agentique`
7. `fallback + incident recovery contract`

Reference racine pour la donnee canonique:

- `docs/architecture/PROJECT_OS_CANONICAL_DATA_MODEL_CONTRACT.md`

Definition of done:

- chaque contrat a ses inputs, outputs, droits, limites et failure modes
- `OpenClaw` et `Codex CLI` consomment et emettent via les contrats `Project OS`, pas via des schemas paralleles

### Phase 1 - Core Node distant always-on

Objectif:

- sortir la maison mere du PC dans une V1 budget

Build:

- PWA
- API
- auth
- Postgres
- Redis
- runner distant minimal
- Cloudflare Tunnel
- Tailscale admin
- terminal fallback

Definition of done:

- la maison mere reste consultable et utile meme si le PC est eteint

### Phase 2 - Home Relay / Wake-Recovery

Objectif:

- recuperer la puissance locale sans faire du PC la maison mere

Build:

- Tailscale
- wake-on-lan
- healthcheck du PC
- healthcheck VM locale
- relance services locaux
- remontee d'etat dans la maison mere

Definition of done:

- depuis la web app, l'operateur voit si le PC est joignable, endormi, reveille, ou casse
- une reprise locale simple est possible sans shell manuel opaque

### Phase 3 - Runner local Linux securise

Objectif:

- exploiter le PC sans exposer Windows

Build:

- VM Linux locale
- `OpenClaw`
- `Codex CLI`
- workspaces jetables
- mount policy du `8 To`
- upload artefacts vers le control plane
- kill switch runner

Definition of done:

- les jobs lourds peuvent partir en local sans jamais executer directement sur Windows

### Phase 4 - Routing intelligent des runs

Objectif:

- choisir automatiquement le bon moteur d'execution

Routing retenu:

- urgent / leger / standard -> runner distant minimal
- lourd / data-local / build massif -> runner local
- runner local indisponible -> fallback distant si possible
- action impossible sans local -> statut degrade clair + option de reprise

Definition of done:

- l'operateur ne choisit pas a la main la machine dans 80% des cas
- le systeme explique pourquoi un run part ici ou la

### Phase 5 - Maison mere complete V1

Objectif:

- faire de la web app le vrai centre unique dans le cadre V1

Build:

- chat
- docs notion-like
- PDF explorer
- timeline
- issues internes
- run inspector
- approvals
- decision log
- founder preference registry
- recherche transversale

Definition of done:

- l'operateur n'a plus besoin d'aller fouiller des shells ou JSON pour suivre le projet

### Phase 6 - V2 robuste suspendue

Objectif:

- separer le noeud V1 en topologie distante plus robuste

Build:

- split `control plane`
- split `runner distant`
- stockage externe
- restore drills renforces

Definition of done:

- le split ne force pas de refonte du produit
- les contrats restent stables
