# OpenClaw Reinforcement Plan

## Statut

Feuille de route canonique.

Ce document transforme la note temporaire `TEMP_OPENCLAW_UPSTREAM_FEATURE_PACKS_2026-03-15.md` en plan operatoire pour renforcer `OpenClaw` dans `Project OS`.

## But

Faire d'`OpenClaw` une facade operateur plus solide, plus visible et plus utile, sans lui laisser prendre la place du runtime canonique `Project OS`.

Le plan doit renforcer cinq choses:

- la verite live et la sante du gateway
- la frontiere de confiance et la securite plugin/auth
- l'ergonomie operateur `Discord`
- la qualite du routage modele et de la protection des contenus sensibles
- la capacite locale Windows-first pour les contenus `S3`

## Point de depart

Ce qui est deja acquis:

- gateway `OpenClaw` installe en tache planifiee Windows
- `openclaw doctor` vert
- `doctor --strict` vert
- secrets live sortis du snapshot runtime
- allowlist plugin explicite
- policy Discord live durcie
- replay et doctor locaux deja branches sur `Project OS`

Ce qui manque encore pour un renforcement complet:

- semantics de health Windows totalement stabilisees
- distinction documentaire propre entre preuve canonique runtime et preuve operateur Discord reelle
- un dernier run manuel utilisateur sur Discord si on veut une preuve humaine, pas seulement une preuve runtime

## Contraintes d'architecture

Regles dures:

- `Windows` reste la machine maitresse
- `OpenClaw` reste une facade et un gateway, jamais la verite canonique
- `Project OS` garde `runtime`, `memory`, `Mission Router`, `Guardian`, `ApprovalPolicy` et `evidence`
- aucune idee prise dans un fork ne doit introduire une deuxieme architecture concurrente
- aucune couche `WSL2` n'est un prerequis de ce plan

References:

- `docs/architecture/WINDOWS_FIRST_HOST_AND_WSL_FABRIC.md`
- `docs/integrations/OPENCLAW_GATEWAY_ADAPTER.md`
- `PROJECT_OS_MASTER_MACHINE.md`

## Sources d'inspiration

- upstream officiel `openclaw/openclaw`
- fork `sunkencity999/localclaw`
- fork `OpenBMB/EdgeClaw`

On ne copie pas ces projets.
On en extrait des patterns utiles et compatibles avec la frontiere `OpenClaw` vs `Project OS`.

## Ordre retenu

1. `Phase 0 - Truth And Health`
2. `Pack 1 - Plugin And Pairing Hardening`
3. `Pack 2 - Discord Operations UX`
4. `Pack 3 - Model Health And Routing`
5. `Pack 4 - Privacy Guard And Sensitive Routing`
6. `Pack 5 - Local Windows-First Inference Lane`

Pourquoi cet ordre:

- on verrouille d'abord la verite live
- on ferme ensuite les frontieres de confiance
- on ameliore ensuite le pilotage operateur
- on optimise ensuite le routage et la resilience modele
- on renforce ensuite la privacy et la memoire
- on termine par la vraie capacite locale Windows-first pour `S3`

## Phase 0 - Truth And Health

### Objet

Faire en sorte que `Project OS` sache dire si `OpenClaw` est vraiment sain, surtout sur Windows, sans se laisser tromper par les faux negatifs de la CLI.

### Source

Experience live du poste Windows + docs officielles `gateway` / `doctor` / `windows`.

### Ce qu'on garde

- `service.loaded = true`
- `port.status = busy`
- `rpc.ok = true`

### Ce qu'on adapte

- ne pas utiliser `service.runtime.status` seul comme source de verite sur Windows
- ne pas traiter un timeout de restart comme une panne finale si le listener et le RPC sont sains

### Travaux

- figer une semantics de sante Windows dans `Project OS`
- garder le script admin idempotent et strict
- ajouter une verification live `Discord` de bout en bout comme preuve finale du lot bootstrap
- rendre la post-installation reproductible et lisible pour un non-dev

### Criteres d'acceptation

- une machine Windows saine passe avec:
  - tache planifiee chargee
  - port occupe
  - RPC local joignable
  - pas de fallback `Startup`
- la doc ne dit nulle part que `runtime.status = unknown` vaut panne
- un run de verification post-install unique permet de conclure en moins de 5 minutes

### Non-buts

- patcher `OpenClaw` upstream pour supprimer son faux negatif Windows
- forker la CLI juste pour rendre l'affichage plus joli

## Pack 1 - Plugin And Pairing Hardening

### Objet

Rendre la frontiere `OpenClaw` plus dure contre les plugins trop ouverts, les secrets mal portes et les credentials partages.

### Sources

