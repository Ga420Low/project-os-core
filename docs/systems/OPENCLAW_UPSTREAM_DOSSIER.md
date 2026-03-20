# OpenClaw Upstream Dossier

## Statut

- `draft`
- `grounded_in_code`
- `research_profile=repo_comparison`
- `research_intensity=extreme`
- reevalue le `2026-03-17` apres lecture code-level de l'upstream, de `NemoClaw` et de plusieurs forks

## But

- garder une base durable des findings `OpenClaw / NemoClaw / forks`
- eviter de reperdre l'analyse a chaque compact de contexte
- classer ce qui doit etre `KEEP / ADAPT / DEFER / REJECT` pour `Project OS`

## Reponse courte

`Project OS` peut depasser `OpenClaw` sur le produit `Discord + desktop + founder workflow`, mais pas si on continue a compenser les trous runtime par du prompt et des tests de phrase.

Le vrai ecart aujourd'hui:

- `OpenClaw` est plus mature sur la discipline `session / control surface / command gating / compaction`
- `NemoClaw` est plus mature sur `host control plane / preflight / registry / policy-backed runtime`
- certains forks sont meilleurs que nous sur:
  - routage modele et fallback (`LocalClaw`)
  - action gating et privacy (`EdgeClaw`, `openclaw-cn`)
  - discover/inspect/call et memoire cross-session (`QVerisBot`)
  - onboarding/provider discovery et visibilite compaction (`DenchClaw`)

La bonne strategie n'est pas `copier 80% du code`.
La bonne strategie est:

- reprendre leurs primitives de rigueur
- les adapter a `Project OS`
- garder notre produit `discussion-first`

Corollaire important:

- `OpenClaw` est assez bon pour servir de vraie fondation
- si nous voulons sauver des petits morceaux utiles de `Project OS`, il est souvent plus propre de les recreer au-dessus de cette fondation que de les merger brutalement dans le coeur upstream
- la question correcte n'est donc pas `comment tout fusionner`
- la question correcte est `quelles capacites metier merite-t-on de reconstituer proprement sur une base plus saine`

## Gaps confirmes dans le code Project OS actuel

Les deux trous prioritaires initiaux confirmes par lecture du repo etaient:

- les chemins `clarification_required` et une partie des `approval_required` ne republient pas encore tout le noyau `truth-first`
  - voir `src/project_os_core/gateway/service.py`
- `project_review.py` publie bien un report utile, mais sa partie `upstream/fork snapshot` reste plus statique que le niveau de detail du dossier local
  - voir `src/project_os_core/project_review.py`

Etat apres implementation `Pack 0` le `2026-03-17`:

- ces deux trous sont maintenant fermes dans le code
- la priorite ne porte plus sur la consolidation du noyau `truth-first`
- la priorite porte maintenant sur les primitives runtime manquantes qui rapprochent vraiment `Project OS` du niveau `OpenClaw/NemoClaw`

Etat apres implementation `Pack 1` le `2026-03-17`:

- le coeur `conversation session / control session / control target session` existe maintenant pour `status` et `mode`
- les `queue modes` sont calcules de facon deterministe et persists dans le noyau runtime
- le ledger garde maintenant une trace `control_action` separee des actions de discussion
- la cible de delivery est persistee dans les bindings et ledgers de thread
- en revanche, le parser pre-modele complet, le retrait des directives du prompt et les primitives `new / reset / compact / usage` restent du ressort du lot suivant

Etat apres implementation `Pack 2` le `2026-03-17`:

- le parser pre-modele existe maintenant pour les surfaces `status / mode / recherche / debug / where / compact / usage / new / reset`
- les controles qui enchainent ensuite sur une discussion libre (`mode`, `compact`, `new`, `reset`) retirent bien leur directive du prompt final
- `deep research` garde son flow existant et `/recherche` le reutilise sans branche parallele
- `/debug` est gate cote operateur
- `/where` renvoie uniquement les vues canoniques du desktop
- `/compact`, `/new`, `/reset` et `/usage` sont maintenant de vraies primitives runtime, testees au niveau gateway
- on reste encore en dessous d'`OpenClaw` sur le command gating strict type `useAccessGroups` et en dessous des forks UI/channel sur les surfaces interactives riches

Mais l'ecart restant ne se limite pas a ces deux points.
Les themes structurels encore sous-armes chez nous etaient aussi:

- pairing / approvals / allowlists pas encore traites comme primitives runtime first-class
- audit d'exposition et de surface pas encore assez riche pour dire proprement ce qui est ouvert, bloque, dangereux ou mal borne
- queue persistante, recovery apres restart et continuite de compaction encore en dessous du niveau vu dans `openclaw-cn`, meme si un premier spine `session_continuity` relie maintenant compaction, digest, importance et recovery metadata
- visibilite des outils de session et des outils sensibles pas encore gouvernee par une policy aussi explicite que dans les meilleurs forks
- continuite de routage `lastAccountId / lastThreadId` et resets propres pas encore assez explicitement traites
- discipline `provider/plugin architecture + provider-owned onboarding/discovery/model-picker` pas encore formalisee chez nous
- validation config / preflight / backup/recovery pas encore pensee comme une chaine de fiabilite unique

