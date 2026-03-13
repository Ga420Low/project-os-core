# Project OS Master Machine

Ce fichier est la reference racine du projet.
Il fixe le cap produit, les decisions structurantes et les regles a respecter par l'humain et par l'IA.

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

## Workflow officiel

Le workflow officiel du projet est maintenant hybride:

- `OpenAI API` grande fenetre = force de frappe principale de raisonnement
- `Codex` = penseur directeur, inspecteur, integrateur, verificateur
- `Project OS` runtime = verite machine, memoire canonique, tests et evidence

Regles:

- l'API pense large et peut diriger un gros lot
- `Codex` prepare, inspecte, challenge et integre
- le runtime local reste la verite finale
- aucune branche n'entre dans le coeur sans inspection locale et verification reelle

Reference detaillee:

- `docs/architecture/HYBRID_LARGE_CONTEXT_WORKFLOW.md`

## Vision produit

Project OS doit devenir une `master machine`:

- un cerveau d'execution pour le poste fondateur
- un systeme de supervision a distance
- un moteur multi-projets
- un actif reutilisable pour une future entreprise

Le systeme doit privilegier la robustesse, la reprise et l'auditabilite plutot que la demo fragile.

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
  - UEFN
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
- `OpenAI API`: cerveau generaliste
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
Ils ne remplacent pas les skills locaux Codex.

## Etat operationnel actuel

Le noyau local a maintenant les fondations suivantes en etat reel:

- `OpenMemory` actif comme memoire primaire
- `SQLite + sqlite-vec` actifs comme verite locale et retrieval
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

Le projet secrets actif est:

- `Project OS Core` dans `Infisical`
- repo relie via `.infisical.json`
- mode local: `infisical_required`
- support `Universal Auth` machine identity implemente dans le coeur

## Etat OpenClaw actuel

Le lot `OpenClaw` est maintenant pose en deux etages:

- frontiere d'architecture figee
- adaptateur local `OpenClaw -> Project OS` code dans le repo

Le package live est:

- `integrations/openclaw/project-os-gateway-adapter`

Role actuel:

- capter `message_received` depuis `OpenClaw`
- convertir l'evenement en charge utile canonique `Project OS`
- appeler `gateway ingest-openclaw-event`

Ce qui reste avant de considerer le lot 4 totalement termine:

- brancher cet adaptateur sur un runtime `OpenClaw` reel du poste
- valider Discord/WebChat avec un message live

## Memory OS locale

La memoire finale doit vivre sur ton PC.
Le systeme ne doit jamais dependre d'un prompt geant ou d'un cache distant pour sa continuite.

La pile memoire visee est:

- `OpenMemory` pour le moteur memoire primaire
- `SQLite` comme verite locale canonique
- `sqlite-vec` pour la recherche vectorielle locale
- fichiers locaux pour les preuves, captures, rapports et artefacts
- `Letta` comme backup et reference de comparaison

Autres candidats surveilles:

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

## Premier cas d'usage

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
