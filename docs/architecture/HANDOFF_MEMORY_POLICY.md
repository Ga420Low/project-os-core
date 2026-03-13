# Handoff Memory Policy

Ce document fixe comment l'information circule proprement entre:

- humain
- `Discord`
- `Codex`
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

### Codex -> Runtime

Quand `Codex` confirme un choix important:

- ecrire la doc
- ecrire ou mettre a jour l'ADR si necessaire
- emettre un signal `DECISION CONFIRMED` ou `DECISION CHANGED`
- pousser cela dans la memoire durable

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

## Promotions automatiques souhaitables

Le systeme doit penser a promouvoir regulierement:

- `DECISION CONFIRMED`
- `DECISION CHANGED`
- `PATCH_ACCEPTED`
- `PATCH_REJECTED`
- `LOOP_DETECTED`
- `REFRESH_NEEDED`
- preference stable explicite du fondateur

Le fondateur ne doit pas avoir besoin de le demander a chaque fois.

## Rejet de promotion

Ne pas promouvoir automatiquement:

- bavardage
- hesitation sans consequence
- doublons
- idees non validees
- bruit de debug
- frustrations temporaires sans impact structurel

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

## Cible

Le handoff ideal doit produire:

- zero decision critique perdue
- zero memoire polluee par du bruit
- zero double verite entre `Codex`, `Discord` et l'API
