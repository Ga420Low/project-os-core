# Project OS Master Machine

Ce fichier est la reference racine du projet.
Il fixe le cap produit, les decisions structurantes et les regles a respecter par l'humain et par l'IA.

Pour le comportement agent au quotidien, la porte d'entree prioritaire est maintenant:

- [AGENTS.md](D:/ProjectOS/project-os-core/AGENTS.md)

## Identite

Project OS est un systeme proprietaire de copilote PC autonome, supervise, multi-apps et multi-canaux.

Le produit ne depend pas d'UEFN.
UEFN est un profile applicatif parmi d'autres.
Le coeur doit pouvoir, a terme, piloter:

- UEFN
- web et email
- montage video
- documents et operations business
- workflows Windows generaux

## Mission

Construire une surcouche d'intelligence locale capable de:

- comprendre l'etat du PC
- planifier une mission longue
- agir sur Windows, le web et des applications metier
- parler avec l'operateur via Discord
- memoriser projets, habitudes, incidents et preuves
- demander une approbation lorsque le risque augmente
- reprendre une mission sans perdre le contexte

## Taxonomie app et profils

Regle de vocabulaire:

- `categorie` = famille de capacites ou de workers
- `app` = logiciel concret a piloter
- `profil applicatif` = facon dont `Project OS` travaille avec une app ou un domaine

Donc:

- `UEFN` n'est pas une categorie d'architecture
- `UEFN` est une app cible
- `UEFN` peut aussi etre le nom d'un profil applicatif

## Workflow officiel

Le workflow officiel repose sur un duo de modeles complementaires (ADR 0013):

- `GPT API` (gpt-5.4, 1M contexte) = Le Cerveau / Le Dev (code, planifie, brainstorme)
- `Claude API` (opus/sonnet, 1M contexte) = L'Auditeur / Le Traducteur (review cross-model, traduit pour l'humain, filtre le bruit)
- `Project OS` runtime = verite machine, memoire canonique, tests et evidence
- `Discord` = surface operateur prioritaire ; terminal + dashboard = supervision locale et preuve

Regles:

