# Discord Founder Surface Repair V2 Plan

## Statut

Feuille de route canonique proposee.

Ce document relance le chantier de correction du bot visible sur `Discord`.
Il ne remplace pas:

- `docs/roadmap/DISCORD_FACADE_AND_CONTINUITY_PATCH_PLAN.md`
- `docs/roadmap/PROJECT_OS_DESKTOP_CONTROL_ROOM_V1_PLAN.md`
- `docs/architecture/FOUNDER_SURFACE_MODEL.md`
- `docs/integrations/DISCORD_OPERATING_MODEL.md`

Il les recadre autour d'une doctrine plus nette:

- un seul agent visible
- plusieurs surfaces
- `Discord` comme surface conversationnelle distante
- `Project OS.exe` comme control plane local

## Pourquoi cette roadmap v2 existe

Les correctifs precedents ont ameliore des zones utiles, mais le symptome reel reste visible:

- le bot laisse encore fuiter de l'etat runtime interne dans une conversation normale
- le moteur de clarification boucle encore sur des references pourtant resolubles
- la continuite reste trop dependante du thread Discord, pas assez du fil de travail fondateur

Le probleme n'est pas `Deep Research`.
Le probleme n'est pas le systeme de modes voulu.
Le probleme n'est pas non plus un manque de "magie OpenClaw".

Le probleme est surtout dans notre surcouche founder-facing:

- `src/project_os_core/gateway/context_builder.py`
- `src/project_os_core/gateway/service.py`
- `src/project_os_core/gateway/stateful.py`
- `src/project_os_core/api_runs/service.py`

## Ce que la recherche externe a confirme

### OpenClaw officiel

La doc officielle d'`OpenClaw` confirme quatre principes utiles:

1. le `Gateway` est la source de verite pour sessions, routing et channels
2. le chat normal doit rester mince
3. les controles operationnels vivent dans des surfaces explicites
4. le housekeeping peut et doit rester silencieux

En clair:

- backlog
- pending counts
- queue interne
- routing detaille
- provider detaille

ne doivent pas sortir spontanement dans une reponse normale.

### Forks OpenClaw

Les forks publics regardes confirment la meme direction:

- `jiulingyun/openclaw-cn`
- `DenchHQ/DenchClaw`
- `QVerisAI/QVerisBot`
- `itc-ou-shigou/winclaw`

Ils changent surtout:

- la distribution produit
- l'onboarding
- les canaux
- les sessions UI
- les commandes explicites
- les hooks memoire

Ils ne montrent pas un pattern ou un "bot plus malin" viendrait du fait de pousser backlog, queue ou plumbing dans le chat normal.

Conclusion:

- la reponse n'est pas dans un fork miracle
- le bon pattern est `chat thin + control surfaces explicites + session continuity`
- la correction est principalement chez nous

## Doctrine produit v2

### Regle centrale

`Project OS` est un seul agent visible cote fondateur.

Il possede plusieurs surfaces:

- `Discord` = surface conversationnelle distante
- `Project OS.exe` = surface locale de pilotage et de verite operationnelle
- runtime local = verite machine

### Ce que cela implique

- `Discord` n'est pas un dashboard repo/runtime par defaut
- `Discord` ne remplace pas `Codex CLI`
- `Discord` ne doit pas improviser de statut systeme non demande
- `Project OS.exe` porte la queue, la health, les runs, les approvals techniques et les traces
- le fondateur parle au meme agent sur plusieurs surfaces
- les sous-agents restent invisibles par defaut et n'apparaissent que sur demande explicite

## Invariants non negociables

- `single visible agent identity`
- `runtime truth`
- `artifact evidence`
- `no-loss delivery`
- `deep research isolation`
- `no control-plane leakage in normal Discord chat`
- `explicit cost disclosure when product requires it`
- `cross-surface consistency of visible state`

Si un lot fragilise un de ces invariants, il doit etre coupe ou recadre.

## Ce que cette roadmap ne doit pas changer

- la pipeline `Deep Research`
- le mode `deep research` / `recherche approfondie`
- le systeme de modes existant
- les niveaux `simple / avance / extreme`
- les confirmations de changement de modele
- les confirmations de passage vers une autre IA ou un autre mode
- l'affichage volontaire des prix
- le fallback `artifact_summary / PDF`
- `database.py`
- `models.py`

## Trois problemes racines a traiter

### 1. Control plane leakage dans le chat

Aujourd'hui, l'etat interne fuit trop facilement dans la conversation normale:

- `active_missions`
- `pending_*`
- queue
- backlog
- provider / route_reason

Ce bruit ne devrait exister que dans:

- le control plane local
- une commande explicite
- une demande de statut claire

