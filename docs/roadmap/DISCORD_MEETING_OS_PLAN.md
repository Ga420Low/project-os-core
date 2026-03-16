# Discord Meeting OS Plan

## Statut

Feuille de route canonique proposee.

Ce document cadre le chantier `Discord Meeting OS` pour `Project OS`.

Il prolonge:

- `docs/roadmap/DISCORD_AUTONOMY_NO_LOSS_PLAN.md`
- `docs/roadmap/NATURAL_MANAGER_MODE_PLAN.md`

Le but n'est pas de remplacer le cockpit texte actuel.
Le but est de faire emerger une surface `meeting voice` durable, pilotable, memoire-aware et economiquement gouvernable.

## But

Faire de `Project OS` un systeme qui:

- peut rejoindre un vocal Discord uniquement quand le fondateur l'appelle
- garde `une seule voix visible`: le maitre
- permet au fondateur de changer le cerveau du maitre par langage naturel (`sonnet`, `opus`, `gpt`)
- conserve une `meeting memory` canonique pendant qu'une vraie reunion se deroule
- peut lancer des workers en arriere-plan pendant la reunion sans casser la fluidite du call
- prepare, plus tard, l'arrivee d'intervenants temporaires (`designer`, `coder`, `researcher`) sans perdre l'autorite du maitre

## Vision Future

La cible produit n'est pas un salon vocal rempli de bots qui parlent en meme temps.

La cible produit est:

- `1 maitre visible`
- `N specialistes temporaires`
- `N workers silencieux`

Le maitre:

- conduit l'appel
- garde la memoire officielle
- change de mode sur ordre du fondateur
- resume les interventions
- lance les workers de fond
- arbitre ce qui reste en memoire et ce qui est ecarte

Le fondateur:

- appelle le maitre
- ne recoit jamais d'appel sortant du systeme
- peut dire `mets-toi en mode opus`, `passe en mode sonnet`, `reste en mode gpt`
- peut dire `fais venir le designer`
- peut continuer la reunion pendant qu'un worker code, recherche ou redige

Les intervenants futurs:

- entrent peu de temps
- sont briefes par le maitre
- font une proposition limitee
- ressortent
- leur contribution est transformee en memoire exploitable

## Point de Depart Reel

### Ce qui existe deja dans le repo

- contrat `single voice` Discord texte deja durci via OpenClaw + gateway adapter
- `typing`, `approval / cout / temps / API`, `mode simple / avance / extreme`, `deep research`, `artifact-first` deja poses
- `PersistentSessionState` et `thread bindings` deja presents pour garder la continuite de conversation
- `GatewayService` sait deja:
  - gerer les approvals runtime
  - gerer les bascules de modele
  - conserver des artefacts durables
  - router du travail vers des workers et runs canoniques
- `Discord Autonomy No-Loss` est ferme et donne deja:
  - ingress durable
  - sorties reviewables
  - replay-safe delivery

### Endroits concrets reutilisables

- `src/project_os_core/gateway/service.py`
- `src/project_os_core/session/state.py`
- `src/project_os_core/gateway/openclaw_live.py`
- `src/project_os_core/api_runs/service.py`
- `integrations/openclaw/project-os-gateway-adapter/index.js`
- `docs/integrations/OPENCLAW_DISCORD_OPERATIONS_UX.md`

### Ce qui manque encore

- aucun lane `Discord voice` canonique
- aucune notion de `meeting_session` persistante
- aucun bus `speech-to-text -> master runtime -> text-to-speech`
- aucun `meeting mode switch` persistant au niveau vocal
- aucun protocole `guest agent`
- aucun `background worker mesh` visible pendant un call
- aucun vrai `cost accounting` par reunion

## Regles d'Architecture

### 1. Inbound Only

Regle dure:

- le maitre ne t'appelle jamais
- il rejoint seulement un vocal ou une session que le fondateur a explicitement ouverte

### 2. Single Visible Voice

Regle dure:

- une seule voix visible au debut: le maitre
- les workers de fond ne parlent pas
- les agents invites plus tard sont des exceptions explicites, pas le mode par defaut

### 3. Voice Is A Facade, Project OS Remains Truth

La verite canonique reste dans `Project OS`, pas dans Discord voice:

- session
- transcript
- decisions
- actions
- budgets
- workers

### 4. Meeting Mode Is Explicit

Le maitre doit pouvoir basculer entre:

- `simple`
- `avance`
- `extreme`

et plus tard entre fournisseurs:

- `sonnet`
- `opus`
- `gpt`

Chaque bascule doit avoir:

- un mode courant visible
- un cout previsionnel
- une justification si le cout monte

### 5. Guest Agents Are Temporary, Not Sovereign

Un invite futur:

- n'entre que sur demande
- parle peu
- ne garde pas la memoire officielle
- ne remplace pas le maitre

### 6. Background Workers Stay Silent

Les workers de production:

- peuvent coder
- chercher
- rediger
- analyser

mais ne parlent pas dans le vocal par defaut.

Le maitre seul restitue leur progression.

### 7. Cost Truth Beats Vibes