Consequence:

- `Pack 0`, `Pack 1`, `Pack 2` et `Pack 3` sont fermes sur leur coeur runtime
- le prochain ecart reel porte maintenant sur `model health / routing discipline`, puis sur le gating/policy plus dur

Etat apres implementation `Pack 4` le `2026-03-17`:

- `Project OS` expose maintenant un vrai snapshot `model health / routing / fallback`, lisible dans le gateway et dans `Project OS.exe`
- les status Discord et les truth cards desktop savent dire quel provider est actif, quel fallback est enclenche et quelle policy de timeout l'explique
- l'ecart principal ne porte donc plus sur la lisibilite du routage, mais sur le contrat `execution evidence`

Etat apres implementation `Pack 5` le `2026-03-17`:

- le contrat `ack / prepare / handoff / execution_pending / completed_with_evidence` est maintenant centralise dans `src/project_os_core/gateway/execution_evidence.py`
- un `ack` n'est plus degrade silencieusement en `execution_pending`
- les nouvelles directives d'ecriture ne reusent plus une ancienne preuve terminee
- les follow-ups `?` et `c'est fait ?` restent bloques sur `pending` sans preuve et repondent `oui` seulement quand la completion est verifiee dans le fil
- les approvals runtime et `deep research` portent maintenant des refs canoniques sur leur evidence
- les reponses inline d'escalade reasoning publient une completion verifiee, enrichie ensuite avec `reply_id` et artefacts eventuels

Etat apres implementation `Pack 6` le `2026-03-17`:

- `Project OS.exe` lit maintenant un `operator_handoff` canonique depuis `gateway_dispatch_results` et `thread_ledgers`
- le desktop n'invente plus son detail operatoire: il expose `control_intent`, `queue_mode`, `delivery_target_ref`, `execution_evidence` et les vues du handoff depuis les metadonnees `truth-first`
- les `truth_cards` desktop couvrent maintenant aussi `Execution Evidence` et `Operator Handoff`
- la `command palette` desktop est maintenant servie par le payload runtime et ne lance que des vues canoniques ou des actions supportees
- la vue `Session` porte explicitement le handoff operatoire et les vues ciblees, au lieu de s'en remettre a une interpretation implicite du renderer

Etat apres implementation `Pack 7` le `2026-03-17`:

- `Project OS` expose maintenant une premiere couche policy-backed reelle: `privacy_guard`, approvals bornees, `security_request`, `security_boundaries` et trust audit OpenClaw relu dans le review loop
- les approvals runtime expirent maintenant automatiquement, restent lisibles dans l'etat de session et se resolvent sans ecraser leurs metadonnees
- le gateway sert maintenant une boucle operateur `security audit` de type `audit / deep / fix`, gatee cote controle et rattachee a une evidence canonique
- `Project OS.exe` expose `security_boundaries` dans `Overview / Config / Settings`, avec une action reelle `refresh_security_audit`
- `project_review.py` integre maintenant `security_boundaries` dans le statut global, les founder review items et le rapport markdown
- le vrai ecart ne porte donc plus sur l'absence totale de policies/approvals, mais sur le preflight/registry plus large, la generalisation du pairing et le durcissement de la visibilite des outils sensibles

Etat apres implementation `Pack 8` le `2026-03-17`:

- `Project OS` expose maintenant un vrai `runtime_registry` local, durable et relu par le gateway, le desktop et `review status`
- les controles `/preflight`, `/onboard` et `/setup` existent maintenant comme primitives runtime, en formes explicites et naturelles
- `status_request` re-utilise maintenant le meme registre operateur pour expliquer `Discord / desktop / models / research / providers`
- `Project OS.exe` expose `runtime_registry`, une truth card dediee, un startup check et l'action `refresh_runtime_registry`
- `project_review.py` remonte maintenant `runtime_registry` dans le rapport markdown, les sources et l'escalade founder review
- le vrai ecart ne porte donc plus sur l'absence de preflight/registry, mais sur le registre provider plus profond, le lifecycle modulaire `provider discovery` et les surfaces host plus larges type `connect / logs`

Consequence mise a jour:

- `Pack 0`, `Pack 1`, `Pack 2`, `Pack 3`, `Pack 4`, `Pack 5`, `Pack 6`, `Pack 7` et `Pack 8` sont fermes sur leur coeur
- l'ecart principal se deplace maintenant vers le registre provider plus profond, le pairing plus large, la visibilite des outils sensibles et la resilience longue duree

## Miroirs locaux audites

Repos audites localement sur `E:`