- docs officielles `plugins`
- changelog officiel `pairing`

### Decision

`KEEP`

### Contenu

- installs plugin bornees et explicites
- versions pinees
- `--ignore-scripts` quand la voie d'installation le permet
- allowlist plugin explicite
- tokens de bootstrap de pairing courts, jetables et jamais exposes dans un thread public

### Travaux

- durcir encore la doc d'installation et de mise a jour plugin
- figer un process de rotation / re-pairing
- verifier que les tokens de bootstrap courts ne sont jamais copies dans `Discord`
- garder les secrets vivants hors snapshot runtime

### Criteres d'acceptation

- aucun secret long terme en clair dans `runtime/openclaw/openclaw.json`
- aucun plugin hors allowlist ne peut etre considere "sain"
- le pairing n'utilise pas de secret durable poste en chat
- un audit local peut prouver le mode de trust sans lire le code du plugin

### Etat 2026-03-15

`IMPLEMENTE`

Preuves retenues:

- commande canonique `py D:/ProjectOS/project-os-core/scripts/project_os_entry.py --config-path D:/ProjectOS/project-os-core/config/storage_roots.local.json --policy-path D:/ProjectOS/project-os-core/config/runtime_policy.local.json openclaw trust-audit`
- rapport runtime `D:/ProjectOS/runtime/openclaw/live/latest_trust_audit.json`
- allowlist active: `project-os-gateway-adapter`, `discord`, `device-pair`, `memory-core`
- provenance plugin locale prouvee via `plugins.load.paths` + `plugins.installs`
- fenetre de rotation pairing fixee a `30 jours`
- scan de fuite de secrets negatif sur les surfaces visibles retenues

Runbook:

- [OPENCLAW_PLUGIN_PAIRING_HARDENING.md](../integrations/OPENCLAW_PLUGIN_PAIRING_HARDENING.md)

### Non-buts

- marketplace plugin libre
- install "pratique" sans trust boundary claire

## Pack 2 - Discord Operations UX

### Objet

Prendre les meilleures idees de l'UX Discord officielle `OpenClaw` sans transformer `Discord` en theatre ni en seconde source de verite.

### Sources

- docs officielles `discord`

### Decision

- `KEEP` pour `threadBindings`
- `KEEP` pour `execApprovals`
- `ADAPT` pour `autoPresence`
- `DEFER` pour les `components v2` les plus riches tant que la base n'est pas beton

### Contenu

- binding durable `thread -> mission/session/run`
- approvals via boutons plutot que texte libre
- presence Discord pilotee par la sante du runtime
- composants riches reserves aux besoins reels

### Travaux

- definir un contrat runtime `DiscordThreadBinding`
- mapper `ApprovalTicket` et `ApprovalDecision` vers des actions Discord rejouables
- definir des etats de presence sobres:
  - `healthy`
  - `degraded`
  - `blocked`
  - `busy`
  - `attention_required`
- garder `Discord` compact:
  - cards courtes
  - threads lies a une mission
  - approvals sensibles seulement dans `#approvals`

### Criteres d'acceptation

- un thread `run` ou `incident` garde un lien durable avec la mission canonique
- un clic d'approbation ne bypass jamais `ApprovalPolicy`
- la presence Discord est derivee du health snapshot, pas d'un flag ad hoc
- la perte d'un thread Discord ne fait pas perdre la verite runtime

### Non-buts

- bot multi-personnages
- composants flashy sans besoin operateur clair
- logique metier enfouie dans des handlers Discord

### Etat 2026-03-15

`IMPLEMENTE`

Preuves retenues:

- commande canonique `py D:/ProjectOS/project-os-core/scripts/project_os_entry.py --config-path D:/ProjectOS/project-os-core/config/storage_roots.local.json --policy-path D:/ProjectOS/project-os-core/config/runtime_policy.local.json openclaw doctor`
- projection runtime `discord_thread_bindings` dans `D:/ProjectOS/runtime/project_os_core.db`
- runtime OpenClaw avec `session.threadBindings`, `channels.discord.threadBindings`, `channels.discord.autoPresence` et `channels.discord.execApprovals`
- target approvals retenu: `dm`
- approver Discord retenu: `1482209095984484443`

Runbook:

- [OPENCLAW_DISCORD_OPERATIONS_UX.md](../integrations/OPENCLAW_DISCORD_OPERATIONS_UX.md)

## Pack 3 - Model Health And Routing

### Objet

Recuperer la "magie utile" de `localclaw`: voir l'etat du stack modele avant de lancer, router intelligemment, et mieux survivre aux timeouts locaux.

### Source

Fork `sunkencity999/localclaw`

### Decision

`ADAPT`

### Contenu

