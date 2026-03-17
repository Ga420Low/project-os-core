# Founder Surface Model

Ce document fige la doctrine de surfaces humaines de `Project OS`.

Il ne remplace pas:

- `docs/integrations/DISCORD_OPERATING_MODEL.md`
- `docs/architecture/RUN_COMMUNICATION_POLICY.md`
- `docs/roadmap/PROJECT_OS_DESKTOP_CONTROL_ROOM_V1_PLAN.md`
- `docs/roadmap/DISCORD_FOUNDER_SURFACE_REPAIR_V2_PLAN.md`

Il sert a repondre clairement a une seule question:

- `quelle surface sert a quoi pour le fondateur ?`

## Regle centrale

`Project OS` doit etre pense comme:

- `un seul agent visible cote fondateur`
- `plusieurs surfaces`

Phrase directrice:

- `Project OS is a single founder-facing agent with multiple surfaces. Discord is the remote conversation surface. The desktop app is the operational control surface. System state belongs to the control plane, not to normal conversation.`

Le futur coeur pilotable local du projet est:

- `Project OS.exe`

`Discord` reste:

- la surface conversationnelle distante
- une surface de remote work
- une surface d'arbitrage
- une surface mobile/importante

Le runtime local reste:

- la verite machine
- la source canonique des preuves et etats

## Invariants non negociables

- `single visible agent identity`
- `multi-surface model`
- `Discord = remote conversation plane`
- `Project OS.exe = control plane`
- `runtime local = runtime truth`
- `subagents are backend-only unless explicitly requested`
- `no dual personality between surfaces`
- `control-plane data stays out of normal chat unless explicitly requested or truly actionnable`

## Hierarchie des surfaces

### 1. `Project OS.exe`

Role:

- surface locale fondatrice
- control plane Windows-first
- terminal maitre `Codex`
- reprise du contexte local
- supervision locale lisible
- etat systeme, queue, sante, approvals techniques, traces

Ce que cette surface doit devenir:

- l'entree visible principale du projet cote bureau
- le point d'acces naturel du fondateur sur son PC

### 2. `Discord`

Role:

- discussion naturelle
- arbitrage
- travail distant
- coordination mobile et hors poste
- retours de run et clarifications
- remote conversation plane

Ce que cette surface n'est plus en doctrine cible:

- le tableau de bord systeme principal
- le control plane operateur
- l'endroit par defaut pour exposer queue, backlog, routing et provider details

### 3. Dashboard / terminal / scripts

Role:

- socle technique de supervision
- preuves visuelles et operationnelles
- composants que `Project OS.exe` doit a terme emballer proprement

## Corollaires produit

- un humain ne doit pas devoir ouvrir un JSON runtime pour suivre le systeme
- l'app locale ne remplace pas la verite machine
- `Discord` ne remplace pas l'app locale
- les sous-agents ne doivent pas apparaitre naturellement dans la surface visible
- la v1 n'impose pas de sync de conversation complete entre `Discord`, l'app locale et `Codex`
- les surfaces doivent partager une identite visible et des etats coherents avant toute conversation fusionnee

## Matrice de verite par surface

- `Queue / backlog / runs / health / approvals techniques / traces / routing / provider details` -> `Project OS.exe`
- `Conversation / decisions courtes / relances / pilotage leger / clarifications` -> `Discord`
- `Artefacts / evidence / snapshots / journal canonique / DB` -> `runtime local`

## Session fondatrice

La continuite cible n'est plus seulement:

- `thread Discord centric`

Elle doit devenir:

- `founder-session centric`
- partageable entre surface distante et surface locale
- sans produire deux etats contradictoires de l'agent

## Contrat v1

En v1:

- `Project OS.exe` est la future surface locale principale a construire
- `Discord` reste pleinement utilisable
- les deux surfaces sont reliees par une meme identite visible
- la sync visee porte d'abord:
  - etats
  - runs
  - couts
  - activites
  - blocages

Pas encore:

- une conversation partagee stricte
- une memoire de chat commune temps reel

## Phrase de reference

Quand il faut resumer la doctrine en une ligne:

- `Project OS.exe = control plane ; Discord = remote conversation plane ; runtime local = verite machine ; agent visible unique sur toutes les surfaces`