- `E:/ProjectOSArchive/external_audit/openclaw` -> `cc88b4a72` -> `2026-03-16 Commands: add /plugins chat command (#48765)`
- `E:/ProjectOSArchive/external_audit/nemoclaw` -> `df47f67d7` -> `2026-03-17 Don't log the dashboard URL (#112)`
- `E:/ProjectOSArchive/external_audit/forks/localclaw` -> `10fa0e926` -> `2026-02-20 README: add prominent install section with bootstrap script + update Jira docs to PAT-first`
- `E:/ProjectOSArchive/external_audit/forks/edgeclaw` -> `904778cc4` -> `2026-03-05 perf: skip duplicate resolve_model call from reply pipeline.`
- `E:/ProjectOSArchive/external_audit/forks/qverisbot` -> `bed349b98` -> `2026-03-15 Merge pull request #107 from QVerisAI/sync/upstream-2026-03-14`
- `E:/ProjectOSArchive/external_audit/forks/denchclaw` -> `3cd51759d` -> `2026-03-15 DOC: feat(cli): enhance daemonless mode support for container/cloud environments`
- `E:/ProjectOSArchive/external_audit/forks/openclaw-cn` -> `157a6f828` -> `2026-03-14 chore: track upstream v2026.3.13`

## Ce que le code upstream montre vraiment

### 1. OpenClaw n'est pas "juste un bon chat"

Les primitives fortes viennent du code, pas seulement des docs.

Ce qui est reel:

- directives et shortcuts traites avant le modele
  - `E:/ProjectOSArchive/external_audit/openclaw/docs/concepts/context.md`
  - `E:/ProjectOSArchive/external_audit/openclaw/src/auto-reply/reply.raw-body.test.ts`
- modes de queue explicites quand une run est deja active:
  - `interrupt`
  - `steer`
  - `followup`
  - `collect`
  - avec backlog variants et statut lisible
  - voir:
    - `E:/ProjectOSArchive/external_audit/openclaw/docs/concepts/messages.md`
    - `E:/ProjectOSArchive/external_audit/openclaw/docs/concepts/agent-loop.md`
    - `E:/ProjectOSArchive/external_audit/openclaw/src/auto-reply/status.test.ts`
    - `E:/ProjectOSArchive/external_audit/openclaw/src/auto-reply/reply.directive.parse.test.ts`
- command gating explicite pour les controles texte
  - `E:/ProjectOSArchive/external_audit/openclaw/src/channels/command-gating.ts`
- sessions de commande separees des sessions conversationnelles tout en gardant la session cible
  - `E:/ProjectOSArchive/external_audit/openclaw/docs/channels/discord.md`
  - `E:/ProjectOSArchive/external_audit/openclaw/src/auto-reply/templating.ts`
- pairing DM, allowlists et `doctor` securite comme defaults produits verifiables
  - `E:/ProjectOSArchive/external_audit/openclaw/README.md`
- compaction, new/reset et hygiene de session exposes comme primitives de controle
  - `E:/ProjectOSArchive/external_audit/openclaw/src/auto-reply/status.ts`
- runtime controls first-class (`session/status`, `session/set_mode`, `session/set_config_option`)
  - `E:/ProjectOSArchive/external_audit/openclaw/src/acp/control-plane/manager.runtime-controls.ts`
  - `E:/ProjectOSArchive/external_audit/openclaw/src/acp/runtime/types.ts`
- meme le `chat.send` injecte proprement les hints de thinking sans laisser le modele improviser leur interpretation
  - `E:/ProjectOSArchive/external_audit/openclaw/src/gateway/server-methods/chat.ts`

Conclusion:

- la robustesse vient d'un pipeline `parse -> gate -> route -> tool/control`
- pas d'un prompt plus long

### 2. NemoClaw ajoute un vrai host control plane

Ce que le code apporte reellement:

- onboarding guide avec preflight et health verification
  - `E:/ProjectOSArchive/external_audit/nemoclaw/bin/lib/preflight.js`
  - `E:/ProjectOSArchive/external_audit/nemoclaw/bin/lib/onboard.js`
- registre local durable des sandboxes et permissions strictes
  - `E:/ProjectOSArchive/external_audit/nemoclaw/bin/lib/registry.js`
  - `E:/ProjectOSArchive/external_audit/nemoclaw/bin/lib/credentials.js`
- policies appliquees par preset, pas par prose
  - `E:/ProjectOSArchive/external_audit/nemoclaw/bin/lib/policies.js`
  - `E:/ProjectOSArchive/external_audit/nemoclaw/nemoclaw-blueprint/policies/presets/discord.yaml`
- `status` agrege a partir d'un vrai `statusData` runtime
  - `E:/ProjectOSArchive/external_audit/nemoclaw/nemoclaw/src/commands/status.ts`
- `connect / status / logs` sont des surfaces host, pas juste des reponses conversationnelles
  - `E:/ProjectOSArchive/external_audit/nemoclaw/bin/nemoclaw.js`
  - `E:/ProjectOSArchive/external_audit/nemoclaw/nemoclaw/src/cli.ts`
- approvals reseau operateur dans la TUI, avec details host/port/binary et effet borne a la session
  - `E:/ProjectOSArchive/external_audit/nemoclaw/docs/network-policy/approve-network-requests.md`

Conclusion:

- `NemoClaw` ne nous donne pas un meilleur bot
- `NemoClaw` nous montre comment industrialiser `status / preflight / registry / policy`

### 3. Les forks utiles ont de vraies idees, pas juste du branding

#### LocalClaw

Ce qu'on recupere conceptuellement:

- onboarding en `model strategy presets`
  - `balanced`
  - `local-only`
  - `all-api`
  - voir `E:/ProjectOSArchive/external_audit/forks/localclaw/src/wizard/onboarding.model-strategy.ts`