- startup health check du stack modeles
- routage 3 tiers `fast / local / API`
- auto-escalation en cas de timeout local
- proactive briefing depuis les sessions recentes

### Adaptation retenue pour `Project OS`

Le 3 tiers ne veut pas dire "tout local d'abord".
Il veut dire:

- `fast` = deterministic first ou modele peu couteux pour banal / ops / reformulation
- `local` = voie privee explicite quand un modele local est present et prouve
- `API` = voie forte distante pour code, arbitrage, review, traduction de qualite

Sur le poste cible actuel:

- `Claude API` reste ideal pour `Discord` compact et traduction
- `GPT API` reste la voie forte pour code et raisonnement lourd
- la voie `local` existe via `Ollama + qwen2.5:14b`
- si elle tombe, la policy doit rebasculer proprement vers blocage `S3` ou escalation explicite selon la classe du contenu

### Travaux

- ajouter un `model stack health snapshot`
- definir un `ModelRouteClass`
- definir l'escalade automatique si la voie locale timeoute ou degrade
- injecter un recap des sessions recentes seulement quand cela aide reellement

### Criteres d'acceptation

- avant une mission, le systeme sait dire quels providers sont dispo, lents ou bloques
- si la voie `local` patine, l'escalade se fait sans silence ni double effet
- si aucune voie locale n'est configuree, la policy reste propre et explicite
- le proactive briefing ne doit jamais noyer l'operateur sous du vieux contexte

### Non-buts

- brancher un modele local juste pour cocher une case
- remplacer la policy actuelle `Claude API` / `GPT API` sans preuve
- auto-injecter des resumes partout

### Etat 2026-03-15

`IMPLEMENTE`

Preuves retenues:

- commande canonique `py D:/ProjectOS/project-os-core/scripts/project_os_entry.py --config-path D:/ProjectOS/project-os-core/config/storage_roots.local.json --policy-path D:/ProjectOS/project-os-core/config/runtime_policy.local.json router model-health`
- commande canonique `py D:/ProjectOS/project-os-core/scripts/project_os_entry.py --config-path D:/ProjectOS/project-os-core/config/storage_roots.local.json --policy-path D:/ProjectOS/project-os-core/config/runtime_policy.local.json router proactive-briefing --branch-name codex/project-os-<branche>`
- `doctor` et `health snapshot` exposent maintenant `model_stack_health`
- `api-runs build-context` injecte `model_stack_health`
- `api-runs build-context` injecte `recent_session_briefing` quand une branche ou un profil a un historique recent
- `prefer_local_model = true` sans voie locale configuree produit `local_unavailable_escalated_to_api`
- voie locale reelle active sur le poste cible:
  - provider `ollama`
  - modele `qwen2.5:14b`
  - URL `http://127.0.0.1:11434`
- `doctor --strict` echoue desormais si `local_model_enabled = true` mais que la voie locale n'est pas `ready`

Runbook:

- [OPENCLAW_MODEL_HEALTH_AND_ROUTING.md](../integrations/OPENCLAW_MODEL_HEALTH_AND_ROUTING.md)

## Pack 4 - Privacy Guard And Sensitive Routing

### Objet

Prendre la meilleure idee d'`EdgeClaw` pour renforcer `Guardian`: classifier la sensibilite avant cloud, nettoyer ce qui doit l'etre et garder une memoire exploitable sans fuite.

### Source

Fork `OpenBMB/EdgeClaw`

### Decision

`ADAPT FORTEMENT`

### Contenu

- protocole `GuardAgent`
- niveaux `S1 passthrough / S2 desensitize / S3 local`
- double memoire `full / clean`
- routage edge-cloud selon sensibilite

### Adaptation retenue pour `Project OS`

La sensibilite ne remplace pas le risque.
Elle ajoute une seconde dimension au `Mission Router` et au `Guardian`.

Lecture proposee:

- `S1 passthrough` = contenu non sensible, envoi cloud possible selon policy normale
- `S2 desensitize` = contenu utile mais a nettoyer/redacter avant cloud + memoire `clean`
- `S3 local` = contenu trop sensible pour sortie cloud; doit rester local ou etre bloque

Regle dure:

- si un contenu `S3` n'a pas de voie locale sure et prouvee, le systeme bloque au lieu de "downgrader" vers le cloud

### Travaux

- definir un classifieur de sensibilite exploitable
- introduire une memoire `clean` explicite a cote de la verite runtime complete
- formaliser la promotion `full` vs `clean`
- brancher ces decisions dans `Guardian` et `Memory Curator`

### Criteres d'acceptation

- une mission sait etre classee `S1`, `S2` ou `S3`
- `S2` laisse une trace exploitable sans fuite evidente
- `S3` n'est jamais envoye au cloud par accident
- la memoire ne se duplique pas de facon anarchique