- GPT API pense large et peut diriger un gros lot
- Claude API audite le code produit par GPT (vrai challenge cross-model, pas d'auto-validation)
- Claude API traduit les signaux techniques en francais humain pour le fondateur via Discord
- le runtime local reste la verite finale
- aucune branche n'entre dans le coeur sans review Claude API et verification reelle
- les gros runs de code se font en silence operationnel
- les sorties operateur doivent etre en francais clair, non developpeur
- un gros run ne part pas sans contrat de run et validation humaine
- le fondateur interagit via Discord (PC + mobile), au feeling, pas de planning rigide

Reference detaillee:

- `docs/architecture/HYBRID_LARGE_CONTEXT_WORKFLOW.md`
- `docs/integrations/API_LEAD_AGENT_V1.md`
- `docs/architecture/AGENT_IDENTITY_AND_CHANNEL_MODEL.md`
- `docs/architecture/DOCUMENTATION_LANGUAGE_POLICY.md`
- `docs/architecture/HANDOFF_MEMORY_POLICY.md`
- `docs/architecture/WINDOWS_FIRST_HOST_AND_WSL_FABRIC.md`
- `docs/integrations/DISCORD_OPERATING_MODEL.md`
- `docs/architecture/RUN_COMMUNICATION_POLICY.md`
- `docs/integrations/DISCORD_CHANNEL_TOPOLOGY.md`
- `docs/integrations/API_RUN_CONTRACT.md`
- `docs/architecture/FRENCH_OPERATOR_OUTPUT_POLICY.md`

## API Lead Agent v1

Le premier systeme de gros runs est maintenant pose dans le coeur.

Il repose sur:

- `gpt-5.4` comme lead agent obligatoire
- une lane `repo_cli` pour le code
- une lane `future_computer_use` reservee pour plus tard
- un systeme de `ContextPack`
- un systeme de `MegaPrompt`
- un systeme de `ApiRunResult`
- un systeme de `ApiRunReview`
- un systeme de `RunContract`
- un monitor texte local des runs
- un dashboard web local des runs pour la supervision visuelle

Les modes canoniques sont:

- `audit`
- `design`
- `patch_plan`
- `generate_patch`

Regle dure:

- l'API peut produire un gros lot
- mais Claude API et l'humain gardent la revue avant integration dans `main`
- pendant un run de code, le texte naturel est remplace par dashboard + terminal + cartes compactes
- avant tout run API reel, le dashboard local doit etre lance automatiquement sur le PC pour offrir une preuve visuelle immediate

## Mode operatoire vNext

L'agent systeme reste unique, mais travaille selon plusieurs modes:

- `discussion`
- `architecte`
- `builder`
- `reviewer`
- `gardien`
- `incident`

Discord devient le hub humain via une topologie `hub + salons`:

- `#pilotage`
- `#runs-live`
- `#approvals`
- `#incidents`
- threads par mission

Rappels:

- `Discord` n'est pas la memoire canonique
- `Discord` n'est pas la verite machine
- `Discord` est l'interface operateur

## Vision produit

Project OS doit devenir une `master machine`:

- un cerveau d'execution pour le poste fondateur
- un systeme de supervision a distance
- un moteur multi-projets
- un actif reutilisable pour une future entreprise

Le systeme doit privilegier la robustesse, la reprise et l'auditabilite plutot que la demo fragile.

## Windows-first et WSL

`DECISION CONFIRMED`

Le systeme reste `Windows-first`.

Le poste Windows est la machine operatoire principale.
`WSL2` n'est pas la base unique du produit.

Role retenu:

- `Windows host` = verite machine, runtime, memoire, evidence, workers Windows, apps reelles, `UEFN`
- `WSL2` = cellules de travail optionnelles par projet ou par domaine

Le futur peut inclure plusieurs cellules `WSL2` en parallele, mais elles restent supervisees par l'hote Windows.

Reference:

- `docs/architecture/WINDOWS_FIRST_HOST_AND_WSL_FABRIC.md`

## Principe cle

Le systeme final n'est pas:

- un ensemble de scripts UEFN colles entre eux
- un simple agent screenshot -> clic
- un prompt geant qui sert de memoire

Le systeme final est:

- un runtime local qui tient la verite machine
- une orchestration durable
- une memoire long terme structuree
- des workers specialises
- des preuves et des garde-fous
- une interface operateur distante

## Discipline de decision

Le projet doit garder une discipline explicite de decision, sans changement implicite de cap.

Marqueurs obligatoires:

- `DECISION CONFIRMED`
- `DECISION CHANGED`

Usage:

- `DECISION CONFIRMED` quand une direction importante est revalidee
- `DECISION CHANGED` quand on remplace proprement une direction precedente

Ces decisions doivent etre promues regulierement dans la memoire durable.
L'humain n'a pas besoin de le redire a chaque fois.

## Compensation cognitive et anti-boucle

Le systeme doit agir comme une couche de compensation cognitive haut niveau pour le fondateur.

Cela veut dire:

- supposer que des decisions importantes peuvent etre oubliees
- supposer que des suivis utiles peuvent etre manques
- supposer que des erreurs deja vues peuvent revenir
- supposer que le systeme peut tourner en rond sans s'en rendre compte

Obligations:

- automatiser autant que possible la memoire des decisions, contraintes, lecons et incidents
- aller chercher plus loin quand le niveau de profondeur baisse ou que le raisonnement s'appauvrit
- detecter les repetitions steriles, faux progres et boucles de pensee
- detecter une baisse de capacite, de qualite ou de coherence
- faire un `refresh` de contexte et prendre du recul quand le systeme se degrade
- preferer une correction structurelle plutot qu'un patch opportuniste

Le projet ne doit pas attendre que l'humain pense a rappeler ce genre de besoin.
Cette exigence est structurelle.

## Architecture cible

- `gateway/`
  - facade operateur riche
  - Discord
  - WebChat
  - Control UI
  - inbox
  - websocket
- `orchestration/`
  - graphe mission canonique a 6 roles
  - policies
  - reprise et handoff
  - mission router policy-aware
- `memory/`
  - memoire episodique
  - memoire semantique
  - memoire procedurale
- `runtime/`
  - etat machine
  - evidence
  - approvals
  - sessions
  - bootstrap state
  - health snapshots
- `workers/`
  - Windows
  - browser
  - media
  - app profiles (`UEFN`, etc.)
  - future Linux project cells via `WSL2`
- `profiles/`
  - profils applicatifs
  - projets cibles
- `integrations/`
  - OpenAI
  - OpenClaw
  - LangGraph
  - OpenMemory
  - Stagehand
  - UFO
- `benchmarks/`
  - OSWorld
  - WindowsAgentArena
  - WorldGUI
- `tests/`
  - unit
  - integration
  - evals

## Branches de construction

Le projet doit etre pilote comme un systeme de branches maitrisees, pas comme une suite de features.

Les branches majeures sont:

- `gateway_operator`
- `orchestration`
- `memory`
- `runtime_state`
- `workers`
- `perception`
- `evaluation`
- `ops_observability`
- `security_policy`

## Stack finale retenue

- `OpenClaw`: shell operateur, Discord, inbox, acces distant
- `LangGraph`: orchestration durable
- `OpenMemory`: logique de memoire long terme locale
- `GPT API`: cerveau generaliste (lane code et planification)
- `Claude API` (Anthropic): auditeur cross-model et traducteur operateur
- `UFO` style worker: execution Windows
- `Stagehand`: execution web
- `pywinauto` et UIA: perception structuree Windows
- `OmniParser`: fallback vision
- `SQLite`: verite locale canonique
- `sqlite-vec`: recherche vectorielle embarquee et portable
- `Langfuse`: observabilite LLM, datasets, evals
- `OpenTelemetry`: logs, traces, metriques
- `Infisical`: secrets et configuration sensible
- `WindowsAgentArena`, `OSWorld`, `WorldGUI`: evaluation
- `Letta`: backup et benchmark memoire

Note de trajectoire:

- `WSL2` est autorise comme tissu futur de cellules de travail isolees
- il ne remplace pas l'hote Windows comme verite operatoire

## Frontiere OpenClaw vs Project OS

`OpenClaw` porte:

- channels
- inbox operateur
- pairing / allowlists
- `WebChat`
- `Control UI`
- events operateur
- future hooks voix/mobile/nodes

`Project OS` porte:

- `RuntimeState`
- `Memory`
- `Mission Router`
- `ExecutionPolicy`
- `ApprovalPolicy`
- `MissionRun`
- `Workers`
- `Profiles`
- `Evidence`

Regles dures:

- `OpenClaw` n'est jamais la source de verite
- `OpenClaw` ne decide pas de la memoire canonique
- `OpenClaw` ne contourne pas le `Mission Router`

## Orchestration canonique

Le graphe mission officiel part sur 6 roles:

- `Operator Concierge`
- `Planner`
- `Memory Curator`
- `Critic`
- `Guardian`
- `Executor Coordinator`

Le premier graphe reste unique et canonique.
On ne multiplie pas les graphes metier avant d'avoir valide cette forme.

## Gouvernance analytique

Au-dessus du graphe canonique, `Project OS` peut ouvrir une couche de deliberation structuree pour les arbitrages importants.

Cette couche ne remplace pas les 6 roles.
Elle sert a cadrer:

- les reviews avant codage
- les arbitrages d'architecture
- les pre-mortems
- les conseils strategiques
- les revues de confiance et de comportement externe

V1 retenue:

- `Vision Strategy`
- `Product Value`
- `Technical Architecture`
- `Execution Delivery`
- `Operations Workflow`
- `Security Governance`
- `Red Team`
- `Clarity Anti-Bullshit`
- `Research Exploration`

Angles reserves:

- `Financial Leverage`
- `Legal Compliance`
- `Brand Trust`

Regles dures:

- les angles sont des fonctions d'analyse bornees, pas des personnages
- ils sont actives selectivement
- ils n'ont aucune autorite d'execution directe
- le `Moderator` est une fonction procedurale, pas une nouvelle identite produit
- la synthese arbitree et le `DecisionRecord` sont les seules sorties durables par defaut

References:

- `docs/analysis-angles/README.md`
- `docs/analysis-angles/00-framework.md`
- `docs/analysis-angles/06-activation-policy.md`
- `docs/integrations/DISCORD_MEETING_SYSTEM_V1.md`

## Skills de mega prompt

Les gros runs API doivent declarer explicitement leurs skills de run.

Base minimale:

- `CODE`
- `AUDIT`
- `DESIGN`
- `PATCH_PLAN`
- `GENERATE_PATCH`
- `UEFN`
- `WINDOWS`
- `BROWSER`
- `MEMORY`
- `SECURITY`
- `OPS`

Ces skills de run servent a borner le mega prompt.
Ils ne remplacent pas les skills locaux de l'agent.

## Etat operationnel actuel

Le noyau local a maintenant les fondations suivantes en etat reel:

- `OpenMemory` actif comme memoire primaire
- `SQLite + sqlite-vec` actifs comme verite locale et retrieval
- `api_runs` actif pour les gros runs `gpt-5.4`
- `learning` actif pour les signaux de progression, boucle et refresh
- `Mission Router` actif avec:
  - route `cheap` deterministe
  - route standard `gpt-5.4 high`
  - route hard `gpt-5.4 xhigh`
  - route exceptionnelle `gpt-5.4-pro` sous approval explicite
- `Infisical` relie au projet secrets dedie
- support `Universal Auth` machine identity implemente dans le coeur
- `health snapshot` local actif
- `doctor --strict` vert avec `Universal Auth`
- `OPENAI_API_KEY` resolu depuis `Infisical` sans dependance a la session utilisateur
- premier run API reel `gpt-5.4` valide sur le poste

Le projet secrets actif est:

- `Project OS Core` dans `Infisical`
- repo relie via `.infisical.json`
- mode local: `infisical_required`
- support `Universal Auth` machine identity implemente dans le coeur

## Etat OpenClaw actuel

Le lot `OpenClaw` est maintenant pose en quatre etages:

- frontiere d'architecture figee
- adaptateur local `OpenClaw -> Project OS` code dans le repo
- bootstrap natif `OpenClaw` valide sur le poste
- doctor + replay fail-closed valides sur le poste

Le package live est:

- `integrations/openclaw/project-os-gateway-adapter`

Le runtime reel retenu est:

- `D:\ProjectOS\openclaw-runtime`
- `D:\ProjectOS\runtime\openclaw`

Role actuel:

- capter `message_received` depuis `OpenClaw`
- convertir l'evenement en charge utile canonique `Project OS`
- appeler `gateway ingest-openclaw-event`
- prouver en replay que tout passe par `Gateway -> Mission Router`
- echouer ferme tant qu'aucune preuve canonique `source=openclaw` n'a ete validee

Ce qui est deja valide:

- bootstrap natif via `openclaw plugins install --link`
- plugin visible dans `OpenClaw`
- configuration et policy `Project OS` lisibles
- doctor `OpenClaw` vert et comprehensible
- replay sur fixtures reelles vert
- validation live canonique verte sur le poste
- voie locale Windows-first reelle via `Ollama`
- modele local courant: `qwen2.5:14b`

Ce qui reste avant de considerer le lot 4 totalement termine:

- rejouer un vrai message operateur Discord/WebChat amont si on veut une preuve humaine stricte distincte de la preuve canonique runtime

## Memory OS locale

La memoire finale doit vivre sur ton PC.
Le systeme ne doit jamais dependre d'un prompt geant ou d'un cache distant pour sa continuite.

La pile memoire visee est:

- `SQLite` comme verite locale canonique
- `OpenMemory` comme sidecar retrieval utile, pas comme verite
- `sqlite-vec` pour la recherche vectorielle locale
- `Retrieval Sidecar` pour query expansion, session recall, temporal decay et MMR
- `Memory OS substrate` pour `MemCube`, `MemoryBlock`, `ThoughtMemory`, `RecallPlan`
- `Sleeptime Curator` pour la consolidation async
- `Temporal Graph Sidecar` local avec cible `Kuzu embedded`
- fichiers locaux pour les preuves, captures, rapports et artefacts

Etat reel maintenant livre:

- blocs partages locaux type Letta
- profils dual-layer `founder_stable_profile` et `recent_operating_context`
- memoire de conclusions `ThoughtMemory`
- supersession non destructive
- traces memoire persistantes
- lane graph locale en `sqlite shadow` tant que `Kuzu` n'est pas present

Autres candidats surveilles:

- `MemOS`: reference architecturale, pas composant central
- `Graphiti`: candidat fort si la lane graph doit monter en puissance
- `A-MEM`: candidat pour enrichissement bidirectionnel
- `Mem0`: couche memoire SDK utile, mais moins centrale
- `Zep`: interessant pour memoire + knowledge graph

## Discord selective sync

`Discord` reste la surface humaine prioritaire, mais pas une source de memoire brute.

Pipeline retenu:

1. message recu
2. classification (`chat`, `tasking`, `idea`, `decision`, `note`, `artifact_ref`)
3. decision explicite de promotion
4. promotion selective vers la memoire canonique

## Standard attendu

Le projet doit rester:

- optimise
- autonome
- intelligent
- securise
- sans doublon
- bien ecrit
- protege
- haut niveau

Le but assume est de construire `Jarvis`.
5. sinon conservation comme evenement tracable uniquement

On promeut les decisions, preferences stables, missions, incidents, artefacts et resumes valides.
On ne promeut pas automatiquement le small talk ni le bruit.

## Meme agent sur plusieurs surfaces

Le systeme doit rester le meme agent a travers:

- gros runs GPT API (le cerveau)
- reviews Claude API (l'auditeur)
- traductions Claude API (le traducteur vers Discord)
- `Discord` (surface operateur fondateur)
- futures surfaces

Cela impose:

- une identite canonique unique
- des overlays de canal sans changer la personnalite
- une memoire partagee
- un handoff explicite entre GPT API, Claude API et Discord
- une supervision locale via terminal + dashboard reste disponible pour l'inspection et la preuve

References:

- `docs/architecture/AGENT_IDENTITY_AND_CHANNEL_MODEL.md`
- `docs/architecture/HANDOFF_MEMORY_POLICY.md`

## Discord operating model

`Discord` est la surface humaine prioritaire.

Le systeme doit y rester:

- compact
- operateur
- rigoureux
- coherent avec l'identite agent

`Discord` n'est jamais:

- la memoire canonique
- la verite machine
- un contournement du `Mission Router`

Reference:

- `docs/integrations/DISCORD_OPERATING_MODEL.md`
- `docs/integrations/DISCORD_MEETING_SYSTEM_V1.md`

## Stockage cible

Le stockage doit etre pense en trois niveaux:

- `hot`
  - etat courant
  - files d'execution
  - checkpoints actifs
  - index et retrieval rapides
- `warm`
  - memoire recente consolidee
  - resumes de mission
  - embeddings utiles
  - preuves recentes
- `cold`
  - archives lourdes
  - screenshots anciens
  - videos, logs bruts, bundles de preuve complets
  - historique long terme

Repartition materielle visee:

- `D:` sur le SSD 990 Pro = coeur de travail
- disque lent 8 To dedie = archive longue
- `C:` n'est pas la cible principale du runtime si sa capacite reste sous pression

Mapping cible:

- `D:\\ProjectOS\\runtime`
- `D:\\ProjectOS\\memory_hot`
- `D:\\ProjectOS\\memory_warm`
- `<ARCHIVE_DRIVE>:\\ProjectOSArchive\\episodes`
- `<ARCHIVE_DRIVE>:\\ProjectOSArchive\\evidence`
- `<ARCHIVE_DRIVE>:\\ProjectOSArchive\\screens`
- `<ARCHIVE_DRIVE>:\\ProjectOSArchive\\reports`

## Ops core

Le systeme final ne doit pas etre aveugle.
La couche ops retenue est:

- `Langfuse` pour traces LLM, prompts, datasets, evals
- `OpenTelemetry` pour logs, traces et metriques
- `Infisical` pour secrets, tokens et configurations sensibles

## Model policy

La politique modele retenue est:

- `gpt-5.4` en `high` par defaut
- `gpt-5.4` en `xhigh` en escalade
- `gpt-5.4-pro` tres rarement et jamais dans la boucle normale

Pour le canal `Discord`, la policy adaptative est:

- banal / check rapide / accuse de reception -> `Claude API` si un LLM est necessaire
- operateur standard -> `gpt-5.4 high`
- complexe / critique / ambigu -> `gpt-5.4 xhigh`
- exceptionnel -> `gpt-5.4-pro` seulement avec approval explicite

Le systeme ne doit pas compenser une mauvaise architecture par une consommation abusive de modele premium.

## Mission Router

Le `Mission Router` est la couche qui decide:

- si une mission peut partir
- quel worker peut la prendre
- quel niveau de raisonnement utiliser
- si une approval est obligatoire
- si le budget autorise la route
- si la mission doit etre bloquee

Le router doit toujours appliquer:

- `gpt-5.4 high` par defaut
- `gpt-5.4 xhigh` uniquement en escalade
- `gpt-5.4-pro` seulement en cas exceptionnel approuve
- blocage immediat si runtime non pret, secret requis absent ou chemin interdit

## Hardening local

Le noyau local doit rester production-like meme avant `OpenClaw` et `LangGraph`.

Cela implique:

- secrets hors repo
- bootstrap idempotent
- `doctor --strict`
- journal append-only
- evidence verifiee par checksum/taille/chemin
- health snapshots locaux
- politique explicite sur `E:\\DO_NOT_TOUCH`

## Upgrade path

Les briques suivantes ne sont pas au coeur immediat, mais doivent rester visibles dans la trajectoire:

- `Temporal` comme evolution vers une execution durable niveau entreprise
- `Qdrant` ou `LanceDB` si la memoire devient trop lourde pour `SQLite + sqlite-vec`

## Regles fondatrices

- Le coeur du systeme reste separe des projets clients.
- Le runtime local est la source de verite.
- Discord est une interface operateur, pas la logique centrale.
- La memoire ne vit pas dans le prompt seul.
- Chaque action sensible doit laisser une preuve.
- Toute autonomie risquee doit pouvoir etre stoppee, reprise et auditee.
- Chaque app importante doit devenir un profile propre.
- Une decision d'architecture doit etre visible dans `docs/`.
- Le SSD porte le hot path, le disque lent porte l'archive.
- Une memoire locale qui ne peut pas etre inspectee ou migree n'est pas acceptable.

## Regles de structure

- `project-os-core` contient le produit.
- Les projets pilotes, comme un projet UEFN, vivent dans des repos separes.
- `profiles/` contient la facon dont Project OS travaille sur une app ou un projet.
- `third_party/` sert de reference locale et de zone d'etude, pas de coeur proprietaire.
- Le code proprietaire doit rester clairement distinct des inspirations externes.

## Premier profil applicatif

Le premier profile metier est `UEFN`.
Le systeme devra pouvoir:

- choisir le bon projet
- comprendre l'etat du poste et des fenetres
- travailler sur la map cible
- lancer des tests
- rapporter
- reprendre plus tard sans confusion

## Anti-spaghetti

Les points suivants sont obligatoires:

- pas de logique metier cachee dans des scripts isoles sans contrat
- pas de dependances ajoutees sans role clair
- pas de memoire implicite dispersee
- pas de couplage fort entre le coeur et un seul projet client
- pas de patch rapide qui contourne la structure cible
- pas de developpement du nouveau coeur a l'interieur d'un ancien repo client

## Ordre de construction

L'ordre de travail officiel est:

1. definir le cadre et les contrats
2. ecrire le nouveau coeur propre, script par script et module par module
3. seulement ensuite auditer l'ancien systeme
4. pour chaque morceau ancien, decider `keep`, `migrate`, `rewrite` ou `delete`

Le nouveau coeur ne doit pas etre aspire par les hacks de l'ancien repo.

## Usage de ce fichier

Quand l'humain ou l'IA hesite, ce fichier prime sur l'improvisation.

Si un changement contredit ce document, il faut:

1. mettre a jour l'architecture ou la decision explicitement
2. documenter pourquoi
3. seulement ensuite changer le code
