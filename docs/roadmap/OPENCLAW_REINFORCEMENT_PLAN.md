# OpenClaw And NemoClaw Reinforcement Plan

## Statut

Feuille de route canonique.

Reecriture du plan le `2026-03-17` apres audit local des repos:

- `E:/ProjectOSArchive/external_audit/openclaw`
- `E:/ProjectOSArchive/external_audit/nemoclaw`

## But

Amener `Project OS` au niveau de discipline runtime d'`OpenClaw` et de `NemoClaw` sans casser l'UX discussionnelle du produit.

Le cap n'est pas de copier leur interface telle quelle.
Le cap est:

- de reprendre leurs invariants de verite
- de reprendre leur separation `conversation / control / runtime`
- de garder `Discord` comme surface de discussion naturelle
- de garder `Project OS.exe` comme surface canonique du detail operatoire

## Position produit retenue

Regles dures:

- `Project OS` reste la verite canonique
- `Discord` reste une surface de discussion d'abord
- les commandes explicites existent comme filet de securite et voie operateur, pas comme UX principale
- `Project OS.exe` reste la source canonique pour le detail operatoire, les vues, le monitoring et les preuves
- aucune idee upstream ne doit creer une deuxieme architecture concurrente a `Project OS`

Consequence directe:

- on ne veut pas d'un bot qui force le fondateur a taper uniquement `/status` ou `/mode`
- on veut qu'un message naturel comme `mets toi en mode avance`, `fais une recherche approfondie`, `ou j'en suis`, `debug ca` resolve la meme primitive de controle en interne
- les commandes explicites `Discord` restent utiles pour les cas operateur, les scripts, le fallback deterministe et le debuggage

Position de merge retenue:

- `OpenClaw` est considere comme une base solide sur laquelle il est rationnel de reconstruire
- quand une petite capacite historique `Project OS` vaut la peine d'etre conservee, le chemin prefere est de la reconstituer proprement au-dessus des primitives upstream
- on ne veut pas "verser le vieux projet dans OpenClaw"
- on veut reprendre les bons morceaux metier `Project OS` sous forme de `adapters`, `wrappers`, `bridges`, `policies` et `surfaces`, jusqu'a ce que la nouvelle base soit plus propre que l'ancienne
- si une capacite n'entre pas proprement dans cette structure, c'est un signal qu'il faut la redesigner, pas la coller

## Verites upstream a reprendre

### OpenClaw

Ce qu'`OpenClaw` fait mieux que nous aujourd'hui:

- queue disciplinee par `session key` et lane dediee
- modes de queue explicites (`interrupt / steer / followup / collect` + backlog variants) exposes comme verite runtime et non comme comportement implicite
- routing Discord deterministe
- sessions slash separees de la conversation, tout en gardant la session cible
- surfaces de controle first-class (`/status`, `/config`, `/debug`)
- raccourcis et directives inline (`/think`, `/verbose`, `/usage`, `/compact`, `/new`, `/reset`) traites avant le modele
- inline shortcuts de type `hey /status` traites avant generation libre et retires du prompt
- commandes autorisees par policy et access groups
- command gating explicite sur les controles texte, pas seulement un conseil de prompt
- runtime controls explicites de type `session/status`, `session/set_mode`, `session/set_config_option`
- compaction et hygiene de session comme primitives de controle, pas comme detail d'UX
- regle produit tres simple: quand un outil first-class existe, le modele ne doit pas improviser a sa place

References locales:

- `E:/ProjectOSArchive/external_audit/openclaw/docs/concepts/queue.md`
- `E:/ProjectOSArchive/external_audit/openclaw/docs/channels/discord.md`
- `E:/ProjectOSArchive/external_audit/openclaw/docs/cli/index.md`
- `E:/ProjectOSArchive/external_audit/openclaw/CHANGELOG.md`
- `E:/ProjectOSArchive/external_audit/openclaw/docs/concepts/context.md`
- `E:/ProjectOSArchive/external_audit/openclaw/src/channels/command-gating.ts`
- `E:/ProjectOSArchive/external_audit/openclaw/src/auto-reply/reply.raw-body.test.ts`
- `E:/ProjectOSArchive/external_audit/openclaw/src/auto-reply/status.ts`
- `E:/ProjectOSArchive/external_audit/openclaw/src/gateway/server-methods/chat.ts`
- `E:/ProjectOSArchive/external_audit/openclaw/src/acp/control-plane/manager.runtime-controls.ts`
- `E:/ProjectOSArchive/external_audit/openclaw/src/agents/system-prompt.ts`
- `E:/ProjectOSArchive/external_audit/openclaw/src/agents/tools/message-tool.ts`
- `E:/ProjectOSArchive/external_audit/openclaw/src/agents/tools/slack-actions.ts`

### NemoClaw

Ce que `NemoClaw` ajoute au-dessus d'`OpenClaw`:

- un vrai host control plane (`onboard`, `connect`, `status`, `logs`)
- un lifecycle deployable `resolve -> verify digest -> plan -> apply -> status`
- des policies declaratives par preset
- un onboarding avec preflight et persistence d'etat host
- un registre explicite des sandboxes et credentials host
- un `status` qui agrege sandbox, blueprint, inference et services
- une verification de health et de readiness pendant l'onboarding
- un dashboard operatoire minimal avec run/status/logs immediatement exploitables
- une execution bornee par runtime, pas seulement par prompt

References locales:

- `E:/ProjectOSArchive/external_audit/nemoclaw/docs/reference/architecture.md`
- `E:/ProjectOSArchive/external_audit/nemoclaw/docs/reference/commands.md`
- `E:/ProjectOSArchive/external_audit/nemoclaw/bin/lib/onboard.js`
- `E:/ProjectOSArchive/external_audit/nemoclaw/bin/lib/registry.js`
- `E:/ProjectOSArchive/external_audit/nemoclaw/bin/lib/credentials.js`
- `E:/ProjectOSArchive/external_audit/nemoclaw/bin/lib/preflight.js`
- `E:/ProjectOSArchive/external_audit/nemoclaw/bin/lib/policies.js`
- `E:/ProjectOSArchive/external_audit/nemoclaw/nemoclaw/src/commands/status.ts`
- `E:/ProjectOSArchive/external_audit/nemoclaw/nemoclaw-blueprint/policies/presets/discord.yaml`

### Forks utiles

Ce que les forks ajoutent de pertinent:

- `LocalClaw`: health check du stack modele, routage en tiers, timeouts/fallback propres, statuts plus riches
- `EdgeClaw`: privacy tiers `S1 / S2 / S3`, protocole `Hooker -> Detector -> Action`, action gating par surface
- `QVerisBot`: onboarding produit plus muscle, couche toolbox `discover -> inspect -> call`, hooks memoire cross-session, `dashboard-v2` modulaire et `command palette`
- `DenchClaw`: provider discovery/onboarding branchable dans le produit et compaction rendue visible dans les runs
- `openclaw-cn`: action gating reutilisable, recovery de compaction et visibilite restreinte des outils de session en mode sandbox

References minimales:

- `E:/ProjectOSArchive/external_audit/forks/localclaw/src/wizard/onboarding.model-strategy.ts`
- `E:/ProjectOSArchive/external_audit/forks/localclaw/src/commands/status.command.ts`
- `E:/ProjectOSArchive/external_audit/forks/localclaw/src/agents/timeout.ts`
- `E:/ProjectOSArchive/external_audit/forks/edgeclaw/src/agents/tools/slack-actions.ts`
- `E:/ProjectOSArchive/external_audit/forks/edgeclaw/src/agents/tools/telegram-actions.ts`
- `E:/ProjectOSArchive/external_audit/forks/qverisbot/CHANGELOG.md`
- `E:/ProjectOSArchive/external_audit/forks/qverisbot/src/agents/system-prompt.ts`
- `E:/ProjectOSArchive/external_audit/forks/qverisbot/src/agents/tools/qveris-tools.ts`
- `E:/ProjectOSArchive/external_audit/forks/qverisbot/src/hooks/bundled/context-digest/handler.ts`
- `E:/ProjectOSArchive/external_audit/forks/qverisbot/src/hooks/bundled/session-importance/handler.ts`
- `E:/ProjectOSArchive/external_audit/forks/qverisbot/ui/src/ui/views/command-palette.ts`
- `E:/ProjectOSArchive/external_audit/forks/denchclaw/extensions/dench-ai-gateway/index.ts`
- `E:/ProjectOSArchive/external_audit/forks/denchclaw/apps/web/lib/active-runs.ts`
- `E:/ProjectOSArchive/external_audit/forks/openclaw-cn/src/agents/tools/common.ts`
- `E:/ProjectOSArchive/external_audit/forks/openclaw-cn/src/agents/tools/discord-actions.ts`
- `E:/ProjectOSArchive/external_audit/forks/openclaw-cn/src/agents/tools/sessions-history-tool.ts`

## Ce que `Project OS` a deja

Acquis utiles a conserver:

- `DiscordThreadBinding` persistant
- `founder_session_key`
- `handoff_contract`
- `GatewayContextBundle` avec `intent_class`, `grounding_mode`, `execution_claim_mode`, `execution_evidence`
- `desktop_view_refs` et registre de vues canoniques
- `truth_first_context_metadata`
- `truth_registry`, `canonical_views`, `truth_cards`, `founder_session_spine`
- mode `simple / avance / extreme` deja gere comme decision explicite
- `deep research` deja separe du chat normal
- surfaces CLI locales `review status` et `debug discord-audit`
- premier contrat de verite sur les claims de completion, de repo et de navigation desktop

References locales:

- `src/project_os_core/gateway/service.py`
- `src/project_os_core/gateway/context_builder.py`
- `src/project_os_core/config.py`
- `src/project_os_core/cli.py`
- `docs/workflow/DEEP_RESEARCH_PROTOCOL.md`

## Ce qui manque encore

Les vrais trous restants:

- le controle est encore trop diffuse entre chat, approvals, desktop handoff et CLI
- le classifieur d'intent reste trop lexical
- le grounding repo est maintenant deterministic pour les citations verifiees, mais on n'a pas encore la chaine complete `discover -> inspect -> call`
- la separation `conversation session / control session` couvre maintenant les surfaces `status / mode / recherche / debug / where / compact / usage / new / reset`, mais le gating strict facon `useAccessGroups` reste a faire
- les `queue modes` sont maintenant traces et expliques dans le runtime, mais la vraie politique par surface, restart et directives inline reste a finir
- on a maintenant une premiere couche policy-backed (`privacy_guard`, approvals bornees, `security_request`, `security_boundaries`, trust audit OpenClaw cache), ainsi qu'un premier host-like control plane `preflight / onboard / runtime registry`; il manque encore le registry provider plus profond et le lifecycle complet facon `NemoClaw`
- on n'a pas encore de couche inline/directive comparable a `OpenClaw` sur toute la largeur des shortcuts upstream
- on n'a pas encore d'auth stricte des commandes de controle facon `useAccessGroups`
- le modele `pairing / approvals / allowlists` est maintenant lisible dans le runtime et le review loop, mais il n'est pas encore generalise a toutes les surfaces et tous les canaux sensibles
- l'audit `exposure matrix / attack surface` existe maintenant, et il est complete par un `runtime registry` operateur; il reste trop borne pour remplacer un vrai registre provider/preflight plus large
- la sante du stack modele et le routage degrade sont maintenant visibles, et un premier `runtime registry` couvre `Discord / desktop / models / research / providers`; le registre provider plus profond reste a faire
- on a maintenant un vrai preflight/onboarding/runtime registry pour les surfaces sensibles principales, mais pas encore un registre host/provider complet de niveau `NemoClaw`
- on n'a pas encore de guard protocol de privacy/routing comparable a `EdgeClaw`
- on n'a pas encore de contrat `discover -> inspect -> call` pour les capacites externes
- on a maintenant un premier spine `session_continuity` avec `context digest`, `session importance`, compaction visible et recovery lisible dans le runtime, le desktop et `review status`; les hooks memoire asynchrones plus larges restent a faire
- on n'a pas encore de policy nette de visibilite des outils de session depuis des contextes ou runs sensibles
- on a maintenant une premiere discipline `queue continuity / recovery restart / continuation post-compaction` adossee aux `thread_ledgers` et `discord_thread_bindings`; le vrai backend de queue persistant de type `openclaw-cn` reste a faire
- on a maintenant une premiere branche d'onboarding operateur injectable dans le produit, mais pas encore le vrai `provider discovery` modulaire des forks les plus solides
- on n'a pas encore de strategie claire pour la continuite `lastAccountId / lastThreadId` et les resets propres
- on n'a pas encore assez de validation config / probe failure / backup-recovery discipline
- on n'a pas encore de vrai lifecycle provider modulaire facon `provider-owned onboarding / discovery / model-picker / post-selection hooks`
- la `command palette` operateur existe maintenant dans `Project OS.exe`, mais elle doit encore etre etendue aux couches policy/preflight plus dures des packs suivants
- si `Slack` devient une surface majeure, on n'a pas encore de replies interactives natives avec boutons/selects, preservation du callback context et fallback propre vers texte normal

Base deja durcie par `Pack 0`:

- les principaux reply paths republient maintenant le meme noyau `truth-first`
- `clarification_required`, `approval_required`, `session_resolved`, `duplicate_ingress` et les branches deep research critiques gardent `intent_class`, `grounding_mode`, `execution_claim_mode`, `execution_evidence`, `founder_session_key`, `desktop_view_refs`
- `project_review.py` lit maintenant les miroirs upstream/forks locaux avec chemins, SHAs et dates reelles au lieu de rester sur un simple rappel d'URLs

## Strategie retenue

Avant les principes de controle, la regle d'integration est:

- `OpenClaw` = fondation runtime forte
- `Project OS` = couche produit, memoire, audit, surfaces operateur
- on merge les idees et les capacites, pas les couches en vrac
- les petites briques utiles de l'ancien projet peuvent etre recreees au-dessus de la fondation `OpenClaw` si cela garde la lisibilite et la frontiere de verite
- un "petit bout a reimporter" est acceptable seulement si son point d'ancrage est clair et si sa reimplementation est plus propre que sa transplantation brute

### Principe 1 - Discussion first, control second

Le produit doit rester fluide en langage naturel.

Ce que cela veut dire:

- la conversation naturelle reste la voie principale
- les commandes explicites ne sont pas obligatoires
- toute demande naturelle de type `status`, `mode`, `recherche`, `debug` doit etre resolue en interne comme une action de controle deterministe
- les commandes explicites restent disponibles comme voie de secours et pour les usages operateur

### Principe 2 - Une primitive interne par intention de controle

Chaque controle important doit avoir une primitive interne unique:

- `status`
- `mode`
- `deep_research`
- `debug`
- `where`

La forme utilisateur peut varier:

- phrase naturelle
- commande explicite
- bouton
- command palette desktop
- handoff desktop

Mais le coeur runtime doit etre le meme.

### Principe 2 bis - Directives naturelles avant slash commands

Le meilleur de `OpenClaw` n'est pas seulement la presence de slash commands.
C'est le fait qu'une partie des controles est extraite avant le modele.

Chez nous, on retient:

- phrases naturelles d'abord
- directives inline ensuite
- slash commands seulement en secours operateur

Exemples de primitives a unifier:

- `mode`
- `status`
- `debug`
- `deep research`
- `compact`
- `usage`

### Principe 2 ter - Parser et gate avant le modele

Les primitives de controle ne doivent pas etre laissees au texte libre du prompt.

Chez nous, cela veut dire:

- parser d'abord les directives naturelles et inline
- verifier ensuite l'autorisation de controle
- seulement apres, laisser le message restant partir au modele

La robustesse ne vient pas d'une phrase de plus dans le prompt.
Elle vient d'un pipeline `parse -> gate -> route -> answer`.

### Principe 2 quater - Discover, inspect, puis call

Quand une capacite externe ou specialisee existe, le systeme doit:

- decouvrir la capacite
- verifier sa disponibilite et son schema
- seulement ensuite la promettre ou l'appeler

On ne promet jamais une integration, un fichier, un ecran ou un outil sans verification.

### Principe 3 - Evidence first

- aucun fichier repo ne doit etre cite sans grounding reel
- aucune completion ne doit etre dite `faite` sans preuve
- aucune vue desktop ne doit etre citee hors registre canonique
- aucune capacite locale ne doit etre promise depuis `Discord` si le runtime ne la prouve pas

### Principe 4 - Runtime boundaries, pas seulement prompt boundaries

Le chat ne peut pas porter seul la securite.

Il faut une couche runtime plus dure:

- separation conversation / control
- etats d'execution canoniques
- policies de surface
- policies reseau / process / filesystem quand on activera la couche correspondante Windows-first

## Pack 0 - Consolidate Existing Truth-First Spine

### Objet

Solidifier ce qui existe deja avant d'ajouter de nouvelles primitives upstream.

### Decision

`KEEP` puis `HARDEN`

### Etat

`IMPLEMENTED` le `2026-03-17`

### Pourquoi il existe

Le repo a deja un socle utile:

- `GatewayContextBundle`
- `truth_first_context_metadata`
- `truth_registry`
- `founder_session_spine`
- `truth_cards`
- `project_review` et `docs_audit`

Mais ce socle n'est pas encore uniforme sur tous les chemins.

### Travaux

- faire passer le meme noyau de verite dans `chat_response`, `ack`, `clarification_required`, `approval_required`, `blocked`
- verifier particulierement les builders de `clarification_required` et les approvals guardian
- figer l'usage de `truth_registry`, `desktop_view_refs` et `founder_session_spine` comme dependances obligatoires des handoffs
- aligner `project_review.py` sur le dossier upstream local et les SHAs reels des miroirs
- garder la preuve de l'audit sur disque, pas seulement dans la fenetre de contexte

### Criteres d'acceptation

- aucun chemin de reply important ne perd `intent_class`, `grounding_mode`, `execution_claim_mode`, `execution_evidence`, `founder_session_key`, `desktop_view_refs`
- les handoffs desktop reposent tous sur le registre canonique
- `project_review.py` remonte un upstream/fork snapshot plus proche du dossier local que d'un simple rappel d'URLs
- la base existante est stabilisee avant toute extension `Pack 1+`

### Verification

- `tests/unit/test_gateway_and_orchestration.py`
- `tests/unit/test_gateway_context_builder.py`
- `tests/unit/test_project_review.py`
- `project_os_entry.py review status --limit 8 --markdown`

### Non-buts

- recreer un nouveau socle
- attaquer le parser de directives avant d'avoir verrouille la verite deja presente

## Pack 1 - Deterministic Conversation And Control Sessions

### Objet

Reprendre l'idee `OpenClaw` de sessions de commande separees, sans casser l'UX discussionnelle.

### Decision

`ADAPT`

### Etat

`COEUR_LIVRE`

### Ce qu'on prend

- une `conversation session` pour le fil normal
- une `control session` separee pour les actions `status / mode / recherche / debug`
- une `target session key` attachee a l'action de controle
- des `queue modes` explicites pour les messages entrants quand une run est deja active

### Ce qu'on adapte

- chez nous, la plupart des actions pourront etre declenchees par phrase naturelle
- la separation est surtout une verite runtime interne, pas une obligation UX visible

### Etat au `2026-03-17`

`COEUR_LIVRE`

Ce qui est effectivement en place dans le code:

- parseur partage `control_intent` pour les primitives `status` et `mode`
- `conversation_session_key`, `control_session_key` et `control_target_session_key` calcules et republies dans le noyau `truth-first`
- `queue_mode` + `queue_mode_reason` derives de facon deterministe et persistés dans les dispatch metadata, les bindings Discord et le thread ledger
- `delivery_target_ref` persiste dans le binding et le ledger pour eviter la perte silencieuse de cible
- une trace separee `control_action` dans le ledger runtime
- une phrase naturelle `ou j'en suis` et la commande `/status` resolvent la meme primitive
- une phrase naturelle `mets toi en mode avance` et la commande `/mode avance` resolvent la meme primitive

