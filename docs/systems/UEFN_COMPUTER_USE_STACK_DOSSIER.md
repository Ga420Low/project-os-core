# UEFN Computer Use Stack Dossier

## Statut

- `active`

## But

Ce dossier sert a classer les systemes externes utiles pour construire un lane `UEFN computer use` dans `Project OS`.

Il ne dit pas encore tout l'ordre d'implementation.
Il dit:

- quoi tester maintenant
- quoi seulement etudier
- quelles preuves il faut obtenir
- quelles briques peuvent vraiment reduire le risque UEFN

## Point de depart reel

Ce qui existe deja dans le coeur:

- `router` canonique dans `src/project_os_core/router/service.py`
- `api_runs` avec `learning_context` dans `src/project_os_core/api_runs/service.py`
- `learning` canonique dans `src/project_os_core/learning/service.py`
- `mission chain` dans `src/project_os_core/mission/chain.py`

Ce qui manque encore dans le coeur:

- pas de package `src/project_os_core/uefn`
- pas de package `src/project_os_core/evals`
- pas de package `src/project_os_core/skills`
- pas de `VerifierGate` canonique
- pas de perception/grounding desktop robuste pour UEFN

Contrainte de fond:

- `UEFN` est un cas dur de `computer use` a cause de la GUI complexe, des surfaces custom, du viewport 3D et des workflows longs
- le lane `Verse` ne doit pas etre traite comme du pur GUI si `VS Code` et des ponts Unreal permettent mieux

## Hypothese de travail

- la meilleure pile `UEFN` sera hybride, pas purement GUI
- il faut sortir le plus possible du GUI via `Verse`, `VS Code` et un pont `Unreal/MCP`
- la GUI doit etre reservee aux zones opaques: viewport, drag, panels custom, verification visuelle
- un systeme ne passe en `A_FAIRE` que s'il a une preuve testable sur la machine

## A faire

### runreal/unreal-mcp

Etat:

- `A_FAIRE`

Pourquoi il compte:

- c'est aujourd'hui la meilleure piste plugin-free pour parler a `Unreal Engine` via `MCP`
- il utilise le `Python Remote Execution` integre au moteur au lieu d'imposer un nouveau plugin C++
- si cela marche sur `UEFN`, on retire une grosse partie du risque `pure GUI`

Ce qu'on recupere:

- serveur `MCP` deja pense pour l'editeur Unreal
- outils `editor_run_python`, navigation editeur, inspection d'objets et screenshots
- pattern `bridge local-first` entre agent et editeur

Ce qu'on n'importe pas:

- l'idee que cela est automatiquement compatible `UEFN`
- une dependance aveugle a tout le serveur si un bridge plus petit suffit

Preuves a obtenir:

- ouvrir `UEFN` ou un projet compatible et verifier si le protocole de `Python Remote Execution` est disponible
- executer une commande simple depuis le bridge et recuperer un resultat lisible
- prouver une action editeur utile sans clic GUI

Ou ca entre dans Project OS:

- futur package `src/project_os_core/uefn/bridge/`
- `Pack B` du futur lane `UEFN`

Sources primaires:

- [runreal/unreal-mcp](https://github.com/runreal/unreal-mcp)

### cgtoolbox/UnrealRemoteControlWrapper

Etat:

- `A_FAIRE`

Pourquoi il compte:

- c'est une base basse couche propre pour construire un bridge maison si `runreal/unreal-mcp` ne passe pas tel quel
- il couvre a la fois `Remote Control API` et `Python Remote Execution`

Ce qu'on recupere:

- wrapper Python reutilisable
- pattern de connexion distante a l'editeur
- exemples clairs de remote execution et d'echange de donnees

Ce qu'on n'importe pas:

- toute la surface du wrapper si seules quelques primitives sont utiles
- l'hypothese que `Remote Control API` est disponible partout dans `UEFN`

Preuves a obtenir:

- verifier quelles parties du wrapper sont compatibles avec `UEFN`
- prouver au moins un read et un write ou une execution distante depuis la machine locale

Ou ca entre dans Project OS:

- futur package `src/project_os_core/uefn/bridge/`
- fallback si `runreal/unreal-mcp` est partiellement inutilisable

Sources primaires:

- [cgtoolbox/UnrealRemoteControlWrapper](https://github.com/cgtoolbox/UnrealRemoteControlWrapper)

### microsoft/OmniParser

Etat:

- `A_FAIRE`

Pourquoi il compte:

- c'est l'un des parseurs d'ecran les plus utiles pour les surfaces GUI sans arbre d'accessibilite exploitable
- Microsoft a ajoute du `local trajectory logging`, ce qui le rend utile aussi pour la collecte de traces

Ce qu'on recupere:

- `screen parsing` pour toolbar, menus, panneaux et controles opaques
- `OmniTool` comme reference de glue `parser + model + action`
- idees de collecte locale de trajectoires pour un futur dataset UEFN

Ce qu'on n'importe pas:

- une dependance forte a toute la stack `OmniTool`
- les poids ou composants sous licence inadaptree sans verifier l'usage

Preuves a obtenir:

- parser des screenshots UEFN reels et mesurer la couverture utile des controles
- verifier la latence pratique sur la machine cible
- valider la contrainte licence avant toute integration durable

Ou ca entre dans Project OS:

- futur package `src/project_os_core/uefn/grounding/`
- futur package `src/project_os_core/evals/` pour le harness de perception

Sources primaires:

- [microsoft/OmniParser](https://github.com/microsoft/OmniParser)

### OpenAdaptAI/OmniMCP

Etat:

- `A_FAIRE`

Pourquoi il compte:

- c'est une bonne couche intermediaire `perceive-plan-act` basee sur `OmniParser`
- il montre comment relier un parser d'ecran, un planner et un executor avec des logs de runs

Ce qu'on recupere:

- pattern `agent_executor`
- structure de runs debugges
- separation entre perception, planning et execution

Ce qu'on n'importe pas:

- l'idee de prendre `OmniMCP` comme runtime canonique de `Project OS`
- sa boucle complete telle quelle sans l'aligner sur `Mission Router`

Preuves a obtenir:

- verifier si la boucle `perception -> plan -> action` reste stable sur un petit workflow UEFN
- mesurer si la structure de logs est assez bonne pour nourrir `skills` et `evals`

Ou ca entre dans Project OS:

- reference pour `src/project_os_core/uefn/runtime/`
- source d'inspiration pour `trace capture`

Sources primaires:

- [OpenAdaptAI/OmniMCP](https://github.com/OpenAdaptAI/OmniMCP)

### ServiceNow/GroundCUA

Etat:

- `A_FAIRE`

Pourquoi il compte:

- le vrai probleme UEFN est souvent le `grounding`, pas juste le planning
- `GroundCUA` apporte un dataset desktop dense et `GroundNext` comme modele de grounding recent

Ce qu'on recupere:

- reference dataset pour evaluer du grounding desktop
- idee d'un `second grounder` dans un `mixture-of-grounding`
- architecture d'eval sur captures desktop reelles

Ce qu'on n'importe pas:

- le training complet tant que nous n'avons pas notre propre harness
- l'hypothese que le dataset general desktop couvre naturellement `UEFN`

Preuves a obtenir:

- tester `GroundNext` sur un petit lot de screenshots UEFN
- comparer contre `OmniParser` sur les memes ecrans
- verifier si un vote simple entre grounders ameliore la precision utile

Ou ca entre dans Project OS:

- futur package `src/project_os_core/uefn/grounding/`
- futur package `src/project_os_core/evals/`

Sources primaires:

- [ServiceNow/GroundCUA](https://github.com/ServiceNow/GroundCUA)
- [GroundCUA project page](https://groundcua.github.io/)

### showlab/showui-pi

Etat:

- `A_FAIRE`

Pourquoi il compte:

- `UEFN` contient beaucoup d'actions continues ou semi-continues: drag, slider, camera, gizmo, viewport
- `ShowUI-pi` travaille exactement la partie que les agents click-only gerent mal

Ce qu'on recupere:

- modele mental `discrete + continuous actions`
- benchmark `ScreenDrag`
- idee d'un lane specifique pour les actions de dexterite GUI

Ce qu'on n'importe pas:

- la pile complete comme runtime principal
- un entrainement lourd tant qu'on n'a pas prouve le besoin exact

Preuves a obtenir:

- lister les actions UEFN qui relvent vraiment du drag fin
- verifier si `ShowUI-pi` ou sa logique de trajectoires apporte quelque chose de reel sur ces actions

Ou ca entre dans Project OS:

- futur package `src/project_os_core/uefn/actions/`
- futur package `src/project_os_core/evals/drag/`

Sources primaires:

- [showlab/showui-pi](https://github.com/showlab/ShowUI-Pi)
- [ShowUI-pi paper](https://arxiv.org/abs/2512.24965)

## A etudier

### appleweed/UnrealMCPBridge

Etat:

- `A_ETUDIER`

Pourquoi il compte:

- il expose la logique `MCP client -> full UE Python API` via un plugin Unreal
- si `UEFN` accepte ce type de plugin ou de bridge, la surface de controle serait tres riche

Ce qu'on recupere:

- architecture d'un vrai pont `MCP` vers l'API Python Unreal
- idees d'outillage et de prompts exposes a un agent

Ce qu'on n'importe pas:

- l'hypothese que `UEFN` supporte le meme mode plugin que `UE`
- la decision d'installer un plugin lourd sans preuve de compatibilite

Preuves a obtenir:

- verifier si l'approche plugin est possible dans `UEFN`
- mesurer le cout d'installation et de maintenance

Ou ca entre dans Project OS:

- reference pour un futur `uefn bridge`
- option secondaire si la voie plugin-free echoue

Sources primaires:

- [appleweed/UnrealMCPBridge](https://github.com/appleweed/UnrealMCPBridge)

### simular-ai/Agent-S

Etat:

- `A_ETUDIER`

Pourquoi il compte:

- `Agent-S` est un bon referentiel d'architecture `generalist-specialist`
- la famille `Agent-S` pousse la planification hierarchique et le `mixture-of-grounding`

Ce qu'on recupere:

- pattern `manager/worker` ou `host/app`
- idees de grounding composite
- signal benchmark pour jauger l'etat de l'art ouvert

Ce qu'on n'importe pas:

- la stack complete comme verite canonique de `Project OS`
- le workflow multi-agent tel quel sans passer par `Mission Router`

Preuves a obtenir:

- verifier quelles pieces sont transposables sans recrire le coeur
- isoler un pattern d'orchestration simple a reprendre

Ou ca entre dans Project OS:

- reference pour `router + uefn runtime`
- inspiration pour `VerifierGate` et decomposition

Sources primaires:

- [simular-ai/Agent-S](https://github.com/simular-ai/Agent-S)
- [Agent S2 paper](https://arxiv.org/abs/2504.00906)

### microsoft/UFO

Etat:

- `A_ETUDIER`

Pourquoi il compte:

- `UFO` reste la reference ouverte la plus forte pour l'architecture Windows `HostAgent + AppAgent`
- c'est le meilleur point de comparaison pour savoir si notre design Windows est trop faible

Ce qu'on recupere:

- architecture Windows-first
- decomposition par application
- garde-fous et patterns d'orchestration

Ce qu'on n'importe pas:

- la pile complete en remplacement du coeur `Project OS`
- toute la dette de framework si seuls quelques patterns suffisent

Preuves a obtenir:

- verifier ce qui est vraiment reutilisable sans dupliquer `router`, `learning` et `mission`
- comparer sa logique de decomposition avec notre future couche `uefn`

Ou ca entre dans Project OS:

- reference d'architecture pour `src/project_os_core/uefn/`

Sources primaires:

- [microsoft/UFO](https://github.com/microsoft/UFO)

### bytedance/UI-TARS et UI-TARS-desktop

Etat:

- `A_ETUDIER`

Pourquoi il compte:

- c'est une reference forte pour un modele GUI natif et une stack desktop ouverte
- utile pour benchmarker une lane locale ou hybride

Ce qu'on recupere:

- modele GUI natif
- pattern d'infra `desktop agent stack`
- baseline locale ou semi-locale de comparaison

Ce qu'on n'importe pas:

- l'idee de fine-tuner tout de suite
- l'idee de faire de `UI-TARS` le coeur produit avant d'avoir des evals UEFN

Preuves a obtenir:

- tester la robustesse sur un petit workflow UEFN
- mesurer VRAM, latence et taux de correction manuelle necessaire

Ou ca entre dans Project OS:

- benchmark secondaire
- futur lane local si le cout cloud devient trop fort

Sources primaires:

- [bytedance/UI-TARS](https://github.com/bytedance/UI-TARS)
- [bytedance/UI-TARS-desktop](https://github.com/bytedance/UI-TARS-desktop)

### OpenGVLab/ZeroGUI

Etat:

- `A_ETUDIER`

Pourquoi il compte:

- `ZeroGUI` travaille l'apprentissage GUI online sans annotation humaine directe
- c'est une piste forte si on veut un jour entrainer sur `UEFN` sans labellisation manuelle massive

Ce qu'on recupere:

- pattern `automatic task generation`
- pattern `automatic reward estimation`
- boucle `online learning`

Ce qu'on n'importe pas:

- un passage precoce au RL
- l'idee de lancer cela avant d'avoir un benchmark UEFN maison

Preuves a obtenir:

- confirmer que le signal de recompense peut etre rendu fiable sur `UEFN`
- verifier le cout de mise en place d'un environnement de generation de taches

Ou ca entre dans Project OS:

- futur `Pack D` ou `Pack E` de learning avance

Sources primaires:

- [OpenGVLab/ZeroGUI](https://github.com/OpenGVLab/ZeroGUI)
- [ZeroGUI paper](https://arxiv.org/abs/2505.23762)

### 2020-qqtcg/GUI-360

Etat:

- `A_ETUDIER`

Pourquoi il compte:

- `GUI-360` est moins un composant runtime qu'un bon modele de dataset et de benchmark
- il montre comment unifier grounding, parsing et action prediction

Ce qu'on recupere:

- structure d'un corpus computer-use riche
- idees de pipeline de collecte et de filtrage
- criteres d'evaluation unifies

Ce qu'on n'importe pas:

- le dataset brut comme preuve qu'on sait faire `UEFN`
- une dette d'infra dataset trop tot

Preuves a obtenir:

- transformer ses idees de benchmark en un mini corpus UEFN maison
- definir 10 a 20 taches UEFN canoniques au lieu de copier le dataset

Ou ca entre dans Project OS:

- futur package `src/project_os_core/evals/`
- futur corpus interne `UEFN`

Sources primaires:

- [2020-qqtcg/GUI-360](https://github.com/2020-qqtcg/GUI-360)

## A rejeter pour maintenant

### Strategie pure GUI pour tout UEFN

Etat:

- `REJECT`

Pourquoi elle parait seduisante:

- elle semble generaliste
- elle evite de traiter `Verse`, `VS Code` et les bridges Unreal comme des lanes differentes

Pourquoi on la rejette maintenant:

- `UEFN` ouvre deja `Verse` dans `VS Code`
- si une partie du travail peut sortir du GUI, la garder en GUI pur ajoute du cout, de la latence et de la fragilite
- la valeur de `Project OS` vient de l'hybride, pas d'un dogme `computer use partout`

Ce qu'on recupere:

- rien comme choix principal

Ce qu'on n'importe pas:

- un runtime integralement base sur clics clavier et screenshots pour tous les cas

Preuves a obtenir pour rouvrir la question:

- montrer qu'aucun pont viable n'existe pour les surfaces non GUI
- montrer que le lane code `VS Code + Verse` n'apporte aucun gain

Ou ca entre dans Project OS:

- nulle part comme doctrine principale

Sources primaires:

- [Epic UEFN docs: Modify and Run Your First Verse Program](https://dev.epicgames.com/documentation/en-us/uefn/modify-and-run-your-first-verse-program-in-unreal-editor-for-fortnite)

## Ordre de test recommande

1. `runreal/unreal-mcp`
2. `cgtoolbox/UnrealRemoteControlWrapper`
3. `microsoft/OmniParser`
4. `OpenAdaptAI/OmniMCP`
5. `ServiceNow/GroundCUA`
6. `showlab/showui-pi`

## Sources

- [Epic UEFN docs: Modify and Run Your First Verse Program](https://dev.epicgames.com/documentation/en-us/uefn/modify-and-run-your-first-verse-program-in-unreal-editor-for-fortnite)
- [runreal/unreal-mcp](https://github.com/runreal/unreal-mcp)
- [cgtoolbox/UnrealRemoteControlWrapper](https://github.com/cgtoolbox/UnrealRemoteControlWrapper)
- [appleweed/UnrealMCPBridge](https://github.com/appleweed/UnrealMCPBridge)
- [microsoft/OmniParser](https://github.com/microsoft/OmniParser)
- [OpenAdaptAI/OmniMCP](https://github.com/OpenAdaptAI/OmniMCP)
- [ServiceNow/GroundCUA](https://github.com/ServiceNow/GroundCUA)
- [GroundCUA project page](https://groundcua.github.io/)
- [showlab/showui-pi](https://github.com/showlab/ShowUI-Pi)
- [ShowUI-pi paper](https://arxiv.org/abs/2512.24965)
- [simular-ai/Agent-S](https://github.com/simular-ai/Agent-S)
- [Agent S2 paper](https://arxiv.org/abs/2504.00906)
- [microsoft/UFO](https://github.com/microsoft/UFO)
- [bytedance/UI-TARS](https://github.com/bytedance/UI-TARS)
- [bytedance/UI-TARS-desktop](https://github.com/bytedance/UI-TARS-desktop)
- [OpenGVLab/ZeroGUI](https://github.com/OpenGVLab/ZeroGUI)
- [ZeroGUI paper](https://arxiv.org/abs/2505.23762)
- [2020-qqtcg/GUI-360](https://github.com/2020-qqtcg/GUI-360)