### Non-buts

- chiffrer ou dissocier toute la base SQLite des maintenant
- creer une seconde memoire canonique concurrente
- envoyer une version `clean` comme verite unique en effacant les preuves d'origine

### Etat 2026-03-15

`IMPLEMENTE`

Preuves retenues:

- `gateway` classe maintenant les messages `S1 / S2 / S3` avant routage cloud
- `S2` ecrit une copie `full` locale + une copie `clean` exploitable
- `S3` execute localement si la voie locale est `ready`
- `S3` bloque sans voie locale sure et n'est jamais eligible a `OpenMemory` / embeddings cloud
- la recherche memoire standard masque les vues `full` par defaut
- `openclaw doctor` expose maintenant `privacy_guard_policy`

Runbook:

- [OPENCLAW_PRIVACY_GUARD_AND_SENSITIVE_ROUTING.md](../integrations/OPENCLAW_PRIVACY_GUARD_AND_SENSITIVE_ROUTING.md)

## Pack 5 - Local Windows-First Inference Lane

### Objet

Transformer la policy `S3 local` en capacite reelle, pas en simple blocage.

### Source

- architecture `Windows-first`
- runtime local `Ollama`
- modele local `qwen2.5:14b`

### Decision

`IMPLEMENTE`

### Contenu

- runtime local sur l'hote Windows, pas dans `WSL2`
- client local canonique dans `Project OS`
- integration dans `model-health`
- integration dans `doctor --strict`
- execution inline locale pour les messages `Discord` `S3`
- blocage ferme si la voie locale echoue apres routage

### Preuves retenues

- `router model-health` expose `local.status = ready`
- `doctor --strict` reste `ready`
- `openclaw doctor` expose `local_model_route = ok`
- un event `S3` `source=openclaw` route en `s3_local_route`
- la reponse operator reste redactee
- la memoire associee reste `privacy_view = full` avec `openmemory_enabled = false`

### Non-buts

- remplacer `GPT` ou `Claude` partout par du local
- faire du `local-first` ideologique
- accepter un fallback cloud implicite pour `S3`

## Choses a ne pas faire

- ne pas forker `OpenClaw` complet
- ne pas replatformer `Project OS` autour d'un fork
- ne pas basculer l'architecture sous `WSL2` pour ce lot
- ne pas creer des features Discord qui cachent la logique du runtime
- ne pas confondre sensibilite, risque d'action et priorite produit

## Dependances transverses

Avant `Pack 2`:

- `Phase 0` doit etre propre

Avant `Pack 3`:

- `doctor --strict` et `openclaw doctor` doivent deja rester des signaux de confiance

Avant `Pack 4`:

- `Guardian` et `Memory Curator` doivent deja etre les points de passage obligatoires

## Ordre de livraison concret

### Lot A - Verite live finale

- terminer la preuve live Discord de bout en bout
- figer la semantics de health Windows dans la doc et les scripts
- cloturer proprement le bootstrap live

### Lot B - Trust boundary

- terminer le durcissement plugin/pairing
- documenter rotation, re-pairing et mise a jour plugin

### Lot C - Discord operator upgrade

- ajouter `threadBindings`
- ajouter `execApprovals`
- brancher une presence sobre pilotee par health

### Lot D - Smart routing

- ajouter health snapshot des modeles
- introduire les classes `fast / local / API`
- gerer l'escalade automatique
- ajouter le proactive briefing de facon bornee

### Lot E - Privacy reinforcement

- introduire `S1 / S2 / S3`
- ajouter memoire `full / clean`
- bloquer proprement le `S3` sans voie locale sure

### Lot F - Local inference lane

- brancher un provider local Windows-first reel
- faire remonter la voie locale dans `model-health`
- faire traiter `S3` localement quand la voie est `ready`
- bloquer proprement si la voie locale casse apres routage

## Definition de termine

Le renforcement `OpenClaw` sera considere vraiment termine quand:

- le bootstrap live Windows est banal et rejouable
- `Discord` peut porter run, incident, approval et reunion sans perdre la verite runtime
- le stack modele est visible avant mission
- la policy de routage sait rester economique, robuste et explicite
- les contenus sensibles ne peuvent plus partir au cloud par erreur de design

## Liens

- `docs/integrations/OPENCLAW_GATEWAY_ADAPTER.md`
- `docs/integrations/DISCORD_OPERATING_MODEL.md`
- `docs/integrations/DISCORD_MEETING_SYSTEM_V1.md`
- `docs/architecture/WINDOWS_FIRST_HOST_AND_WSL_FABRIC.md`
- `PROJECT_OS_MASTER_MACHINE.md`