Ce qui reste volontairement hors de ce pack:

- parser pre-modele complet qui retire les directives du prompt
- `new / reset / compact / usage` comme primitives hard
- gating strict des commandes de controle facon `useAccessGroups`
- extension du meme mecanisme a toutes les commandes `debug / recherche / where`

### Travaux

- introduire une notion explicite de `control intent`
- creer un binding `control session -> conversation session`
- faire en sorte que les commandes explicites et les phrases naturelles utilisent la meme primitive
- garder le thread Discord visible unique, sauf cas operateur particulier
- preserver explicitement la cible de delivery (`lastAccountId / lastThreadId` ou equivalent produit) dans les bindings et ledgers de thread pour servir de base aux futurs flows `reset / new / compact`
- definir des modes `interrupt / steer / followup / collect` adaptes a `Project OS`, avec politique par surface et statut visible

### Criteres d'acceptation

- une demande `mets toi en mode avance` et une commande `/mode avance` resolvent la meme primitive
- une demande `ou j'en suis` et une commande `/status` resolvent la meme primitive
- le controle n'empoisonne pas la session de discussion principale
- le runtime garde une trace separee des actions de controle
- la cible de reply est persistee explicitement dans les bindings et ledgers; son exploitation par `/new` et `/reset` est traitee au `Pack 2`
- le systeme sait expliquer quel `queue mode` est actif et pourquoi une nouvelle entree a ete steeree, collectee, suivie ou a interrompu le travail

