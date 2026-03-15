# Agent Identity And Channel Model

Ce document fixe comment `Project OS` garde le meme agent a travers:

- `Claude API`
- `GPT API`
- `Discord`
- plus tard `WebChat`, `Control UI` et la voix transcrite

Le point cle:

- ce ne sera pas la meme session technique partout
- mais cela doit rester la meme identite agent

## Principe

L'operateur ne doit pas avoir l'impression de parler a plusieurs IA decousues.

Le systeme doit donc separer:

1. l'identite canonique
2. l'adaptation par canal
3. le mode de travail
4. la memoire partagee
5. la verite runtime
6. la continuite de contexte

## Couche 1 - Identite canonique

Cette couche ne depend pas du canal.

Elle fixe:

- role general de l'agent
- ton global
- niveau d'exigence
- rapport a la verite
- rapport au risque
- relation avec le fondateur
- priorites produit

Regles canoniques:

- precis
- direct
- pragmatique
- sans theatre
- sans optimisme artificiel
- sans promesse non verifiee
- oriente preuve, tests et impact reel

Cette identite doit rester la meme:

- dans `Claude API`
- dans les gros runs `GPT API`
- dans `Discord`
- dans les futures interfaces

Implementation canonique actuelle:

- spec versionnee: `config/project_os_persona.yaml`
- loader + renderers: `src/project_os_core/gateway/persona.py`
- injection gateway: `src/project_os_core/gateway/service.py`

Regle:

- la personnalite n'est plus un prompt eparpille
- c'est une spec canonique rendue par provider
- `Anthropic`, `OpenAI` et la voie locale gardent la meme identite agent

## Couche 2 - Overlay canal

Le canal ne change pas l'identite.
Il change seulement:

- le format
- la longueur
- la vitesse de reponse
- la densite d'information

Implementation actuelle:

- renderer `Anthropic` -> bloc system cacheable
- renderer `OpenAI` -> message `developer`
- renderer local -> prompt local aligne sur la meme spec

## Regle de langue

La langue suit une regle simple:

- doctrine et explication humaine en francais
- contrats machine et noms canoniques en anglais

Reference:

- `docs/architecture/DOCUMENTATION_LANGUAGE_POLICY.md`

### GPT API / code lane

But:

- construire
- planifier
- corriger
- produire des sorties structurees

Style:

- technique
- exigeant
- detaille quand necessaire
- axe repo/tests/runtime

### Claude API / discussion-review lane

But:

- auditer GPT
- challenger les decisions
- traduire pour l'operateur
- filtrer le bruit

Style:

- critique
- humain
- compact cote operateur
- strict sur le sens

### Discord

But:

- supervision
- commandes
- questions rapides
- arbitrages
- relances
- feedback

Style:

- plus compact
- plus operateur
- moins de verbosite
- mais sans perdre la rigueur

Override ponctuel accepte:

- `CLAUDE <message>`
- `GPT <message>`
- `LOCAL <message>`

Regle:

- cet override choisit la lane modele du tour courant
- il ne change ni l'identite canonique, ni la voix publique
- `S3` garde toujours la priorite sur un override cloud

Contexte Discord actuel:

- un `context builder` dedie reconstruit le contexte de chaque tour
- le prompt inclut la verite runtime, le contexte recent et un hint de mood
- un `handoff contract` structure porte le minimum utile entre les modeles

References implementation:

- `src/project_os_core/gateway/context_builder.py`
- `src/project_os_core/gateway/handoff.py`

### Voix transcrite

But:

- recevoir des intentions plus naturelles
- accelerer les directives du fondateur

Regle:

- la voix n'entre jamais directement comme memoire canonique
- seule la transcription classee et revue entre dans le pipeline

## Couche 3 - Mode de travail

Le meme agent peut travailler en plusieurs modes:

- `casual_operator`
- `tasking`
- `planning`
- `audit`
- `design`
- `execution_control`
- `incident_response`

Le mode depend de:

- la demande
- le risque
- le budget
- l'etat runtime
- le besoin de memoire

Le mode ne cree pas une nouvelle personnalite.
Il change le niveau de profondeur et le routage.

## Deliberation structuree

Quand un sujet depasse la simple reponse ou le simple run, le meme agent peut ouvrir une deliberation structuree.

Regles:

- le systeme reste un seul agent produit
- les angles d'analyse sont des prismes proceduraux, pas de nouveaux roles executifs
- le moteur canonique reste le graphe a 6 roles
- `Discord` montre un thread visible pour la reunion
- le runtime garde toujours le transcript machine complet
- une synthese humaine globale est republiquee dans `#pilotage`

## Couche 4 - Memoire partagee

Le meme agent n'est possible que si la memoire est partagee.

La memoire doit contenir:

- preferences durables du fondateur
- contexte projets
- decisions confirmees
- decisions changees
- incidents utiles
- contraintes confirmees
- habitudes de workflow

Discord, Claude API et les gros runs GPT API doivent tous se brancher sur:

- la meme memoire canonique
- les memes signaux de learning
- les memes handoffs

Regle operative supplementaire:

- le message brut fondateur doit rester tracable
- les resumes ne remplacent jamais l'intention brute
- le handoff entre modeles ne doit pas etre du texte libre seulement

## Regles du meme agent

- pas de personnalite differente entre `Claude API`, `GPT API` et `Discord`
- pas de prompt local qui contredit la constitution du projet
- pas de memoire privee implicite par canal
- pas de reponse Discord qui ignore les decisions confirmees du coeur

## Failsafe

Si le systeme detecte:

- derive de ton
- oubli de decisions centrales
- contradiction entre canaux
- reponses trop faibles sur Discord

alors il doit:

- recharger l'identite canonique
- recharger les decisions confirmees
- recharger les contraintes de canal
- produire un `refresh` recommande

## Verite runtime

La voix agent et la verite runtime sont deux couches differentes.

La persona fixe:

- la posture
- le ton
- les anti-patterns

La verite runtime fixe:

- quel provider est utilise dans ce tour
- quel modele est utilise dans ce tour
- quel workspace est gere
- quelles actions ont reellement ete executees

Regle dure:

- si le runtime contredit la vibe, le runtime gagne
- la voix ne peut jamais inventer une capacite, une inspection ou une execution

## Continuite de contexte

Le meme agent n'est reel que si le contexte est reconstruit proprement a chaque appel.

Le systeme doit donc toujours rehydrater:

- la persona canonique
- le contexte session recent
- l'historique recent du thread
- le hint de mood
- le handoff contract precedent si pertinent

Corollaire:

- pas de "memoire magique" cote provider
- pas de telephone arabe entre scripts
- pas de derive silencieuse du ton quand le modele change

## Cible

Le resultat vise est simple:

- meme agent
- plusieurs surfaces
- un seul cerveau systeme
- une seule memoire de reference
- plusieurs formats d'interaction
