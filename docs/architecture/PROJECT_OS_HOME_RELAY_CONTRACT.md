# Project OS Home Relay Contract

## Statut

ACTIVE - Pack 0 locked contract

## But

Definir le contrat du `home relay` comme brique de reprise locale borne, sans en faire
une seconde maison mere.

## Role canonique

Le `home relay` est une petite machine locale always-on.

Il sert uniquement a:

- verifier si le PC repond
- envoyer un `wake-on-lan`
- relancer la `VM` locale
- relancer certains services locaux bornes
- remonter un statut simple au `control plane`

## Ce qu'il n'est pas

Le `home relay` n'est pas:

- un `control plane`
- un `runner`
- une base de donnees
- une interface chat primaire
- une source de verite projet

## Inputs obligatoires

Le `home relay` recoit:

1. demandes de statut
2. demande `wake`
3. demande `restart vm`
4. demande `restart local service`

Toutes ces commandes doivent venir du `control plane` ou d'une voie d'urgence admin
authentifiee.

## Outputs obligatoires

Le `home relay` doit produire:

1. `RuntimeState` ou statut equivalent pour:
   - `pc_power`
   - `pc_reachability`
   - `local_vm`
   - `local_services`
2. `ActionEvidence` pour:
   - `wake`
   - `restart`
   - `status probe`

## Droits autorises

Le `home relay` a le droit de:

- pinger le PC
- envoyer un paquet `wake-on-lan`
- lancer une relance de `VM`
- lancer une relance de service borne

## Interdits

Le `home relay` ne doit pas:

- heberger `Project OS` comme maison mere
- lancer des runs metier
- posseder la DB canonique
- monter le `8 To`
- parler directement a `GitHub` pour muter le code
- devenir un mini shell admin non borne

## Surface de commande autorisee

Commandes canoniques:

- `status`
- `wake_pc`
- `restart_local_vm`
- `restart_local_runner_service`

Tout le reste est hors contrat tant qu'une decision explicite ne l'ajoute pas.

## Failure modes

### Relay offline

Effet:

- plus de reprise locale automatisable

Reaction:

- `control plane` reste vivant
- statut `relay unavailable`

### Wake rate

Effet:

- le PC ne revient pas

Reaction:

- etat visible
- pas de retries infinis opaques

### VM restart rate

Effet:

- lane locale toujours indisponible

Reaction:

- incident trace
- reroutage distant si possible

## Acceptance checks

Le contrat sera considere respecte quand:

1. le `home relay` sait dire `awake / asleep / unreachable`
2. un `wake-on-lan` borne fonctionne
3. une relance de `VM` borne fonctionne
4. le relay n'heberge aucun role de verite projet
5. si le relay tombe, la maison mere distante reste utilisable

## References

- `docs/architecture/PROJECT_OS_MOTHER_CONTROL_PLANE_ARCHITECTURE.md`
- `docs/architecture/PROJECT_OS_ARCHITECTURE_DECISION_MATRIX.md`
- `docs/roadmap/PROJECT_OS_AUTOPILOT_ROADMAP.md`

