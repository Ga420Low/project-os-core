# Handoff Memory Policy

Ce document fixe comment l'information circule proprement entre:

- humain
- `Discord`
- supervision locale
- gros runs API
- runtime `Project OS`

Le but est d'eviter:

- les oublis
- les contradictions
- les doubles verites
- la pollution de la memoire

## Regle principale

Tout n'entre pas en memoire durable.

Le systeme applique:

- trace de tout ce qui compte operationnellement
- promotion selective vers la memoire canonique

## Niveaux d'information

### Evenement brut

Exemples:

- message Discord
- retour d'un run API
- note temporaire
- artefact ponctuel

Sort:

- journal runtime
- pas de promotion automatique

### Signal de travail

Exemples:

- demande d'audit
- nouvelle priorite
- doute produit
- contrainte temporaire

Sort:

- utilisable pour le lot courant
- promotion seulement si valide au-dela du moment

### Decision durable

Exemples:

- choix d'architecture
- policy modele
- choix memoire
- choix Git workflow
- choix Discord workflow

Sort:

- `DECISION CONFIRMED`
- `DECISION CHANGED`
- promotion obligatoire dans la memoire canonique

### Apprentissage durable

Exemples:

- erreur recurrente
- boucle detectee
- strategie qui marche
- angle mort du fondateur
- element de standing qualite a garder

Sort:

- signal `learning`
- promotion recommandee

## Handoffs obligatoires

### Discord -> Runtime

Chaque message utile devient:

- `OperatorEnvelope`
- classification
- event log

Puis:

- soit simple trace
- soit candidat memoire
- soit `MissionIntent`

### Claude API -> Runtime

Quand Claude API (l'auditeur) confirme un choix important apres review:

- ecrire la doc
- ecrire ou mettre a jour l'ADR si necessaire
- emettre un signal `DECISION CONFIRMED` ou `DECISION CHANGED`
- pousser cela dans la memoire durable

### Supervision locale -> Runtime (optionnel)

Si le fondateur utilise une surface locale directe et qu'un choix important emerge:

- suivre les memes regles que ci-dessus
- la supervision locale n'est pas une voie autonome du pipeline (ADR 0013)

### API Run -> Runtime

Le run produit:

- contexte
- prompt
- brut
- structure
- review

Puis:

- rien n'est memoire durable par defaut
- seules les sorties relues et promues entrent dans la memoire canonique

### Discord meeting -> Runtime

Une reunion multi-angles visible dans `Discord` doit etre recopiee en contrat machine dans le runtime.

Objets canoniques documentaires:

- `MeetingIntent`
- `MeetingBrief`
- `AngleResponse`
- `ContradictionReply`
- `MeetingSynthesis`
- `DecisionRecord`

Regles:

- le runtime garde toujours le transcript machine complet du thread
- `Discord` reste une projection humaine, pas la verite canonique
- l'implementation runtime detaillee peut venir plus tard, mais le contrat documentaire est deja fixe

## Promotions automatiques souhaitables

Le systeme doit penser a promouvoir regulierement:

- `DECISION CONFIRMED`
- `DECISION CHANGED`
- `PATCH_ACCEPTED`
- `PATCH_REJECTED`
- `LOOP_DETECTED`
- `REFRESH_NEEDED`
- preference stable explicite du fondateur
- `MeetingSynthesis` durable
- `DecisionRecord`

Le fondateur ne doit pas avoir besoin de le demander a chaque fois.

## Rejet de promotion

Ne pas promouvoir automatiquement:

- bavardage
- hesitation sans consequence
- doublons
- idees non validees
- bruit de debug
- frustrations temporaires sans impact structurel
- transcript complet d'un thread de reunion
- details exploratoires de contradiction

## Refresh

Si le systeme observe:

- baisse de qualite
- boucle
- contradiction de canal
- repetition d'erreur
- oubli de decision deja validee

alors il doit:

- remonter un `RefreshRecommendation`
- relire memoire + docs de reference
- reprendre le flux avec contexte rafraichi

## Budget de continuite projet en conversation standard

La conversation standard peut lire une continuite projet durable, mais seulement avec un budget borne.

Regles du budget de lecture:

- vue `clean` par defaut
- `full` seulement sur opt-in explicite
- fenetre recente bornee a `5 jours` pour les rappels conversationnels
- recap borne a quelques items seulement:
  - decisions durables recentes
  - thoughts utiles
  - prochains jalons differes
  - runs recents relies au contexte

Regles du budget de rappel:

- si le rappel est faible ou ambigu, clarification courte
- ne jamais fabriquer une continuite
- ne jamais transformer un signal prive en rappel visible par defaut
- ne jamais utiliser la memoire longue pour casser les confirmations produit voulues

## Cible

Le handoff ideal doit produire:

- zero decision critique perdue
- zero memoire polluee par du bruit
- zero double verite entre supervision locale, `Discord` et l'API