- timeouts et fallback propres selon la disponibilite d'un orchestrateur API
  - `E:/ProjectOSArchive/external_audit/forks/localclaw/src/agents/timeout.ts`
- `status` plus riche avec audit securite, usage snapshot, gateway reachability et memory state
  - `E:/ProjectOSArchive/external_audit/forks/localclaw/src/commands/status.command.ts`
- audit securite avec matrice d'exposition, risques petits modeles, plugins non allowlistes et surfaces web/sandbox
  - `E:/ProjectOSArchive/external_audit/forks/localclaw/src/security/audit.ts`
  - `E:/ProjectOSArchive/external_audit/forks/localclaw/src/security/audit-extra.ts`

#### EdgeClaw

Ce qu'on recupere conceptuellement:

- `createActionGate` applique a de vraies actions channel/tool
  - `E:/ProjectOSArchive/external_audit/forks/edgeclaw/src/agents/tools/slack-actions.ts`
  - `E:/ProjectOSArchive/external_audit/forks/edgeclaw/src/agents/tools/telegram-actions.ts`
- privacy/routing sensible comme chaine `detect -> classify -> action`

#### QVerisBot

Ce qu'on recupere conceptuellement:

- `discover -> inspect -> call` comme contrat explicite pour les integrations externes
  - `E:/ProjectOSArchive/external_audit/forks/qverisbot/src/agents/system-prompt.ts`
  - `E:/ProjectOSArchive/external_audit/forks/qverisbot/src/agents/tools/qveris-tools.ts`
- memoire cross-session non bloquante:
  - digest roulant
  - classification d'importance
  - voir:
    - `E:/ProjectOSArchive/external_audit/forks/qverisbot/src/hooks/bundled/context-digest/handler.ts`
    - `E:/ProjectOSArchive/external_audit/forks/qverisbot/src/hooks/bundled/session-importance/handler.ts`
- providers modularises avec onboarding/discovery/model-picker/post-selection hooks
  - `E:/ProjectOSArchive/external_audit/forks/qverisbot/CHANGELOG.md`
- orchestration `sessions_yield` pour laisser vivre un follow-up cache sur le tour suivant
  - `E:/ProjectOSArchive/external_audit/forks/qverisbot/CHANGELOG.md`
- continuites runtime utiles:
  - preservation de `lastAccountId` / `lastThreadId` apres `/reset`
  - `gateway status --require-rpc`
  - backup qui bypass proprement le preflight normal en mode recovery
  - voir:
    - `E:/ProjectOSArchive/external_audit/forks/qverisbot/CHANGELOG.md`
    - `E:/ProjectOSArchive/external_audit/forks/qverisbot/docs/cli/backup.md`
    - `E:/ProjectOSArchive/external_audit/forks/qverisbot/docs/cli/configure.md`

#### DenchClaw

Ce qu'on recupere conceptuellement:

- onboarding/provider discovery injectable dans le produit, pas juste dans la CLI
  - `E:/ProjectOSArchive/external_audit/forks/denchclaw/extensions/dench-ai-gateway/index.ts`
- surfacer la compaction comme evenement visible de run et pas comme detail opaque
  - `E:/ProjectOSArchive/external_audit/forks/denchclaw/apps/web/lib/active-runs.ts`

#### openclaw-cn

Ce qu'on recupere conceptuellement:

- action gating reutilisable jusque dans les actions Discord
  - `E:/ProjectOSArchive/external_audit/forks/openclaw-cn/src/agents/tools/common.ts`
  - `E:/ProjectOSArchive/external_audit/forks/openclaw-cn/src/agents/tools/discord-actions.ts`
- restriction de visibilite des outils de session quand on est dans une session sandboxee
  - `E:/ProjectOSArchive/external_audit/forks/openclaw-cn/src/agents/tools/sessions-history-tool.ts`
- forte attention a:
  - compaction/recovery
  - queue persistante SQLite et recovery apres restart
  - approbations `/approve`
  - policies par groupe/canal
  - securite sandbox/browser
  - audit d'exposition et de surface
  - visible dans:
    - `E:/ProjectOSArchive/external_audit/forks/openclaw-cn/CHANGELOG.md`
    - `E:/ProjectOSArchive/external_audit/forks/openclaw-cn/src/process/queue-backend.ts`
    - `E:/ProjectOSArchive/external_audit/forks/openclaw-cn/src/agents/handlers.ts`
    - `E:/ProjectOSArchive/external_audit/forks/openclaw-cn/src/security/audit.ts`

## Classement pour Project OS

## A faire

### 1. Separation conversation / control avec parser pre-modele

Etat:

- `COEUR_LIVRE_LE_2026-03-17`
- `PARSER_PRE_MODELE_LIVRE_SUR_LES_SURFACES_PACK_2`
- `COMMAND_GATING_STRICT_ENCORE_A_FAIRE`

Pourquoi il compte:

- c'est la base qui manque pour sortir du bricolage lexical
- c'est le prerequis pour garder `Discord` naturel tout en etant deterministe

Ce qu'on recupere:

- extraction des directives et shortcuts avant le modele
- `control session` separee de la `conversation session`
- gating deterministe des commandes de controle

Ce qu'on n'importe pas:

- UX slash-first obligatoire
- duplication de threads pour imiter l'upstream

Preuves a obtenir:

- un message naturel et sa forme commande resolvent exactement la meme primitive
- les directives resolues ne sont plus visibles dans le prompt final
- un emetteur non autorise ne peut pas declencher un controle sensible

Preuves obtenues a ce stade:

- `mets toi en mode avance` et `/mode avance` resolvent `set_discussion_mode`
- `ou j'en suis` et `/status` resolvent `status_request`
- `/recherche` rejoint le flow deep research existant sans branche parallele
- `/where` et les demandes naturelles de detail operatoire renvoient les vues desktop canoniques
- `/compact`, `/new`, `/reset` et `/usage` existent comme primitives runtime reelles
- les directives resolues pour `mode / compact / new / reset` ne fuitent plus dans le prompt libre
- le runtime publie `conversation_session_key`, `control_session_key`, `control_target_session_key`, `queue_mode`, `queue_mode_reason`, `delivery_target_ref`
- le thread ledger persiste un evenement `control_action`

References locales:

- `src/project_os_core/control_intents.py`
- `src/project_os_core/session/state.py`
- `src/project_os_core/gateway/context_builder.py`
- `src/project_os_core/gateway/service.py`
- `src/project_os_core/gateway/stateful.py`
- `tests/unit/test_session_state.py`
- `tests/unit/test_gateway_and_orchestration.py`

Ou ca entre dans Project OS:

- `src/project_os_core/gateway/context_builder.py`
- `src/project_os_core/gateway/service.py`
- `src/project_os_core/operator_visibility_policy.py`

Sources primaires:

- `E:/ProjectOSArchive/external_audit/openclaw/docs/concepts/context.md`
- `E:/ProjectOSArchive/external_audit/openclaw/src/channels/command-gating.ts`
- `E:/ProjectOSArchive/external_audit/openclaw/src/gateway/server-methods/chat.ts`

### 2. Repo grounding, truth propagation et no-fake-completion

Etat:

- `COEUR_LIVRE`

Pourquoi il compte:

- c'est le trou qui produit les fichiers/ecrans inventes et les faux `c'est fait`

Ce qu'on recupere:

- tool/control-first
- evidence-backed status
- `discover -> inspect -> call`

Ce qu'on n'importe pas:

- un prompt encore plus long
- des tests phrase-par-phrase comme solution principale

Preuves a obtenir:

- aucune citation repo sans hit verifie
- aucune completion sans evidence
- aucune capacite externe promise sans inspection

Ou ca entre dans Project OS:

- `src/project_os_core/gateway/service.py`
- `src/project_os_core/gateway/context_builder.py`
- `src/project_os_core/gateway/repo_grounding.py`
- `tests/unit/test_gateway_and_orchestration.py`
- `tests/unit/test_gateway_context_builder.py`
- `tests/unit/test_gateway_prompt_ops.py`

Sources primaires:

- `E:/ProjectOSArchive/external_audit/openclaw/src/agents/system-prompt.ts`
- `E:/ProjectOSArchive/external_audit/forks/qverisbot/src/agents/system-prompt.ts`
- `E:/ProjectOSArchive/external_audit/forks/qverisbot/src/agents/tools/qveris-tools.ts`

Ce qui est maintenant livre chez nous:

- grounding repo local deterministe avant citation
- reponse Discord `repo diagnosis` deterministe quand le runtime a deja une reponse verifiee
- post-check des reponses inline pour rejeter les references repo non verifiees
- propagation de `repo_grounding_summary` / `repo_grounding_count` dans le noyau verite, y compris les `session_reply`
- correction d'une vraie faille lexicale: `repo` n'est plus detecte a l'interieur de `reponse`

Ce qui reste volontairement hors de ce pack:

- un vrai `discover -> inspect -> call` multi-capabilities pour les integrations externes
- une inspection de schema/tool availability generalisee avant appel specialise

### 3. Model health, routing discipline et fallback lisible

Etat:

- `COEUR_LIVRE`

Pourquoi il compte:

- on ne peut pas expliquer proprement les fallback, degradations et couts sans cette couche

Ce qu'on recupere:

- status multi-source
- budgets de timeout
- fallback policy lisible
- strategy presets / tiers modeles

Ce qu'on n'importe pas:

- toute l'UX `LocalClaw`
- son produit local-first en bloc

Preuves a obtenir:

- un `status` explique le tier actif, le fallback et la raison
- les timeouts ne sont plus implicites

Ce qui est maintenant livre chez nous:

- snapshot modele structure avec tiers `fast / local / api`, providers et budgets de timeout
- degradation locale explicite quand le modele local repond mais reste trop lent
- `routing_status` structure avec `selected_provider`, `active_provider`, `fallback_active`, `fallback_reason`, `timeout_policy`
- fallback inline borne et visible entre `anthropic`, `openai` et `local`, avec interdiction de fallback silencieux pour les chemins sensibles/forces
- `status_request` et `usage_request` remontent maintenant l'etat modele, le fallback et la policy de timeout
- le desktop expose `model_routing_runtime`, cartes `Modele / Routing` et truth card `Model Routing`

Ce qui reste volontairement hors de ce pack:

- un registre onboarding/preflight complet de la sante providers et du runtime host
- le cycle complet `discover -> inspect -> call` pour les outils externes
- la couche policy-backed type `NemoClaw/OpenShell`

Ou ca entre dans Project OS:

- `src/project_os_core/gateway/service.py`
- `src/project_os_core/config.py`
- `src/project_os_core/desktop/`

Sources primaires:

- `E:/ProjectOSArchive/external_audit/forks/localclaw/src/wizard/onboarding.model-strategy.ts`
- `E:/ProjectOSArchive/external_audit/forks/localclaw/src/agents/timeout.ts`
- `E:/ProjectOSArchive/external_audit/forks/localclaw/src/commands/status.command.ts`

### 4. Host-like control plane, preflight et runtime registry

Etat:

- `COEUR_LIVRE_LE_2026-03-17`

Pourquoi il compte:

- c'est la partie `NemoClaw` qui donne un vrai sentiment de securite et d'operabilite

Ce qu'on recupere:

- preflight
- status aggregate
- registre runtime durable
- connect/logs/status comme surfaces verifiees

Ce qu'on n'importe pas:

- `OpenShell`
- le packaging Linux-first

Preuves a obtenir:

- l'operateur sait avant execution ce qui est configure, sain, degrade ou absent
- les surfaces sensibles ont un statut local et durable

Preuves obtenues a ce stade:

- `src/project_os_core/runtime_registry.py` construit maintenant un rapport `runtime_registry` local avec checks `bootstrap_preflight / desktop_surface / discord_surface / model_stack / research_surface / provider_registry`, findings, fixes, `operator_views`, `operator_handoff` et `onboarding_guide`
- `src/project_os_core/paths.py` conserve maintenant ce rapport dans `runtime/health/latest_runtime_registry.json`
- `src/project_os_core/control_intents.py` et `src/project_os_core/session/state.py` portent maintenant `preflight_request` et `onboarding_request` comme primitives reelles
- `src/project_os_core/gateway/service.py` sert maintenant `preflight`, `onboarding` et `status` sur le meme registre runtime, avec `runtime_registry_status` dans les metadonnees `truth-first`
- `src/project_os_core/desktop/control_room.py` republie `runtime_registry`, un startup check dedie et l'action `refresh_runtime_registry` dans `Project OS.exe`
- `src/project_os_core/project_review.py` remonte maintenant `runtime_registry` dans `review status`, les findings et l'escalade founder review

Ce qui reste volontairement hors de ce theme:

- le lifecycle provider modulaire complet `onboarding / discovery / model-picker / post-selection hooks`
- un registre host plus profond des credentials et des secrets comparable a `NemoClaw`
- des surfaces `connect / logs` plus riches et une discovery provider plus muscle

Ou ca entre dans Project OS:

- `src/project_os_core/desktop/control_room.py`
- `src/project_os_core/desktop/truth_registry.py`
- `src/project_os_core/project_review.py`

Sources primaires:

- `E:/ProjectOSArchive/external_audit/nemoclaw/bin/lib/onboard.js`
- `E:/ProjectOSArchive/external_audit/nemoclaw/bin/lib/registry.js`
- `E:/ProjectOSArchive/external_audit/nemoclaw/nemoclaw/src/commands/status.ts`

### 5. Compaction, digest et memoire cross-session

Etat:

- `COEUR_LIVRE_LE_2026-03-17`
- `GENERALISATION_MEMOIRE_ENCORE_A_FAIRE`

Pourquoi il compte:

- le systeme ne doit pas dependre d'une fenetre de contexte fragile

Ce qu'on recupere:

- compaction comme primitive
- digest cross-session non bloquant
- classification d'importance

Ce qu'on n'importe pas:

- une memoire opaque impossible a verifier

Preuves a obtenir:

- la compaction est pilotable et lisible
- les decisions importantes survivent aux resets de conversation

Preuves obtenues a ce stade:

- `src/project_os_core/session_continuity.py` construit maintenant un rapport durable `session_continuity` avec `queue_runtime`, `recoveries`, `compact_history`, `continuity_digest` et `importance_memory`
- `src/project_os_core/session_continuity.py` persiste maintenant `session_digest` et `session_importance` dans `thread_ledgers.metadata_json`
- `src/project_os_core/gateway/service.py` republie `session_continuity_status` sur `status` et `/compact`
- `src/project_os_core/desktop/control_room.py` expose `session_continuity`, une truth card et l'action `refresh_session_continuity`
- `src/project_os_core/project_review.py` integre maintenant `session_continuity` dans le report global

Ou ca entre dans Project OS:

- `src/project_os_core/gateway/`
- `src/project_os_core/memory/`
- `src/project_os_core/desktop/`

Sources primaires:

- `E:/ProjectOSArchive/external_audit/openclaw/src/auto-reply/status.ts`
- `E:/ProjectOSArchive/external_audit/forks/qverisbot/src/hooks/bundled/context-digest/handler.ts`
- `E:/ProjectOSArchive/external_audit/forks/qverisbot/src/hooks/bundled/session-importance/handler.ts`
- `E:/ProjectOSArchive/external_audit/forks/denchclaw/apps/web/lib/active-runs.ts`

### 6. Approvals, pairing, allowlists et audit d'exposition

Etat:

- `COEUR_LIVRE_LE_2026-03-17`
- `GENERALISATION_CROSS_SURFACE_ENCORE_A_FAIRE`

Pourquoi il compte:

- un systeme n'est pas au niveau upstream s'il sait seulement "repondre mieux" mais pas dire exactement qui peut faire quoi, sur quelle surface, et pourquoi

Ce qu'on recupere:

- pairing DM et allowlists comme defaults produits
- approvals gerables et auditables
- matrice d'exposition et checks de policy
- visibilite restreinte des outils et sessions sensibles

Ce qu'on n'importe pas:

- une UX admin lourde
- des policies generalistes detachees du produit `Project OS`

Preuves a obtenir:

- les controles sensibles ne sont pas juste caches dans le prompt
- les surfaces exposees sont auditees et classables en `ok / warn / critical`
- les approvals et allowlists ont un stockage et une lecture runtime clairs

Preuves obtenues a ce stade:

- `src/project_os_core/runtime/store.py` expire maintenant les approvals runtime stale et conserve leurs metadonnees lors des resolutions
- `src/project_os_core/session/state.py` charge les approvals pendantes comme partie du snapshot de session au lieu de les laisser a l'etat SQL implicite
- `src/project_os_core/security_boundaries.py` construit un rapport local `security_boundaries` avec `privacy_guard`, `approval_boundary`, `control_surface`, `openclaw_trust_audit`, `exposure_matrix`, `operator_views` et `operator_handoff`
- `src/project_os_core/gateway/service.py` sert un `security_request` deterministic (`audit / deep / fix`), gate cette action cote controle et renvoie une completion `completed_with_evidence`
- `src/project_os_core/desktop/control_room.py` republie `security_boundaries` dans le payload, les truth cards et l'action `refresh_security_audit`
- `src/project_os_core/project_review.py` remonte maintenant `security_boundaries` dans le statut global et la synthese review

Ce qui reste volontairement hors de ce pack:

- une boucle de pairing/bootstrap token court-vivant pour toutes les surfaces operateur sensibles
- un durcissement plus large de la visibilite des outils de session hors du perimetre `security_request`
- des checks `deep/fix` plus vastes pour providers/plugins/surfaces encore non couverts

Ou ca entre dans Project OS:

- `src/project_os_core/gateway/service.py`
- `src/project_os_core/gateway/context_builder.py`
- `src/project_os_core/operator_visibility_policy.py`
- `src/project_os_core/project_review.py`

Sources primaires:

- `E:/ProjectOSArchive/external_audit/openclaw/README.md`
- `E:/ProjectOSArchive/external_audit/nemoclaw/docs/network-policy/approve-network-requests.md`
- `E:/ProjectOSArchive/external_audit/forks/qverisbot/docs/cli/approvals.md`
- `E:/ProjectOSArchive/external_audit/forks/localclaw/src/security/audit.ts`
- `E:/ProjectOSArchive/external_audit/forks/localclaw/src/security/audit-extra.ts`
- `E:/ProjectOSArchive/external_audit/forks/openclaw-cn/src/security/audit.ts`
- `E:/ProjectOSArchive/external_audit/forks/openclaw-cn/src/agents/tools/sessions-history-tool.ts`

### 7. Queue persistante, recovery restart et continuite de compaction

Etat:

- `SOCLE_CONTINUITE_LIVRE_LE_2026-03-17`
- `BACKEND_QUEUE_PERSISTANT_ENCORE_A_FAIRE`

Pourquoi il compte:

- la vraie robustesse apparait quand le service redemarre, compacte ou rejoue du travail interrompu sans raconter n'importe quoi a l'utilisateur

Ce qu'on recupere:

- backend de queue persistant selon le mode runtime
- recovery des taches en cours apres restart
- notification operateur propre pour les runs recuperes
- continuite post-compaction et nested lanes plus propres

Ce qu'on n'importe pas:

- une copie du backend `openclaw-cn`
- une dette SQLite si on n'en a pas besoin partout

Preuves a obtenir:

- un restart ne perd pas silencieusement le travail important
- les recoveries sont visibles, bornees et non mensongeres
- la compaction et le travail queue n'entrent pas en deadlock ou en duplication de run

Preuves obtenues a ce stade:

- `src/project_os_core/session_continuity.py` reconcilie maintenant `thread_ledgers`, `discord_thread_bindings` et `thread_ledger_events` pour rendre les recoveries visibles et classer les fils `recoverable / stale / missing_recovery_key`
- `src/project_os_core/session_continuity.py` derive un etat `queue_runtime` avec `depth`, `explicit_mode_count`, `recoverable_bindings` et `missing_recovery_count`
- `src/project_os_core/gateway/service.py` et `src/project_os_core/desktop/control_room.py` republient maintenant cette continuite au lieu de laisser la recovery implicite

Ce qui reste ouvert:

- un backend de queue persistant dedie
- un replay/recovery actif des runs metier au-dela des metadata de thread
- une orchestration differree de type `sessions_yield`

Ou ca entre dans Project OS:

- `src/project_os_core/gateway/`
- `src/project_os_core/runtime/`
- `src/project_os_core/desktop/`

Sources primaires:

- `E:/ProjectOSArchive/external_audit/forks/openclaw-cn/src/process/queue-backend.ts`
- `E:/ProjectOSArchive/external_audit/forks/openclaw-cn/src/agents/handlers.ts`
- `E:/ProjectOSArchive/external_audit/forks/openclaw-cn/CHANGELOG.md`
- `E:/ProjectOSArchive/external_audit/forks/qverisbot/CHANGELOG.md`

### 8. Continuite de routage, config validation et provider lifecycle

Etat:

- `A_FAIRE`

Pourquoi il compte:

- beaucoup de fiabilite upstream vient des details de cycle de vie: conserver la bonne cible de delivery apres reset, valider la config strictement, faire echouer proprement les probes et modulariser la couche provider

Ce qu'on recupere:

- preservation explicite de `lastAccountId / lastThreadId`
- `status` et probes qui savent fail hard
- validation config stricte avec garde-fous de setup
- backup-recovery qui reste utile meme quand la config est partiellement cassee
- providers possedant leur onboarding/discovery/model-picker/post-selection hooks

Ce qu'on n'importe pas:

- toute l'UX dashboard de l'upstream
- une pluginisation forcenee de chaque provider chez `Project OS`

Preuves a obtenir:

- un reset ou un reroutage ne casse pas silencieusement la cible de reply
- une config invalide ou incomplete echoue avec un diagnostic actionnable
- les providers critiques ont un lifecycle plus modulaire et moins colle a la logique centrale

Ou ca entre dans Project OS:

- `src/project_os_core/gateway/service.py`
- `src/project_os_core/gateway/context_builder.py`
- `src/project_os_core/config.py`
- `src/project_os_core/project_review.py`

Sources primaires:

- `E:/ProjectOSArchive/external_audit/forks/qverisbot/CHANGELOG.md`
- `E:/ProjectOSArchive/external_audit/forks/qverisbot/docs/cli/backup.md`
- `E:/ProjectOSArchive/external_audit/forks/qverisbot/docs/cli/configure.md`
- `E:/ProjectOSArchive/external_audit/forks/openclaw-cn/CHANGELOG.md`

## A etudier

- `DenchClaw` pour le couplage `web UI / onboarding / provider discovery`, mais seulement si on veut enrichir `Project OS.exe`
- `openclaw-cn` pour les details de policies `approve / group policy / sandbox visibility`, pas comme base produit

## A rejeter pour maintenant

- copier massivement le code `OpenClaw` ou `NemoClaw`
- reproduire `OpenShell`
- imposer une UX slash-first
- ouvrir un deuxieme control plane qui ferait concurrence a `Project OS.exe`

## Impact direct sur la roadmap

La feuille de route canonique a ete durcie ici:

- [OPENCLAW_REINFORCEMENT_PLAN.md](../roadmap/OPENCLAW_REINFORCEMENT_PLAN.md)

Les renforcements majeurs ajoutes apres lecture code-level:

- parser pre-modele et gating avant generation
- primitive `compact / new / reset / usage`
- `discover -> inspect -> call`
- `createActionGate` / policies d'autorisation de surface
- pairing / approvals / allowlists / exposure matrix
- `status` multi-source et timeouts/fallback lisibles
- preflight / registry / dashboard operatoire
- hooks `context digest` et `session importance`
- queue persistante, restart recovery et compaction continuity
- continuites de routing/reset, config validation et lifecycle provider
- gouvernance documentaire explicite et review loop capable de remonter les roadmaps non canonisees

## Lane preuve pour le prochain lot

Avant de dire qu'on a rattrape le niveau upstream, il faudra prouver:

- qu'un `status`, un `mode`, un `debug` et un `compact` naturels resolvent des primitives deterministes
- qu'aucune citation repo/ecran n'est possible sans grounding
- qu'aucune completion n'est possible sans evidence
- que `Project OS.exe` expose un vrai `status` operatoire agrege
- qu'on ne reperd plus les decisions importantes quand la conversation compacte

## Sources

- [DEEP_RESEARCH_PROTOCOL.md](../workflow/DEEP_RESEARCH_PROTOCOL.md)
- [OPENCLAW_REINFORCEMENT_PLAN.md](../roadmap/OPENCLAW_REINFORCEMENT_PLAN.md)
- `E:/ProjectOSArchive/external_audit/openclaw`
- `E:/ProjectOSArchive/external_audit/nemoclaw`
- `E:/ProjectOSArchive/external_audit/forks/localclaw`
- `E:/ProjectOSArchive/external_audit/forks/edgeclaw`
- `E:/ProjectOSArchive/external_audit/forks/qverisbot`
- `E:/ProjectOSArchive/external_audit/forks/denchclaw`
- `E:/ProjectOSArchive/external_audit/forks/openclaw-cn`