### Non-buts

- imposer les slash commands comme seule UX
- dupliquer les threads Discord juste pour imiter l'upstream

## Pack 2 - Soft Control Surfaces For Discord

### Objet

Introduire des surfaces explicites utiles sans casser le cote discussion.

### Decision

`ADAPT`

### Position UX

`Discord` reste discussion-first.

On introduit:

- une voie naturelle prioritaire
- une voie explicite secondaire
- une voie inline directive quand elle permet de rester conversationnelle

Voies explicites minimales retenues:

- `/status`
- `/mode`
- `/recherche`
- `/debug`
- `/where`
- `/compact`
- `/usage`
- `/new`
- `/reset`

Directives naturelles / inline a supporter proprement:

- `mode avance`
- `recherche approfondie`
- `debug`
- `compacte le contexte`
- `quel est le statut`
- `nouvelle session`
- `reset la session`
- `combien ca coute`

### Regle produit

- l'utilisateur ne doit pas etre oblige d'utiliser ces commandes
- mais ces commandes doivent exister pour les cas de fallback, de support et d'operateur

### Etat au `2026-03-17`

`COEUR_LIVRE`

Ce qui est effectivement en place dans le code:

- parseur pre-modele partage pour:
  - `/status`
  - `/mode`
  - `/recherche`
  - `/debug`
  - `/where`
  - `/compact`
  - `/usage`
  - `/new`
  - `/reset`
