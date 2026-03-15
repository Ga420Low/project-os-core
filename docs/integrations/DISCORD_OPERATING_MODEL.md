# Discord Operating Model

`Discord` est la surface humaine prioritaire de `Project OS`.

Le but n'est pas de faire un simple bot de chat.
Le but est de faire une interface operateur haut niveau.

Corollaire produit:

- si un humain doit lire un fichier JSON pour comprendre l'etat d'un run, le workflow est mauvais
- `Discord` doit porter la partie conversation, arbitrage et retour humain des gros runs

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
- recevoir les points de passage d'un gros run API
- recevoir les clarifications bloquantes
- recevoir le verdict final sans ouvrir le runtime

Topologie cible:

- `#pilotage`
- `#runs-live`
- `#approvals`
- `#incidents`
- threads par mission

Les deliberations multi-angles se branchent sur cette topologie existante:

- ouverture depuis `#pilotage`
- thread dedie pour la reunion
- synthese finale dans le thread
- synthese humaine finale republiquee dans `#pilotage`
- miroir dans `#approvals` si la decision est sensible
- lien vers `#runs-live` seulement si la reunion debouche sur un run

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
- accuse de reception
- mini reformulation

Route recommandee:

- classification locale ou deterministic first
- si LLM necessaire: `Claude API` pour discussion/traduction compacte
- si le message ouvre un vrai travail de fond: escalade vers `GPT API`

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

Profils de sortie Discord:

- `notification_card` pour les signaux operateur courants et les cartes `#runs-live`
- `meeting_thread` pour les deliberations structurees visibles
- `founder_synthesis` pour la synthese humaine finale dans `#pilotage`

Pendant un gros run de code:

- pas de conversation naturelle sur Discord
- le suivi se fait via `#runs-live`
- seules les cartes compactes, blocages reels et rapports finaux sont autorises

Evenements minimums attendus dans `Discord` pour un gros run API:

- `contract_proposed`
- `clarification_required`
- `run_completed`
- `run_failed`

Note:

- `run_started` n'est pas emis sur `Discord`
- il est filtre comme bruit pur (cf. ADR 0013 et `DAILY_OPERATOR_WORKFLOW`)
- les `notification_card` restent bornees a 3 lignes max
- les `meeting_thread` et `founder_synthesis` ne suivent pas cette limite, mais restent concis et lisibles

Chaque carte doit rester courte et comprehensible par un humain non developpeur.
Les artefacts runtime peuvent etre lies comme preuves, mais ne doivent pas etre la seule explication.

Dans `#pilotage`:

- l'agent reste souple
- mais toujours en francais clair et non technique si ce n'est pas necessaire

## Reunions multi-angles structurees

Quand une simple reponse ne suffit plus, `Discord` peut porter une deliberation structuree.

But:

- confronter plusieurs prismes sans theatre
- produire une synthese arbitrable
- garder la discussion lisible pour le fondateur

Regles:

- un seul bot
- identites logiques `[Vision]`, `[Tech]`, `[RedTeam]`, etc.
- `Moderator` procedurale
- threads first
- thread visible toujours
- format strict
- synthese finale obligatoire
- `Discord` ne devient jamais la memoire canonique

## OpenClaw Discord UX retenue

Le socle `OpenClaw` retenu pour `Discord` est volontairement minimal et robuste:

- `threadBindings` pour garder un fil durable entre thread et runtime
- `execApprovals` pour les approvals Discord natives a faible ambiguite
- `autoPresence` pour refleter la sante runtime

Regles:

- `threadBindings` oui
- approvals upstream en `dm`
- cards compactes dans les salons
- pas de components metier riches tant qu'ils ne sont pas prouves sans ambiguite

Le mapping canonique reste:

- `Discord` = vue operateur
- `Project OS` = verite runtime

References:

- `docs/analysis-angles/README.md`
- `docs/analysis-angles/07-meeting-types.md`
- `docs/integrations/DISCORD_MEETING_SYSTEM_V1.md`