### 2. Clarification engine sous-ancre

Le moteur de clarification traite encore des references explicites comme ambiguës.

Il ne sait pas assez bien privilegier:

- le dernier objet cite explicitement
- la derniere option proposee par l'agent
- le dernier sujet actif du thread

### 3. Continuite trop thread-centric

La continuite actuelle est meilleure qu'avant, mais elle reste encore trop:

- centree sur le thread brut
- dependante du dernier message
- fragile entre surfaces

La cible doit devenir:

- une colonne vertebrale de session fondateur
- partageable entre `Discord` et `Project OS.exe`
- sans sync totale du chat en v1

## Matrice de surfaces cible

### Discord

Doit porter:

- conversation
- arbitrage
- relance
- clarification utile
- decision courte
- statut synthetique sur demande
- preuve ou lien utile si necessaire

Ne doit pas porter par defaut:

- queue brute
- backlog brut
- pending deliveries internes
- traces adapter
- route_reason
- provider detaille
- plumbing runtime

### Project OS.exe

Doit porter:

- queue
- backlog
- runs actifs
- approvals techniques
- gateway health
- traces
- retries
- details de delivery
- vues repo/runtime

## Roadmap en packs

### Pack A - Shared Surface Contracts

Objectif:

- figer la doctrine `single agent / multi-surface`

Ce qui doit sortir:

- matrice `Discord vs Desktop`
- regle de disclosure
- regle `subagents on demand`
- regle `control-plane data stays out of normal chat`

Docs a aligner:

- `docs/architecture/FOUNDER_SURFACE_MODEL.md`
- `docs/integrations/DISCORD_OPERATING_MODEL.md`
- `docs/architecture/RUN_COMMUNICATION_POLICY.md`

### Pack B - Discord Chat Detox

Objectif:

- retirer la fuite de plomberie des reponses normales

Cible code:

- `src/project_os_core/gateway/context_builder.py`
- `src/project_os_core/gateway/service.py`
- `src/project_os_core/api_runs/service.py`

Criteres:

- un `wesh` ne doit jamais sortir backlog/queue/runs internes
- un message normal ne doit pas montrer provider, route_reason, state internals sauf demande explicite

### Pack C - Clarification And Referent Anchoring

Objectif:

- corriger les clarifications stupides et les boucles

Cible code:

- `src/project_os_core/gateway/stateful.py`
- `src/project_os_core/gateway/service.py`

Regles:

- `last explicit referent wins`
- `last offered option wins`
- `low recall confidence -> clarify`
- `never fabricate continuity`

Criteres:

- si le fondateur reprend explicitement une option de la reponse precedente, le bot n'ouvre pas une clarification vide
- une clarification ne peut pas se repeter a l'identique plus d'un tour si le referent est deja explicite

### Pack D - Founder Session Spine

Objectif:

- definir la continuite cross-surface sans sync totale du chat

Ce qui doit exister:

- session fondateur canonique
- sujet actif
- decisions recentes
- prochain pas proche
- dernier artefact utile
- dernier approval utile

Docs a aligner:

- `docs/architecture/HANDOFF_MEMORY_POLICY.md`
- `docs/architecture/FOUNDER_SURFACE_MODEL.md`

Etat:

- implemente cote runtime Discord
- spine minimal injecte dans le contexte:
  - `founder_session_key`
  - `active_subject`
  - `recent_decisions`
  - `next_step`
  - `last_useful_artifact`
  - `last_useful_approval`
- gate `status request` durci:
  - plus de simple match mot-cle
  - synthese Discord par defaut
  - detail control plane reserve a `Project OS.exe`

### Pack E - Desktop Control Plane Handshake

Objectif:

- faire du desktop la surface canonique des disclosures operationnelles

Ce qui doit changer:

- Discord repond de maniere synthetique
- Desktop expose le detail
- les handoffs entre surfaces deviennent explicites

Docs a aligner:

- `docs/roadmap/PROJECT_OS_DESKTOP_CONTROL_ROOM_V1_PLAN.md`
- `docs/architecture/RUN_COMMUNICATION_POLICY.md`

Etat:

- implemente cote runtime Discord
- une `status request` explicite peut produire:
  - une synthese courte dans Discord
  - un handoff explicite vers `Project OS.exe`
- les vues desktop recommandees sont maintenant porteuses du handshake:
  - `Home`
  - `Session`
  - `Runs`
  - `Discord`
  - `Costs`
- `Discord` ne detaille plus a lui seul le control plane quand un handoff explicite est plus approprie

### Pack F - Cross-Surface Evals

Objectif:

- arreter de valider uniquement du texte brut et couvrir les vraies transitions de surface

Cas minimaux:

- bonjour Discord sans fuite de backlog
- question repo depuis Discord apres une reponse precedente
- reprise explicite d'une option sans clarification en boucle
- demande de statut synthetique sur Discord
- detail runtime visible dans l'app, pas dans le chat normal
- continuites visibles coherentes entre `Discord` et `Project OS.exe`

Etat reel:

- implemente
- harness canonique etendu avec une couche `cross-surface`
- commandes de verification:
  - `python scripts/discord_facade_smoke.py --layer cross-surface`
  - `python scripts/project_os_tests.py --suite discord-cross-surface-live`
- cas verrouilles:
  - `cross_surface_discord_status_handoff_contract`
  - `cross_surface_desktop_status_stays_local`
  - `cross_surface_founder_session_key_stays_consistent`
- check manuel ajoute:
  - reprise `Discord -> Project OS.exe`
  - reprise `Project OS.exe -> Discord`

## Ordre recommande

1. `Pack A - Shared Surface Contracts`
2. `Pack B - Discord Chat Detox`
3. `Pack C - Clarification And Referent Anchoring`
4. `Pack D - Founder Session Spine`
5. `Pack E - Desktop Control Plane Handshake`
6. `Pack F - Cross-Surface Evals`

## Decisions produit non negociables

1. `Discord` reste une surface conversationnelle distante, pas un dashboard runtime/repo.
2. `Project OS.exe` devient la surface canonique des disclosures operationnelles detaillees.
3. `Project OS` reste un seul agent visible, quel que soit le provider, la lane ou la surface.
4. `Deep Research`, les modes existants et les confirmations volontaires restent hors perimetre de ce patch.
5. La continuite cible est `founder-session centric`, pas seulement `thread centric`.

## Etat actuel de la roadmap

- `Pack A` est deja largement pose en doctrine et documentation.
- `Pack B` est implemente.
- `Pack C` est implemente.
- `Pack D` est implemente cote runtime Discord.
- `Pack E` est implemente cote runtime Discord.
- `Pack F` est implemente pour verrouiller les evals cross-surface.

## Matrice executable des packs

| Pack | Objectif precis | Ce qui doit changer | Ce qui ne doit pas changer | Criteres d'acceptation | Dependances | Risques principaux |
|---|---|---|---|---|---|---|
| `Pack A - Shared Surface Contracts` | Figer la doctrine `Discord chat plane / desktop control plane` | docs de surfaces, disclosure policy, matrice de verite, invariants | `Deep Research`, modes, confirmations volontaires, logique runtime | plus aucune ambiguite documentaire sur le role de `Discord` vs `Project OS.exe` | aucune | doctrine encore trop floue ou contradictoire |
| `Pack B - Discord Chat Detox` | Retirer la plomberie du chat normal | prompt visible, contexte injecte, disclosures de statut, sorties inline standard | `Deep Research`, costs volontaires, switches modele, fallback PDF | un salut ou une question normale ne surfacent plus queue/backlog/provider/routing | `Pack A` | masquer trop, ou casser un vrai cas de statut explicite |
| `Pack C - Clarification And Referent Anchoring` | Arreter les clarifications stupides et les boucles | heuristiques de referent, priorite au dernier objet explicite, dernier choix propose, sujet actif | garde-fou `low confidence -> clarify`, anti-hallucination memoire | une reprise explicite de l'option precedente ne repart pas en `Tu parles de quoi ?` | `Pack B` pour la surface, sinon `Pack A` minimum | sur-ancrage faux positif, ou continuites inventees |
| `Pack D - Founder Session Spine` | Donner une vraie colonne vertebrale de session visible entre surfaces | sujet actif, decisions recentes, prochain pas, artefact utile, approval utile | pas de sync totale du chat, pas de seconde personnalite, pas de memoire sociale invasive | Discord et desktop restent coherents sur l'etat visible du travail en cours | `Pack B`, `Pack C` | dette memoire, contradiction entre surfaces |
| `Pack E - Desktop Control Plane Handshake` | Faire du desktop la destination naturelle du detail operationnel | handoffs explicites, detail de queue/runs/health dans l'app, resume synthese dans Discord | `Discord` ne devient pas cockpit runtime, pas de forking de verite | une demande de detail systeme peut etre satisfaite sans polluer le chat normal | `Pack D` + progression app desktop | friction entre surfaces, mauvais partage de responsabilite |
| `Pack F - Cross-Surface Evals` | Verrouiller les regressions reelles | suites de tests Discord, desktop, et transitions entre surfaces | pas de CI monstre, pas de suite trop fragile | les cas critiques founder-facing sont rejouables regulierement | tous les packs precedents ou au moins `B/C` | evals trop faibles ou trop cheres a maintenir |