- formes naturelles ou inline resolues sur les memes primitives runtime quand elles sont clairement identifiees
- retrait des directives resolues du prompt libre pour les controles qui continuent ensuite la discussion (`mode`, `compact`, `new`, `reset`)
- `deep research` garde son flow existant et `/recherche` le re-utilise sans deuxieme architecture
- `/debug` est reserve a la control session operateur
- `/where` projette strictement le registre desktop canonique (`Overview / Session / Runs / Discord`, etc.)
- `/compact`, `/new`, `/reset` et `/usage` sont de vraies primitives runtime et non des phrases cosmetiques
- les metadonnees `truth-first` et les `queue modes` restent coherents sur ces surfaces

Ce qui reste volontairement hors de ce pack:

- gating strict type `useAccessGroups` avec plusieurs authorizers et politiques `allow/deny/configured`
- `/config` et les autres primitives de controle plus profondes vues upstream
- `Slack interactive replies`, tant que Slack n'est pas une surface prioritaire du produit
- la partie `repo grounding / truth propagation` qui appartient au `Pack 3`

### Travaux

- parser les commandes explicites tres tot dans le gateway
- parser aussi les directives inline et les phrases naturelles vers la meme primitive
- retirer ces directives du prompt quand elles ont deja ete resolues
- unifier les reponses `status / mode / recherche / debug` avec les flows naturels existants
- garder `mode` et `deep research` conversationnels par defaut
- faire de `/debug` une voie reservee operateur
- faire de `/where` une projection stricte du registre desktop canonique
- faire de `/compact`, `/new`, `/reset` et `/usage` de vraies primitives internes et non des bricolages de texte
- ajouter une policy d'autorisation pour les controles sensibles, equivalent produit de `commands.useAccessGroups`
- preparer une branche de delivery interactive reutilisable pour les surfaces qui la supportent reellement, au lieu de figer le systeme sur `texte seulement`
- si `Slack` devient une surface majeure, ajouter un vrai chemin `interactive replies` avec boutons/selects et preservation du callback context, aligne sur `channelData.slack.blocks` et les callbacks dedupes
- garder un fallback deterministe texte quand la surface ou le compte n'autorise pas l'interactif

### Criteres d'acceptation

- `deep research` continue a marcher en langage naturel
- `mode avance` continue a marcher en langage naturel
- `/recherche` et `/mode` existent comme filet de securite deterministe
- `/debug` ne passe pas par la generation libre du modele
- les controles inline sont resolves avant generation libre quand ils sont clairement identifies
- les controles resolves n'apparaissent plus dans le prompt libre envoye au modele
- `/compact` et sa forme naturelle resolvent la meme primitive de compaction
- les commandes sensibles ne sont pas ouvertes a n'importe quel emetteur
- les surfaces interactives ne sont activees que quand le runtime et la channel capability le prouvent
- si `Slack` est active avec replies interactives, les boutons/selects rendent une vraie action ou un vrai fallback, jamais du texte mort

Preuves obtenues a ce stade:

- `/mode avance explique ...` applique le mode puis continue sur le texte nettoye
- `/new ...` et `/reset ...` tournent les cles de session sans perdre le follow-up operatoire
- `/usage` repond deterministiquement sans generation libre
- `/debug` lit le dernier rapport local et reste gate cote operateur
- `/where` et les demandes naturelles de navigation renvoient les vues canoniques du desktop
- `/compact` declenche une vraie primitive runtime (`memory_blocks.refresh_runtime_blocks` + `tier_manager.compact`)

### Non-buts

- transformer `Discord` en terminal
- multiplier les surfaces si elles ne correspondent pas a une primitive runtime reelle
- imposer `Slack interactive replies` tant que `Slack` n'est pas une surface prioritaire du produit

## Pack 3 - Repo Grounding And Truth Propagation

### Objet

Supprimer les citations repo inventees et les faux verts conversationnels.

### Decision

`KEEP` sur le besoin, `REWRITE` sur l'implementation

### Etat

`COEUR_LIVRE`

### Travaux

- ajouter un module de grounding repo deterministe avant toute citation
- faire un post-check de la reponse pour rejeter toute citation non verifiee
- faire sortir les reponses `repo diagnosis` du prompt libre quand le runtime a deja une reponse verifiee plus forte
- propager les memes metadonnees de verite sur tous les reply paths:
  - `chat_response`
  - `ack`
  - `approval_required`
  - `clarification_required`
  - `blocked`
  - `session_reply`
- pousser `repo_grounding_summary` et `repo_grounding_count` dans les metadonnees runtime et de reply
- corriger les collisions de classification ou `repo` etait detecte comme sous-chaine dans `reponse`

### Criteres d'acceptation

- aucun fichier, dossier, fonction ou ligne n'est cite sans hit verifie
- `clarification_required` conserve `intent_class`, `execution_claim_mode`, `desktop_view_refs`, `founder_session_key`
- `session_reply` conserve lui aussi le meme noyau verite, y compris les nouveaux champs de grounding repo
- un test rouge en vrai ne peut plus etre cache par un test de phrase

Preuves obtenues a ce stade:

- `src/project_os_core/gateway/repo_grounding.py` calcule des hits repo verifies localement avant toute citation
- `GatewayService` enrichit le `context_bundle` avec `repo_grounding_summary`, `repo_grounding_count` et les hits verifies
- un `repo_diagnosis_request` Discord ne passe plus par la generation libre quand le runtime peut repondre plus proprement et plus vrai
- les reponses inline modele passent quand meme par un post-check qui rejette les references repo non verifiees
- le noyau verite inclut maintenant `repo_grounding_summary` / `repo_grounding_count` et repasse aussi dans `session_reply`
- la collision lexicale `repo` dans `reponse` ne bascule plus une escalation reasoning en faux `repo_diagnosis_request`

### Non-buts

- reparer le probleme par accumulation de regex
- generaliser des inspections de schemas/capabilities externes multi-outils avant `Pack 8`

## Pack 4 - Model Health And Routing Discipline

### Objet

Recuperer ce que `LocalClaw` apporte de mieux sans copier son produit:
visibilite de l'etat modele et routage degrade propre.

Etat:

- `COEUR_LIVRE`

### Decision

`ADAPT`

### Ce qu'on prend

- health check du stack modele au boot
- statut clair des tiers de modele
- routage degrade explicite
- etat/profile isole quand une surface l'exige
- budgets de timeout et politique de fallback documentes et verifiables
- statut operateur plus riche, proche d'un vrai `status` multi-source

### Travaux

- exposer un health snapshot modele plus fin dans `Project OS`
- rendre visible quel tier est actif et pourquoi
- definir les degradations propres:
  - local absent
  - local lent
  - API bloquee
  - fallback actif
- rendre visibles les budgets de timeout et la raison du basculement
- eviter que le chat improvise le provider/modele courant

### Criteres d'acceptation

- le systeme sait dire quel tier modele est pret, degrade ou bloque
- un statut runtime peut expliquer un fallback modele sans hallucination
- un timeout ou fallback est justifiable par une policy lisible, pas par une intuition du modele
- la roadmap `status` inclut modele, cout et fallback comme primitives verifiees

### Preuves obtenues a ce stade

- `src/project_os_core/router/service.py` expose maintenant `model_stack_health_snapshot`, `timeout_policy_snapshot` et `build_routing_status_snapshot` avec tiers, providers, budgets de timeout et fallback reason
- `src/project_os_core/gateway/service.py` garde un `provider_runtime_health` local, calcule un `model_routing_runtime_payload` et fait un fallback inline borne et visible entre `local`, `anthropic` et `openai`
- `src/project_os_core/local_model.py` accepte un `timeout_seconds` explicite pour que la policy locale ne reste pas implicite
- `status_request` et `usage_request` remontent maintenant `routing_status`, `provider_runtime_health` et `model_status_summary`
- `Project OS.exe` expose ce runtime via `model_routing_runtime`, cartes `Modele / Routing` et truth card `Model Routing`
- les tests couvrent le local lent, la policy timeout, le fallback runtime inline, et la lisibilite du modele dans `status`

### Ce qui reste volontairement hors de ce pack

- un vrai `discover -> inspect -> call` multi-capabilities
- un health/routing registry plus large branche sur onboarding/preflight (`Pack 8`)
- le contrat d'execution complet `ack -> pending -> completed_with_evidence` (`Pack 5`)

## Pack 5 - Execution Evidence Contract

### Objet

Aligner `Project OS` sur la discipline `OpenClaw/NemoClaw`:
pas de claim sans preuve.

Etat:

- `COEUR_LIVRE`

### Decision

`KEEP`

### Etat

- `COEUR_LIVRE_LE_2026-03-17`
- `NETTOYAGE_PHYSIQUE_GENERATED_ENCORE_A_FAIRE`

### Etats cibles

- `none`
- `prepare`
- `handoff`
- `execution_pending`
- `completed_with_evidence`

### Travaux

- separer clairement `ack` et `execution_pending`
- garder une evidence canonique pour toute completion
- empecher tout follow-up de transformer un `ack` en `done`
- exposer l'evidence dans les handoffs desktop et les reply metadata

### Criteres d'acceptation

- un `?` ou `c'est fait ?` ne peut jamais produire `oui` sans preuve
- un write local depuis Discord est soit `handoff`, soit `pending`, soit `completed_with_evidence`
- la capacite declaree du bot ne depasse jamais la surface reelle

### Preuves obtenues a ce stade

