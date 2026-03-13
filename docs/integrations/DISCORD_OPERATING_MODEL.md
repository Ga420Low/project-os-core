# Discord Operating Model

`Discord` est la surface humaine prioritaire de `Project OS`.

Le but n'est pas de faire un simple bot de chat.
Le but est de faire une interface operateur haut niveau.

## Roles de Discord

`Discord` sert a:

- discuter
- donner une direction
- demander un statut
- lancer ou reprendre une mission
- demander une preuve
- poser un doute
- arbitrer un risque
- envoyer des vocaux transcrits plus tard

Topologie cible:

- `#pilotage`
- `#runs-live`
- `#approvals`
- `#incidents`
- threads par mission

## Ce que Discord n'est pas

`Discord` n'est pas:

- la memoire canonique
- la verite machine
- l'endroit ou les workers decident eux-memes
- un contournement du `Mission Router`

## Types de messages

Chaque message recu doit etre classe dans l'une de ces familles:

- `chat`
- `status_request`
- `tasking`
- `idea`
- `decision`
- `note`
- `approval`
- `artifact_ref`

## Policy selective sync

La memoire Discord suit une policy `selective_sync`.

Donc:

- tout passe dans le journal operateur
- tout ne passe pas dans la memoire durable

Promotions typiques:

- preference stable
- decision explicite
- mission importante
- incident reel
- retour utile du fondateur

## Routing modele recommande

Le meme agent doit rester coherent, mais le cout cognitif doit s'adapter.

### Cas banal Discord

Exemples:

- salut
- check rapide
- petite question de statut
- accusé de reception
- mini reformulation

Route recommandee:

- classification locale ou deterministic first
- si LLM necessaire: `gpt-5.4` avec `reasoning.effort=medium`

### Cas operateur standard

Exemples:

- clarification utile
- mini plan
- decision simple
- retour de mission

Route recommandee:

- `gpt-5.4` avec `reasoning.effort=high`

### Cas complexe / critique

Exemples:

- arbitrage architecture
- incident ambigue
- reprise apres echec
- mission a fort cout d'erreur

Route recommandee:

- `gpt-5.4` avec `reasoning.effort=xhigh`

### Cas exceptionnel

Exemples:

- arbitrage majeur
- run d'urgence multi-systeme
- demande explicitement marquee exceptionnelle

Route:

- `gpt-5.4-pro`
- jamais par defaut
- approval fondateur obligatoire

## Pourquoi ce choix

Le but est:

- garder la meme identite agent
- economiser le budget
- ne pas surpayer les banalites
- reserver le raisonnement maximal aux moments qui le meritent

## Voix

Le mode voix est `future_ready`.

V1:

- on passe par transcription texte
- la transcription entre ensuite dans le meme pipeline que Discord texte

Regle:

- pas de deuxieme cerveau voix
- pas de memoire speciale voix
- la transcription est juste une autre entree operateur

## Politique de parole

Pendant un gros run de code:

- pas de conversation naturelle sur Discord
- le suivi se fait via `#runs-live`
- seules les cartes compactes, blocages reels et rapports finaux sont autorises

Dans `#pilotage`:

- l'agent reste souple
- mais toujours en francais clair et non technique si ce n'est pas necessaire