Le systeme doit distinguer:

- estimation avant run
- cout reel post-run
- cout du master
- cout des guests
- cout des workers
- cout total par reunion

### 8. Safety Before Convenience

Pas de version acceptable qui:

- laisse un guest parler librement sans garde-fou
- laisse un worker prendre la parole sans mandat
- fait des appels sortants
- engage de gros couts sans signal lisible

## Cartographie Externe

### Discord Gateway / Voice

Sources primaires:

- [Discord Gateway Events](https://docs.discord.com/developers/events/gateway-events)
- [Discord Gateway](https://docs.discord.com/developers/events/gateway)
- [Discord Opcodes and Status Codes](https://docs.discord.com/developers/topics/opcodes-and-status-codes)

Ce qu'on recupere:

- `Update Voice State` pour joindre / bouger / quitter un vocal
- `Voice State Update` / `Voice Server Update` comme base de synchronisation runtime
- discipline `Gateway` pour presence, heartbeat, reprise et etat

Ce qu'on n'importe pas:

- pas de multi-voice improvisation au niveau produit
- pas de logique ou le bot appelle lui-meme
- pas de seconde verite Discord-only hors runtime canonique

Ou ca entre:

- `Pack 1 - Voice Session Contract`
- `Pack 2 - Voice Transport And Speech Loop`

Decision:

- `KEEP`

### OpenAI Realtime / STT / TTS

Sources primaires:

- [OpenAI API pricing](https://openai.com/api/pricing/)
- [gpt-realtime](https://developers.openai.com/api/docs/models/gpt-realtime)
- [gpt-4o-mini-transcribe](https://developers.openai.com/api/docs/models/gpt-4o-mini-transcribe)
- [gpt-4o-mini-tts](https://developers.openai.com/api/docs/models/gpt-4o-mini-tts)

Ce qu'on recupere:

- vrai lane `speech in / speech out`
- bons candidats `STT` et `TTS`
- calcul de cout audio par tokens ou par minutes
- bonne base economique pour un `master voice`

Ce qu'on n'importe pas:

- pas de dependance obligatoire a `Realtime` des le jour 1
- pas de `speech-to-speech` complet tant que la couche master texte n'est pas stable

Ou ca entre:

- `Pack 2 - Voice Transport And Speech Loop`
- `Pack 3 - Meeting Mode Switching And Cost Guard`
- `Pack 7 - Cost Accounting And Live Evals`

Decision:

- `ADAPT`

### Anthropic Claude

Sources primaires:

- [Claude models overview](https://platform.claude.com/docs/en/about-claude/models/overview)

Ce qu'on recupere:

- `Opus` comme cerveau haut de gamme pour discussions tres complexes
- `Sonnet` comme mode avance plus economique
- logique `master brain` compatible avec le runtime actuel deja en place

Ce qu'on n'importe pas:

- pas de lane audio natif Anthropic comme prerequis du lot
- pas de guest agents vocaux Anthropic des la premiere version

Ou ca entre:

- `Pack 3 - Meeting Mode Switching And Cost Guard`
- `Pack 4 - Meeting Memory`
- `Pack 5 - Worker Mesh`

Decision:

- `KEEP`

## Pourquoi Cet Ordre

L'ordre est important.

Si on commence par:

- plusieurs voix
- plusieurs agents parlants
- workers qui parlent

on va produire un systeme impressionnant en demo mais fragile en reel.

L'ordre sain est:

1. faire joindre et parler le maitre proprement
2. le rendre gouvernable par modes et couts
3. lui donner une vraie memoire de reunion
4. lui faire lancer des workers en fond
5. seulement ensuite, laisser entrer des invites temporaires

Cet ordre ferme les risques dans le bon sens:

- d'abord transport
- puis cout
- puis memoire
- puis execution
- puis multi-agent voice

## Packs

### Pack 1 - Voice Session Contract

Pourquoi maintenant:

- sans contrat vocal clair, tout le reste est flou

Objectif:

- definir la session vocale canonique cote `Project OS`

Livrables:

- dataclass `MeetingSession`
- dataclass `MeetingTurn`
- dataclass `MeetingModeState`
- table `meeting_sessions`
- table `meeting_turns`
- table `meeting_mode_events`
- regle `inbound_only`
- regle `single_master_voice`
- etat `voice_joined / voice_left / muted / speaking / idle`

Ou cela entre:

- `src/project_os_core/meeting/`
- `src/project_os_core/models.py`
- `src/project_os_core/database.py`

Case a cocher:

- `Pack 1 - Voice Session Contract`

### Pack 2 - Voice Transport And Speech Loop

Pourquoi ici:

- une fois le contrat pose, on branche le vocal reel

Objectif:

- faire entrer et sortir la voix du maitre proprement

Livrables:

- service `DiscordVoiceBridge`
- join / leave / reconnect
- `STT` pipeline
- `TTS` pipeline
- `push-to-talk` logique cote bot
- `typing / speaking / muted` observability

Ou cela entre:

- `src/project_os_core/voice/discord_voice.py`
- `src/project_os_core/voice/stt.py`
- `src/project_os_core/voice/tts.py`
- `integrations/openclaw/` seulement si la facade doit etre etendue

Case a cocher:

- `Pack 2 - Voice Transport And Speech Loop`

### Pack 3 - Meeting Mode Switching And Cost Guard

Pourquoi ici:

- la voix sans gouvernance de cout sera vite inutilisable

Objectif:

- permettre `mets-toi en mode sonnet / opus / gpt`

Livrables:

- `meeting mode state`
- parser naturel des ordres de mode
- `approval if cost jumps`
- estimation avant prise en charge
- mode courant visible
- route `simple / avance / extreme`
- route `sonnet / opus / gpt`

Ou cela entre:

- `src/project_os_core/gateway/service.py`
- `src/project_os_core/session/state.py`
- `src/project_os_core/meeting/service.py`

Case a cocher:

- `Pack 3 - Meeting Mode Switching And Cost Guard`

### Pack 4 - Meeting Memory And Artifact Output

Pourquoi ici:

- une reunion sans memoire durable n'est qu'un chat vocal de plus

Objectif:

- produire une memoire canonique de reunion

Livrables:

- transcript brut
- transcript nettoye
- decisions retenues
- idees rejetees
- actions ouvertes
- resumes par sequence
- export `Markdown + PDF`

Ou cela entre:

- `src/project_os_core/meeting/memory.py`
- `src/project_os_core/gateway/reply_pdf.py`
- `docs/integrations/OPENCLAW_DISCORD_OPERATIONS_UX.md`

Case a cocher:

- `Pack 4 - Meeting Memory And Artifact Output`

### Pack 5 - Background Worker Mesh

Pourquoi ici:

- une fois la reunion stable, on la rend productive

Objectif:

- laisser le maitre lancer des workers pendant l'appel

Livrables:

- `meeting_worker_assignments`
- statut worker pendant meeting
- restitution par le maitre
- workers silencieux par defaut
- fondation `GPT code only` si decide

Ou cela entre:

- `src/project_os_core/meeting/workers.py`
- `src/project_os_core/api_runs/service.py`
- `src/project_os_core/router/service.py`

Case a cocher:

- `Pack 5 - Background Worker Mesh`

### Pack 6 - Guest Agent Protocol

Pourquoi pas avant:

- avant ce point, plusieurs voix casseraient la lisibilite produit

Objectif:

- faire entrer un specialiste temporaire sans casser l'ordre de la reunion

Livrables:

- `guest agent request`
- `guest join`
- `guest brief`
- `guest proposal capture`
- `guest leave`
- memoire de contribution

Exemples futurs:

- `fais venir le designer`
- `fais venir le researcher`
- `fais venir le coder`

Ou cela entre:

- `src/project_os_core/meeting/guests.py`
- `src/project_os_core/meeting/service.py`

Case a cocher:

- `Pack 6 - Guest Agent Protocol`

### Pack 7 - Cost Accounting, Safety And Live Evals

Pourquoi a la fin:

- il faut mesurer le systeme reel, pas un fantasme

Objectif:

- savoir combien coute vraiment une reunion et si elle reste pilotable

Livrables:

- cout estime vs cout reel
- cout par minute
- cout master / guest / worker
- evals `meeting quality`
- smoke tests vocaux
- garde-fou `no outbound call`
- garde-fou `single visible voice`

Ou cela entre:

- `src/project_os_core/meeting/costs.py`
- `src/project_os_core/meeting/evals.py`
- `tests/unit/`
- `tests/integration/`

Case a cocher:

- `Pack 7 - Cost Accounting, Safety And Live Evals`

## KPIs

Le lot ne doit pas etre juge sur l'effet wow.

Il doit etre juge sur:

- temps de join vocal
- stabilite du transport voice
- latence `speech in -> first answer`
- cout par reunion
- cout par heure
- precision des estimations
- taux de decisions bien capturees
- taux de workers lances et suivis proprement
- `outbound call incidents = 0`
- `multi-voice chaos incidents = 0`

## Non-Buts

Ce lot ne vise pas, au debut:

- une agora de plusieurs bots qui discutent librement
- un mode ou les guests restent tout l'appel
- un systeme qui t'appelle tout seul
- une simulation sociale pour le fun

## Sources

- [Discord Gateway Events](https://docs.discord.com/developers/events/gateway-events)
- [Discord Gateway](https://docs.discord.com/developers/events/gateway)
- [Discord Opcodes and Status Codes](https://docs.discord.com/developers/topics/opcodes-and-status-codes)
- [OpenAI API pricing](https://openai.com/api/pricing/)
- [gpt-realtime](https://developers.openai.com/api/docs/models/gpt-realtime)
- [gpt-4o-mini-transcribe](https://developers.openai.com/api/docs/models/gpt-4o-mini-transcribe)
- [gpt-4o-mini-tts](https://developers.openai.com/api/docs/models/gpt-4o-mini-tts)
- [Claude models overview](https://platform.claude.com/docs/en/about-claude/models/overview)