- `src/project_os_core/gateway/execution_evidence.py` centralise maintenant la normalisation `ack / prepare / handoff / execution_pending / completed_with_evidence`
- `src/project_os_core/gateway/context_builder.py` ne reutilise plus une ancienne preuve terminee pour une nouvelle directive d'ecriture et materialise une evidence explicite de surface pour `write_directive` et `capability_query`
- `src/project_os_core/gateway/service.py` separe maintenant `routing_ack` de `execution_pending`, porte des refs canoniques sur les approvals/deep research, et repond deterministiquement `oui` seulement quand `completed_with_evidence` est vrai
- l'escalade reasoning inline publie maintenant une completion verifiee, enrichie ensuite avec `reply_id` et eventuels artefacts de reponse
- `src/project_os_core/operator_visibility_policy.py` n'emploie plus le meme texte pour un simple reroutage queue et pour une execution deja prouvee
- les tests couvrent:
  - directive d'ecriture Discord -> `handoff` explicite
  - follow-up `?` apres `ack` -> jamais `done`
  - deep research lance -> `execution_pending` avec refs runtime
  - escalation reasoning terminee -> `completed_with_evidence`

### Ce qui reste volontairement hors de ce pack

- un contrat de preuves plus profond pour les effets de bord hors gateway (`Pack 7`)
- le registre host/preflight complet type `NemoClaw` (`Pack 8`)
- la persistance/replay de longue duree pour runs et livrables (`Pack 9`)

## Pack 6 - Desktop Truth Cards And Operator Handoff

### Objet

Faire de `Project OS.exe` l'equivalent produit local du host control plane de `NemoClaw`, sans perdre notre axe Windows-first.

### Decision

`ADAPT`

### Etat

`COEUR_LIVRE`

### Ce qu'on prend de NemoClaw

- `status`
- `logs`
- `connect`
- `health`
- policies visibles

### Ce qu'on adapte

- chez nous, cela devient des `truth cards` et des vues desktop canoniques
- le detail operatoire vit dans l'app, pas dans des commandes host Linux
- l'UX desktop peut reprendre l'idee `dashboard-v2` et `command palette`, mais uniquement branchee sur des donnees et actions reelles de `Project OS`

### Travaux

- enrichir les `truth_cards`
- faire de `/where` et des demandes naturelles de detail operatoire une simple projection du desktop
- rendre visibles les preuves d'execution, le statut de session et l'etat runtime dans l'app
- ajouter une `command palette` dans `Project OS.exe` pour lancer rapidement navigation, statut, focus session, runs, costs, discord, terminals et actions operateur reelles
- faire en sorte que la `command palette` reutilise le registre canonique des vues desktop et les actions runtime existantes, sans inventer d'ecran ni d'outil
- preparer une evolution de type `dashboard-v2` modulaire `overview / chat / config / agent / session` quand les backing data desktop sont assez solides

### Criteres d'acceptation

- `quel ecran ouvrir ?` ne peut plus inventer une vue
- `Project OS.exe` expose clairement le detail de session, status, approvals et evidence
- le handoff Discord vers desktop est sobre, court et toujours vrai
- la `command palette` ne lance que des actions vraies et navigue uniquement vers des vues canoniques
- la future couche `dashboard-v2` n'est pas un mockup vide: chaque module visible doit etre branche a un payload desktop reel

### Preuves obtenues a ce stade

- `Project OS.exe` expose maintenant un `operator_handoff` canonique lu depuis `gateway_dispatch_results` et `thread_ledgers`, au lieu d'un etat UI reconstruit a la main
- le `founder_session_spine` desktop embarque maintenant `latest_control_intent`, `latest_execution_evidence_status`, `latest_handoff_views` et `latest_delivery_target_label`
- les `truth_cards` desktop couvrent maintenant aussi `Execution Evidence` et `Operator Handoff`
- la vue `Session` affiche le handoff operatoire, les vues canoniques ciblees et l'etat de preuve sans inventer d'ecran
- la `command palette` est maintenant servie par le payload desktop (`command_palette.items`) et non plus seulement deduite dans le renderer
- la `command palette` ignore les actions non supportees et ne resolve que des vues canoniques ou des actions runtime reelles
- `tests/unit/test_desktop_control_room.py` couvre maintenant le chemin `gateway truth-first metadata -> desktop payload -> command palette`

## Pack 7 - Approvals, Privacy Guard, And Policy-Backed Boundaries

### Objet

Prendre la vraie lecon `NemoClaw` et `EdgeClaw`:
la securite vient du runtime et des guardrails, pas du prompt.

### Decision

`ADAPT`

### Ce qu'on prend

- lifecycle `resolve -> verify -> plan -> apply -> status`
- policies declaratives par preset
- surface de statut et de logs claire
- privacy tiers et guard protocol sur les contenus sensibles
- approvals et allowlists comme donnees runtime auditables
- audit d'exposition et de surface facon `security audit`

### Ce qu'on adapte

- pas de dependance `OpenShell`
- pas de pivot Linux-first
- implementation Windows-first, alignee sur `Project OS`

### Travaux

- definir des presets de surface et d'execution pour `Discord`, `deep research`, `repo audit`, `local writes`
- preparer un cycle `plan/apply/status` pour les actions sensibles
- separer les policies de surface, d'execution et de reseau
- definir une chaine `detect -> classify -> action` pour la privacy et le routing sensible
- distinguer au minimum des classes proches de `S1 / S2 / S3` pour nos surfaces
- definir quelles surfaces peuvent voir ou piloter quelles sessions internes
- definir un vrai modele `pairing / approvals / allowlists` pour les surfaces chat et les actions locales sensibles
- produire un audit d'exposition capable de classer `ok / warn / critical` les surfaces, policies, plugins et outils web/sandbox
- restreindre explicitement la visibilite des outils de session et des outils sensibles selon le contexte du run
- ajouter une vraie boucle operateur `security audit` de type `deep` puis `fix`, au lieu de laisser les checks de surface disperses entre docs, prompt et intuition
- definir un `device pairing` ou bootstrap token court-vivant pour les surfaces operateur sensibles, afin d'eviter tout secret durable ou broad auth partagee dans le chat

### Criteres d'acceptation

- les actions sensibles ont une policy lisible avant execution
- le systeme sait dire quelle policy a permis ou bloque une action
- les outils de session internes ne fuient pas hors de leur perimetre autorise
- on diminue la part de securite portee par le prompt seul
- les approvals et allowlists sont consultables, explicables et non caches dans des heuristiques de chat
- l'operateur peut voir une matrice d'exposition minimale sans relire tout le code
- un audit de securite operateur produit un resultat actionnable et un mode `fix` borne
- le pairing operateur n'expose pas de secret durable dans une surface conversationnelle

### Non-buts

- reimplementer `OpenShell`
- importer du code NVIDIA sans besoin net