## Ce que chaque pack doit produire concretement

### Pack A

- une matrice canonique `ce qu'on montre / ce qu'on cache / ce qu'on montre sur demande`
- une matrice `surface -> type d'information`
- une regle explicite `subagents on demand only`

### Pack B

- suppression de la fuite `active_missions`, `pending_*`, `queue`, `route_reason`, `provider`
- `minimal context` pour salutations, phatique et messages courts non techniques
- distinction nette entre `question normale` et `status request`

### Pack C

- priorite au dernier referent explicite
- priorite a la derniere option proposee par l'agent
- anti-boucle de clarification
- clarification seulement si la reference reste reellement non resoluble

### Pack D

- un objet de session fondateur minimal partageable
- `active_subject`
- `recent_decisions`
- `next_step`
- `last_useful_artifact`

### Pack E

- phrases de handoff explicites du type:
  - `je peux te donner la synthese ici`
  - `le detail operatoire est cote app`
- une frontiere claire entre `synthese Discord` et `detail control plane`

### Pack F

- replays de prompts reels founder-facing
- cas Discord seuls
- cas desktop seuls
- cas Discord -> desktop
- cas desktop -> Discord
- suite canonique `discord-cross-surface-live`
- couche `cross-surface` integree au harness `discord_facade_smoke`
- verrouillage de deux invariants structurels:
  - `Discord` peut handoff vers `Project OS.exe`
  - `Project OS.exe` ne se handoff jamais a lui-meme

## Premier work order recommande

### Nom

`Pack B - Discord Chat Detox`

### Pourquoi commencer ici

- c'est le plus gros levier visible immediat
- c'est exactement le probleme mis en evidence par tes transcripts reels
- c'est coherent avec la doctrine `OpenClaw chat thin`
- c'est faisable sans toucher `Deep Research`, les modes ni les structures les plus risquées

### Scope exact

- `src/project_os_core/gateway/context_builder.py`
- `src/project_os_core/gateway/service.py`
- `src/project_os_core/api_runs/service.py`

### Symptomes a supprimer

- `Salut. Je vois que tu as 151 missions en queue...`
- mention spontanee de backlog / queue / pending internal state
- provider / route_reason dans une reponse normale
- confusion entre `status request` explicite et simple conversation

### Criteres d'acceptation minimaux

- `wesh` -> jamais de queue ou backlog
- `ou est ce que je peut reparer ca dans le repo ?` -> pointe vers une zone repo probable ou demande une clarification utile tres courte, sans replonger dans la plomberie
- une vraie demande de statut explicite peut encore obtenir une synthese
- aucun impact sur `Deep Research`, modes, prix volontaires, switches modele

## Pack suivant obligatoire

Le pack qui suit immediatement `Pack B` doit etre:

- `Pack C - Clarification And Referent Anchoring`

Raison:

- sans lui, le bot restera encore cassant sur les follow-ups courts
- la frustration visible viendra alors moins de la plomberie que de la betise conversationnelle

## Tests manuels cibles de la roadmap v2

### Discord only

- `wesh`
- `salut`
- `ou est ce que je peut reparer ca dans le repo ?`
- `Les 152 missions en queue qui s'accumulent ?`
- `oui`
- `et du coup ?`

### Status explicite

- `donne-moi un statut synthétique`
- `combien de missions sont en attente ?`
- `quel modele tu utilises pour ce tour ?`

### Protections produit

- `deep research`
- `recherche approfondie`
- `passe sur opus`
- `change de modele`

### Cross-surface plus tard

- commencer sur Discord, reprendre sur desktop
- commencer sur desktop, demander une synthese sur Discord

## Rollback triggers

Revert ou recadrage immediat si:

- `Discord` devient trop opaque pour les vrais cas de statut
- un changement de modele ne demande plus confirmation
- `Deep Research` est accidentellement nettoye
- une correction de clarification invente une continuite fausse
- deux surfaces montrent des etats visibles contradictoires

## Ce qu'il faut penser differemment des maintenant

- ne plus penser `bot Discord`
- penser `agent unique multi-surface`
- ne plus penser `Discord peut aussi faire cockpit runtime`
- penser `Discord = remote operator surface`
- ne plus penser `le thread seul suffit comme memoire`
- penser `session fondateur + thread + control plane`
- ne plus penser `les sous-agents peuvent emerger naturellement`
- penser `sous-agents invisibles sauf demande explicite du maitre`

## Phrase directrice

`Project OS` est un seul agent visible cote fondateur. `Discord` est sa surface conversationnelle distante. `Project OS.exe` est sa surface locale de pilotage et de verite operationnelle. L'etat systeme appartient au control plane, pas au chat normal.