### Preuves obtenues a ce stade

- `src/project_os_core/runtime/store.py` borne maintenant les approvals runtime avec expiration automatique, resolution mergee et lecture canonique des approvals pendantes
- `src/project_os_core/session/state.py` charge et republie les approvals pendantes et l'intent `security_request` comme primitives runtime lisibles
- `src/project_os_core/security_boundaries.py` produit maintenant un rapport `security_boundaries` avec checks `privacy_guard / approval_boundary / control_surface / openclaw_trust_audit`, `exposure_matrix`, `operator_views`, `operator_handoff` et mode `fix` borne
- `src/project_os_core/gateway/service.py` sert maintenant `/security` et ses formes naturelles, gate la surface cote operateur et execute un audit/fix local sans laisser le modele improviser la conclusion
- `src/project_os_core/desktop/control_room.py` expose `security_boundaries` dans les payloads, les truth cards, les vues `Overview / Config / Settings` et dans la `command palette` via `refresh_security_audit`
- `src/project_os_core/project_review.py` integre maintenant `security_boundaries` dans `review status`, l'escalade `attention / breach` et la synthese markdown
- les tests couvrent maintenant l'auto-expiration des approvals, la resolution mergee, le gating `security_request`, le mode `fix`, le payload desktop `security_boundaries` et la presence de la section `Security Boundaries` dans le review report

### Ce qui reste volontairement hors de ce pack

- un vrai host control plane `preflight / registry / onboard` type `NemoClaw` (`Pack 8`)
- la generalisation du pairing/bootstrap court-vivant a toutes les surfaces operateur sensibles
- une policy plus dure de visibilite des outils de session et des actions de controle facon `useAccessGroups`
- des checks `deep/fix` plus larges pour providers, plugins et surfaces hors du perimetre actuel

## Pack 8 - Onboarding, Preflight, And Runtime Registry

### Objet

Epaissir la couche operatoire avec les idees les plus utiles de `NemoClaw`.

### Etat

`COEUR_LIVRE_LE_2026-03-17`

### Decision

`ADAPT`

### Ce qu'on prend

- preflight explicite
- onboarding guide
- registre runtime des surfaces / sessions sensibles
- status agrege

### Travaux

- definir un preflight pour les surfaces critiques `Discord`, `desktop`, `models`, `research`
- garder un registre local des contextes / surfaces actives de controle
- produire un `status` qui agrege session, desktop, provider, evidence et surfaces critiques
- garder un registre runtime avec permissions strictes et etat operateur durable
- avoir un dashboard/summary minimal qui mene directement a `run`, `status`, `logs`
- preparer une branche produit d'onboarding/provider discovery pour les futures integrations sensibles
- faire echouer proprement les probes critiques au lieu de laisser un faux vert de type `status printed = healthy`
- durcir `config validate / configure / backup-recovery` comme chaine de fiabilite coherente
- modulariser davantage le lifecycle provider: onboarding, discovery, model-picker et post-selection hooks

### Criteres d'acceptation

- le systeme sait dire ce qui est configure, sain, degrade ou absent avant execution
- le controle operateur ne depend plus de suppositions implicites
- le debug runtime a une vue agregee au lieu de signaux disperses
- une config invalide, un provider incomplet ou une sonde critique manquante echouent avec un diagnostic actionnable

### Preuves obtenues a ce stade

- `src/project_os_core/runtime_registry.py` construit maintenant un rapport local `runtime_registry` avec checks `bootstrap_preflight / desktop_surface / discord_surface / model_stack / research_surface / provider_registry`, findings, fixes, `operator_views`, `operator_handoff` et `onboarding_guide`
- `src/project_os_core/paths.py` garde maintenant un artefact durable `runtime/health/latest_runtime_registry.json`
- `src/project_os_core/control_intents.py` et `src/project_os_core/session/state.py` servent maintenant de vraies primitives `preflight_request` et `onboarding_request`, a la fois en formes explicites (`/preflight`, `/onboard`, `/setup`) et naturelles
- `src/project_os_core/gateway/context_builder.py` classe maintenant ces controles comme surfaces runtime deteministes, leur attribue des vues desktop canoniques (`Overview / Agent / Config / Settings / Discord`) et publie `runtime_registry_status`
- `src/project_os_core/gateway/service.py` execute maintenant `preflight`, `onboard` et `status` sur le meme `runtime registry`, produit des resumes operateur actionnables et porte `runtime_registry_status` dans les metadonnees `truth-first`
- `src/project_os_core/desktop/control_room.py` expose maintenant `runtime_registry`, une truth card dediee, un startup check et l'action `refresh_runtime_registry` dans `Project OS.exe`
- `src/project_os_core/project_review.py` integre maintenant `runtime_registry` dans `review status`, les findings, les sources et l'escalade founder review
- les tests couvrent maintenant les commandes explicites et naturelles `preflight/onboarding`, le payload desktop `runtime_registry` et la presence de la section `Runtime Registry` dans le rapport review

### Ce qui reste volontairement hors de ce pack

- le vrai lifecycle provider modulaire complet `onboarding / discovery / model-picker / post-selection hooks`
- un registre host plus profond des credentials et secrets comparables a `NemoClaw`
- les surfaces `connect / logs` plus larges et un `provider discovery` plus muscle

## Pack 9 - Compaction, Persistent Queue, Digest, And Importance Memory

### Objet

Arreter de traiter la memoire et la compaction comme un detail annexe.

### Decision

`ADAPT`

### Etat

- `COEUR_LIVRE_LE_2026-03-17`
- `QUEUE_BACKEND_DEDIE_ENCORE_A_FAIRE`

### Ce qu'on prend

- compaction comme primitive de controle
- queue persistante optionnelle et lanes qui survivent au restart
- queue modes explicites et survives au restart quand ils font partie de la politique runtime
- digest cross-session non bloquant
- capture d'importance de session en arriere-plan
- mecanismes d'orchestration qui peuvent reporter proprement un follow-up au tour suivant

### Ce qu'on adapte

- pas de gros wiki magique ni de memoire opaque
- une couche legere, verifiable, reliee au `founder_session_spine`

### Travaux

- introduire une vraie primitive `compact`
- definir une strategie `memory / persistent` pour la queue et les runs critiques
- exposer l'etat `queue mode / depth / debounce / cap / drop policy` dans le statut et les truth cards quand la surface le permet
- definir un protocole de recovery apres restart pour le travail interrompu et les cartes/replies obsoletes
- gerer la continuite post-compaction et les nested lanes sans deadlocks ni duplication de run
- etudier un equivalent produit a `sessions_yield` pour l'orchestration differree sans bricolage de thread
- definir des hooks de digest non bloquants
- definir une capture `important sessions / decisions / open items`
- relier ces artefacts au spine de session et aux truth cards desktop

### Preuves obtenues a ce stade

- `src/project_os_core/session_continuity.py` construit maintenant un rapport durable `session_continuity` avec `queue_runtime`, `recoveries`, `compact_history`, `continuity_digest`, `importance_memory`, `operator_views` et `operator_handoff`
- `src/project_os_core/paths.py` garde maintenant un artefact durable `runtime/health/latest_session_continuity.json`
- `src/project_os_core/session_continuity.py` republie un digest stable et une importance de session directement dans `thread_ledgers.metadata_json` via `session_digest`, `session_importance`, `continuity_recovery_ready` et `continuity_stale_recovery`
- `src/project_os_core/gateway/service.py` reconstruit maintenant la continuite de session sur `status` et `/compact`, publie `session_continuity_status` dans les metadonnees `truth-first` et rend la compaction lisible cote operateur
- `src/project_os_core/desktop/control_room.py` expose maintenant `session_continuity`, une truth card dediee, un startup check et l'action `refresh_session_continuity` dans `Project OS.exe`
- `src/project_os_core/project_review.py` integre maintenant `session_continuity` dans `review status`, les findings, les sources et la synthese markdown
- les tests couvrent maintenant le module dedie `session_continuity`, la propagation gateway, le payload desktop et la section `Session Continuity` du review loop

### Ce qui reste volontairement hors de ce pack

- un vrai backend de queue persistant et generalise facon `openclaw-cn`
- un protocole de recovery actif qui rejoue des runs metier hors du perimetre `thread_ledgers / bindings`
- un equivalent plus profond a `sessions_yield` pour l'orchestration differree multi-lane
- des hooks memoire cross-session non limites au spine `thread_ledgers`

### Criteres d'acceptation

- la compaction est pilotable proprement et ne depend pas d'une phrase magique
- un restart ne fait pas perdre silencieusement le travail critique et ne raconte pas de faux etats a l'utilisateur
- les recoveries sont visibles, bornees et rattachees a une evidence runtime
- le systeme garde une memoire cross-session legere et utile
- les decisions et sujets importants ne dependent plus d'un simple historique de thread

## Pack 10 - Review Loop And Noise Sweep

### Objet

Nettoyer les doublons et faire remonter les collisions structurelles plutot que d'empiler des patches.

### Decision

`KEEP`

### Travaux

- garder `project_review.py` comme point d'entree unique
- signaler les collisions docs actives
- signaler les generated/vendor/binaries non canoniques
- garder un seul document actif par sujet
- marquer les docs redondantes `SUPERSEDED BY ...`

### Preuves obtenues a ce stade

- `src/project_os_core/docs_audit.py` impose maintenant une gouvernance minimale des roadmaps actives: statut/decision explicite ou marquage historique/superseded
- `src/project_os_core/project_review.py` remonte maintenant les roadmaps non canonisees comme `Roadmap governance gap`, en plus des artefacts generated et collisions docs
- `docs/roadmap/NEXT_CONVERSATION_HANDOFF.md` et `docs/roadmap/MINI_ROADMAP_PATCH_2026-03-14.md` sont maintenant explicitement marques `Document historique` avec `SUPERSEDED BY`
- `docs/roadmap/DISCORD_AUTONOMY_NO_LOSS_PLAN.md` porte maintenant un vrai marqueur de statut canonique
- les tests couvrent maintenant `docs_audit` et `project_review` sur les ecarts de gouvernance roadmap

### Ce qui reste volontairement hors de ce pack

- la suppression physique des artefacts generated quand ils sont verrouilles par le runtime local
- le traitement des sujets hors review loop deja remontes par le rapport global (`debug_system`, audit live Discord, runtime registry`)

### Criteres d'acceptation

- plus de roadmap concurrente pour le meme sujet
- les rapports de review remontent le bruit repo et les collisions docs
- les futures corrections ne se cachent plus derriere un harness vert mais faux

## Ordre d'implementation

1. `Pack 0 - Consolidate Existing Truth-First Spine`
2. `Pack 1 - Deterministic Conversation And Control Sessions`
3. `Pack 2 - Soft Control Surfaces For Discord`
4. `Pack 3 - Repo Grounding And Truth Propagation`
5. `Pack 4 - Model Health And Routing Discipline`
6. `Pack 5 - Execution Evidence Contract`
7. `Pack 6 - Desktop Truth Cards And Operator Handoff`
8. `Pack 7 - Approvals, Privacy Guard, And Policy-Backed Boundaries`
9. `Pack 8 - Onboarding, Preflight, And Runtime Registry`
10. `Pack 9 - Compaction, Persistent Queue, Digest, And Importance Memory`
11. `Pack 10 - Review Loop And Noise Sweep`

## Pourquoi cet ordre

- on consolide d'abord la colonne vertebrale de verite deja presente
- on separe ensuite proprement conversation et controle
- on ajoute ensuite des surfaces explicites, mais sans casser l'UX discussionnelle
- on verrouille ensuite la verite repo et la verite des claims
- on remet ensuite le health/routing modele au bon niveau
- on rend ensuite le desktop plus fort comme control plane local
- on n'attaque la couche approvals/privacy/policy-backed qu'apres avoir clarifie les primitives
- on ajoute ensuite le preflight et le registre runtime operateur
- on ajoute ensuite la discipline de queue persistante, recovery, compaction et memoire cross-session
- on termine par le sweep structurel pour eviter le retour des doublons

## Criteres globaux de succes

On pourra dire que ce plan est bon si:

- `Discord` reste naturel en usage normal
- les commandes explicites existent mais ne deviennent pas la seule facon de piloter le systeme
- `Project OS` cesse d'inventer des fichiers, des ecrans ou des completions
- les actions de controle sont deterministes sous le capot
- `Project OS.exe` devient une vraie surface de verite operatoire
- le niveau de discipline se rapproche d'`OpenClaw` et de `NemoClaw` sans copier leur produit a l'identique

## References

- `docs/workflow/DEEP_RESEARCH_PROTOCOL.md`
- `docs/roadmap/BUILD_STATUS_CHECKLIST.md`
- `docs/integrations/OPENCLAW_GATEWAY_ADAPTER.md`
- `docs/architecture/WINDOWS_FIRST_HOST_AND_WSL_FABRIC.md`
- `E:/ProjectOSArchive/external_audit/openclaw`
- `E:/ProjectOSArchive/external_audit/nemoclaw`
