# Natural Manager Mode Plan

## Statut

Feuille de route canonique proposee.

Ce document cadre le chantier `mode manager naturel` pour `Project OS`.
Il complete:

- `docs/roadmap/PERSONA_V2_CONTEXT_INTEGRITY_PLAN.md`
- `docs/roadmap/DISCORD_AUTONOMY_NO_LOSS_PLAN.md`

Le but n'est pas de transformer `Project OS` en parseur de commandes.
Le but est de permettre au fondateur de parler naturellement depuis `Discord`, tout en gardant une bascule fiable entre `discussion`, `directive`, `approval`, `execution` et `reporting`.

## But

Faire de `Project OS` un systeme qui:

- comprend une conversation libre de type `manager -> operateur`
- distingue la pensee a voix haute, la direction strategique, la demande de statut et la vraie delegation
- transforme une demande implicite en `contrat d'action` structurable
- n'exige une clarification que si l'intention est ambiguë, risquee ou destructive
- garde `Discord` comme cockpit simple et `Project OS` comme verite canonique

## Probleme produit

Le systeme actuel marche bien pour:

- discuter
- repondre a des questions runtime
- router certains ordres explicites
- demander ou enregistrer des approvals

Mais il reste encore trop sensible a des marqueurs de surface du style:

- `fais`
- `create`
- `write`
- `run`
- `ouvre`

Ce n'est pas une bonne UX de fondateur.
Le fondateur doit pouvoir dire des choses comme:

- `tu peux me poser un fichier test dans le repo pour verifier la boucle ?`
- `j'aimerais qu'on garde une trace de ca dans un md`
- `on part la-dessus, lance proprement`
- `prepares-moi un petit plan et mets-le dans le repo`

Le systeme doit comprendre le niveau d'engagement attendu sans exiger une grammaire de terminal.

## Point de depart reel dans le repo

### Ce qui existe deja

- classification selective sync et typologie `chat / status / approval / decision / tasking` dans `src/project_os_core/gateway/promotion.py`
- garde de clarification / approvals et routing policy-aware dans `src/project_os_core/router/service.py`
- boucle gateway canonique, `deep research scaffold`, `long-context workflow` et `artifact-first output` dans `src/project_os_core/gateway/service.py`
- `Discord Autonomy No-Loss` deja pose et documente
- `Persona V2 + Context Integrity` deja pose et documente

### Gaps reels observes

#### 1. Le passage discussion -> action repose encore trop sur des prefixes

Aujourd'hui, `_TASK_PREFIX_HINTS` dans `src/project_os_core/gateway/promotion.py` contient surtout:

- `fais`
- `implement`
- `build`
- `create`
- `write`
- `run`
- `launch`
- `ouvre`

Risque:

- bonne precision sur des ordres explicites
- mauvaise couverture des formulations naturelles de fondateur

#### 2. Le systeme ne formalise pas encore le niveau de delegation

Aujourd'hui:

- un message peut etre vu comme `chat` ou `tasking`
- mais il manque une couche intermediaire du type `directive implicite`

Risque:

- soit il n'agit pas alors que l'intention est claire humainement
- soit il agit trop tot sur une formulation encore exploratoire

#### 3. Le contrat d'action n'est pas encore explicitement separe de la phrase utilisateur

Aujourd'hui:

- le texte du fondateur est route
- mais il n'y a pas encore de structure canonique du type:
  - objectif
  - perimetre
  - livrable attendu
  - niveau de risque
  - execution immediate ou approval requise

Risque:

- difficile de debugger les bascules
- difficile de mesurer pourquoi une phrase libre a declenche ou non une execution

#### 4. La clarification n'est pas encore calibree comme un produit UX

Aujourd'hui:

- le systeme sait gerer des clarifications
- mais il n'y a pas encore de doctrine simple du type `une seule question courte quand necessaire`

Risque:

- dialogue trop procedural
- fatigue de validation

## Cartographie externe

Cette section rend le plan portable.
Elle dit ce que les sources externes confirment, et comment on l'adapte a `Project OS`.

### OpenAI - Function calling et contrats stricts

Sources primaires:

- [Function Calling in the OpenAI API](https://help.openai.com/en/articles/8555517)
- [Human-in-the-loop - OpenAI Agents SDK](https://openai.github.io/openai-agents-python/human_in_the_loop/)
- [Introducing deep research](https://openai.com/index/introducing-deep-research/)

Ce qu'on recupere:

- transformer une intention libre en contrat structure avec `strict: true`
- separer la conversation utilisateur du contrat machine
- conserver un vrai `pause / approve / resume` pour les actions sensibles
- utiliser un workflow multi-etapes avec progression visible pour les taches longues

Ce qu'on n'importe pas:

- aucune dependance a un SDK agent OpenAI comme coeur canonique
- aucune obligation de faire du tool calling sur chaque tour

Decision:

- `ADAPT`

### Anthropic - Tool use naturel et explication avant action

Sources primaires:

- [How to implement tool use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/implement-tool-use)

Ce qu'on recupere:

- `tool_choice: auto` comme mode naturel par defaut
- possibilite pour le modele de donner du contexte en langage naturel avant l'action
- schema strict pour les outils quand on veut garantir l'entree

Ce qu'on n'importe pas:

- aucune logique qui force l'appel outil sur chaque demande
- aucune dependance a un orchestrateur Anthropic comme coeur

Decision:

- `ADAPT`

### AutoGen - Limites du HITL bloquant

Sources primaires:

- [Human-in-the-Loop - AutoGen](https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/tutorial/human-in-the-loop.html)

Ce qu'on recupere:

- un approval bloquant type `APPROVE` est acceptable pour des interactions tres courtes

Ce qu'on rejette:

- un mode d'approbation console-bloquant comme UX principale pour `Discord` mobile

Decision:

- `REJECT` comme UX principale
- `KEEP` comme rappel de contrainte de design

## Lecture nette des sources

Le consensus externe est coherent:

- la conversation utilisateur doit rester naturelle
- la machine doit convertir l'intention en structure exploitable
- les actions sensibles doivent pouvoir etre approuvees et reprises
- les traitements longs doivent avoir progression visible et reprise durable

Donc la bonne architecture n'est ni:

- un parseur de commandes
- ni un agent "magique" qui agit sans contrat

La bonne architecture est:

- `conversation libre`
- `extraction d'intention`
- `contrat d'action`
- `approval gate`
- `execution`
- `reporting`

## Cible produit

Par defaut, `Project OS` discute.

Il n'execute que quand:

- l'intention d'action est claire
- le risque est compatible
- le perimetre est suffisant
- ou une unique clarification courte a ferme l'ambiguite

L'impression cote fondateur doit etre:

- `je parle normalement`
- `Project OS comprend ce que je veux faire`
- `il agit quand il faut`
- `il me freine seulement quand il y a une vraie raison`

## Dimension orthogonale - Escalade de raisonnement et cout

Le `mode manager naturel` ne doit pas seulement decider `discussion vs execution`.
Il doit aussi savoir quand une conversation libre merite une voie de raisonnement plus chere, sans basculer silencieusement.

Exemple produit cible:

- discussion normale sur `Sonnet` ou la voie cheap par defaut
- quand la discussion devient architecturale, contradictoire, dense ou engageante:
  - `Project OS` propose une escalade vers `Opus`
  - il explique pourquoi
  - il affiche un cout estime
  - il demande un `go`
- pour un `deep research`, un audit, un gros plan ou une operation lourde:
  - il affiche `cout estime + temps estime`
  - il demande confirmation avant de lancer le pipeline couteux

### Regle produit dure

Ne jamais faire d'`auto-upgrade` silencieux vers une voie couteuse.

Le fondateur doit voir:

- pourquoi on propose de monter en gamme
- combien cela coute
- si c'est une simple escalade de raisonnement ou un vrai run lourd
- ce qu'il doit repondre pour continuer

### Ce qui existe deja dans le repo et qu'il faut reutiliser

- `router/service.py` sait deja calculer:
  - `mission_cost_class`
  - `budget_state`
  - `approval_gate`
  - `model_route`
  - `adaptive_model_route`
- `api_runs/service.py` sait deja produire un `RunContract` avec:
  - `estimated_cost_eur`
  - resume de contrat
  - approbation `go / stop`
- `docs/architecture/COST_OPTIMIZATION_STRATEGY.md` pose deja:
  - garde budget
  - estimation conservative
  - alertes
- `docs/architecture/RUN_COMMUNICATION_POLICY.md` pose deja:
  - message de cout utile
  - feedback lisible sur `Discord`

Decision:

- ne pas creer un second systeme parallele de cout
- brancher cette UX sur les primitives deja existantes

### Ce qu'il manque

Il manque une couche UX explicite entre:

- `la discussion libre`
- et `la montee vers une voie chere`

Cette couche doit produire un objet du style:

- `reasoning_route_current`
- `reasoning_route_recommended`
- `escalation_reason`
- `estimated_incremental_cost_eur`
- `estimated_total_cost_eur`
- `estimated_time_band`
- `requires_founder_go`

### Distinction produit a garder absolument

Il y a deux choses differentes:

- `escalade de raisonnement`
  - on change de modele ou de voie de calcul
  - pas forcement d'action sur le repo
- `execution de travail`
  - on lance un vrai run, un patch, un audit, une recherche lourde

Les deux peuvent demander `go`, mais pour des raisons differentes.

### Doctrine UX recommandee

#### Cas 1 - Escalade de raisonnement seule

Quand la discussion devient serieuse mais qu'on n'a pas encore besoin de lancer un run:

- afficher seulement `cout estime`
- ne pas surcharger avec un temps si l'incertitude est trop forte
- format cible:
  - `Je pense qu'Opus est le meilleur move pour la suite.`
  - `Cout estime: ~X EUR.`
  - `Reponds go si tu veux que je bascule.`

#### Cas 2 - Operation lourde

Quand on va lancer un audit, un gros plan, une synthese longue ou un workflow couteux:

- afficher `cout estime + temps estime`
- demander un `go`
- format cible:
  - `Pour lancer cette operation, cout estime: ~X EUR.`
  - `Temps estime: court / moyen / long.`
  - `Reponds go si tu veux que je lance.`

### Signaux de bascule recommandes

Proposer une escalade de raisonnement si plusieurs signaux sont vrais:

- discussion qui dure et se densifie
- arbitrage architectural
- demande de contradiction forte ou d'analyse multi-angles
- besoin de synthese longue ou de plan de haut niveau
- niveau d'incertitude trop eleve pour la voie cheap
- enjeu eleve mais encore sans action destructive

Ne pas proposer une escalade si:

- la demande est triviale
- la discussion est surtout sociale ou de statut
- la difference attendue de qualite est faible
- le budget est deja trop tendu

### Futureproofing recommande

Ne pas coder des prix en dur dans le prompt.

Utiliser:

- un catalogue de prix versionne cote runtime
- des `bands` de temps plutot que des promesses precises
- une estimation de cout incrementale et totale
- un message qui degrade proprement si l'estimation exacte n'est pas disponible

Objectif:

- permettre au fondateur de piloter depuis le telephone
- sans surprise de cout
- sans jargon runtime
- sans perdre le fil de la conversation

## Modele d'etats canonique

### 1. Discussion

Usage:

- exploration
- reaction
- brainstorm
- cadrage
- feedback

Signal:

- aucun engagement d'execution

Sortie:

- reponse conversationnelle
- options
- challenge
- prochain pas propose

### 2. Directive implicite

Usage:

- le fondateur indique une intention operative sans syntaxe imperative stricte

Exemples:

- `j'aimerais qu'on garde une trace de ca`
- `on part la-dessus`
- `tu peux me mettre ca propre`

Signal:

- il y a bien une attente de resultat
- mais le systeme doit encore formaliser le contrat d'action

Sortie:

- reformulation operative tres courte
- puis execution si le contrat est assez clair et non risqué
- sinon une seule clarification courte

### 3. Approval

Usage:

- action destructive
- cout fort
- changement irreversibile
- doute sur la cible

Signal:

- l'intention peut etre comprise
- mais l'autorisation ou la precision manque encore

Sortie:

- une question courte
- ou une demande de validation explicite

### 4. Execution

Usage:

- l'action est suffisamment claire et autorisee

Sortie:

- ack utile
- progression si long
- artefact si le livrable est long

### 5. Reporting

Usage:

- retour d'etat
- resultat
- echec
- reprise

Sortie:

- ce qui a ete fait
- ce qui reste
- si besoin, le livrable ou l'artefact joint

## Regles de bascule

### Discussion -> Directive implicite

Bascule si:

- le message contient une attente de livrable ou de delegation
- meme sans verbe imperatif direct

Indices:

- demande de garder une trace
- demande de preparation
- accord implicite sur une option suivie d'une attente de mise en oeuvre
- demande de concretisation d'une idee deja stabilisee

### Directive implicite -> Approval

Bascule si:

- la cible n'est pas assez claire
- le message est destructif
- la modification touche une zone sensible
- le cout ou la portee sont eleves

Regle UX:

- une seule question
- courte
- orientee fermeture

### Directive implicite -> Execution

Bascule si:

- objectif clair
- sortie attendue claire ou inferable
- risque bas ou moyen
- chemin de travail autorise

### Execution -> Reporting

Toujours.

Regle:

- ne jamais laisser un trou silencieux
- resultat compact sur Discord
- artefact joint si besoin

## Contrat d'action canonique

Ajouter un contrat machine explicite, distinct du message utilisateur.

Proposition de structure:

- `intent_kind`
- `delegation_level`
- `objective`
- `scope`
- `expected_output`
- `confidence`
- `risk_class`
- `needs_clarification`
- `needs_approval`
- `approval_reason`
- `execution_ready`

### Typologie recommandee

`intent_kind`:

- `discussion`
- `status_request`
- `decision_signal`
- `directive_implicit`
- `directive_explicit`
- `approval_response`
- `execution_report_followup`

`delegation_level`:

- `none`
- `explore`
- `prepare`
- `execute`
- `approve`

## Packs d'implementation

### Pack 1 - Intent Taxonomy And State Machine

But:

- poser les nouveaux etats canoniques
- remplacer la simple opposition `chat vs tasking`

Fichiers cibles:

- `src/project_os_core/models.py`
- `src/project_os_core/gateway/promotion.py`
- `src/project_os_core/gateway/service.py`

Livrables:

- nouveaux enums/types pour `intent_kind` et `delegation_level`
- classification plus riche
- transitions explicites documentees

### Pack 2 - Natural Directive Extraction

But:

- detecter les demandes implicites de travail
- reduire la dependance aux prefixes

Fichiers cibles:

- `src/project_os_core/gateway/promotion.py`
- `src/project_os_core/gateway/service.py`

Livrables:

- heuristiques plus larges
- extraction d'indices conversationnels
- bloc de metadata `directive_detection`

### Pack 3 - Action Contract And Clarification Gate

But:

- formaliser le contrat d'action
- calibrer quand il faut demander confirmation

Fichiers cibles:

- `src/project_os_core/models.py`
- `src/project_os_core/gateway/service.py`
- `src/project_os_core/router/service.py`

Livrables:

- dataclass `ActionContract`
- regles `execution_ready / needs_clarification / needs_approval`
- doctrine `one short blocking question`

### Pack 4 - Execution Handoff And Reporting UX

But:

- brancher le contrat d'action au pipeline existant
- garder une UX propre sur Discord
- integrer la proposition d'escalade cout-aware avant les voies cheres

Fichiers cibles:

- `src/project_os_core/gateway/service.py`
- `src/project_os_core/router/service.py`
- `integrations/openclaw/project-os-gateway-adapter/index.js`
- `src/project_os_core/api_runs/service.py`

Livrables:

- ack adapte au niveau d'engagement
- reporting compact
- artifacts si livrable long
- carte `escalade recommandee`
- cout estime visible avant `Opus` ou run lourd
- `go` fondateur qui convertit la proposition en route plus chere ou en vrai run

### Pack 5 - Evals And Smoke Tests

But:

- verifier la qualite du mode manager naturel
- verifier la lisibilite cout / escalade / approval sur mobile

Fichiers cibles:

- `tests/unit/test_gateway_prompt_ops.py`
- `tests/unit/test_gateway_and_orchestration.py`
- `tests/unit/test_openclaw_live.py`
- `tests/unit/test_api_run_service.py`

Jeu minimal de tests:

- message purement conversationnel ne lance rien
- demande implicite de preparation cree un contrat `prepare`
- demande implicite claire et sure devient `execute`
- demande ambigue produit une seule clarification
- demande destructive demande approval
- reporting final reste lisible sur Discord
- discussion serieuse propose `Opus` sans auto-bascule silencieuse
- reponse `go` accepte l'escalade couteuse
- reponse negative garde la voie cheap
- gros workflow affiche `cout estime + temps estime` avant lancement

## Parametres de decision recommandes

### Executer sans clarification

Seulement si:

- `confidence >= 0.80`
- `risk_class` faible ou modere
- `scope` inferable sans ambiguite majeure
- `expected_output` clairement deduisible

### Clarifier

Si:

- `0.45 <= confidence < 0.80`
- ou `scope` trop flou
- ou la cible materielle manque

### Bloquer pour approval

Si:

- action destructive
- cout anormal
- ecriture dans zone sensible
- changement irreversibile

## Exemples de comportement cible

### Exemple 1 - Discussion pure

Message:

- `je suis pas sur qu'on doive partir la-dessus`

Comportement:

- discussion
- challenge
- pas d'execution

### Exemple 2 - Directive implicite prepare

Message:

- `j'aimerais qu'on garde une trace de ca dans le repo`

Comportement:

- detection `directive_implicit`
- contrat `delegation_level=prepare` ou `execute` selon le contexte
- si clair: creation du livrable
- sinon une question courte sur le format ou l'emplacement

### Exemple 3 - Directive implicite execute

Message:

- `ok on part la-dessus, mets-moi ca propre dans un md`

Comportement:

- contrat d'action
- execution
- reporting + artefact

### Exemple 4 - Approval

Message:

- `supprime les anciens brouillons et remplace les docs`

Comportement:

- demande de validation explicite
- pas d'action avant approval

## Ordre recommande

1. `Pack 1 - Intent Taxonomy And State Machine`
2. `Pack 2 - Natural Directive Extraction`
3. `Pack 3 - Action Contract And Clarification Gate`
4. `Pack 4 - Execution Handoff And Reporting UX`
5. `Pack 5 - Evals And Smoke Tests`

## KPIs de sortie

- taux de bonne classification `discussion vs directive`
- taux de clarification inutile
- taux de faux positifs d'execution
- taux de faux negatifs de delegation
- delai moyen entre demande claire et ack utile
- satisfaction de lecture Discord sur les reportings longs

## Ce qu'il ne faut pas faire

- ne pas revenir a un bot a commandes rigides
- ne pas faire agir le systeme sur toute phrase un peu volontaire
- ne pas exiger `APPROVE` comme UX standard mobile
- ne pas melanger le message utilisateur brut et le contrat d'action machine
- ne pas casser la `single voice`

## Ancrage repo

Cette roadmap doit vivre avec:

- `docs/roadmap/PERSONA_V2_CONTEXT_INTEGRITY_PLAN.md`
- `docs/roadmap/DISCORD_AUTONOMY_NO_LOSS_PLAN.md`
- `docs/workflow/DEEP_RESEARCH_PROTOCOL.md`
- `docs/architecture/WORKER_CAPABILITY_CONTRACTS.md`

## Sources

### Sources locales

- [AGENTS.md](../../AGENTS.md)
- [DEEP_RESEARCH_PROTOCOL.md](../workflow/DEEP_RESEARCH_PROTOCOL.md)
- [PERSONA_V2_CONTEXT_INTEGRITY_PLAN.md](./PERSONA_V2_CONTEXT_INTEGRITY_PLAN.md)
- [DISCORD_AUTONOMY_NO_LOSS_PLAN.md](./DISCORD_AUTONOMY_NO_LOSS_PLAN.md)
- [COST_OPTIMIZATION_STRATEGY.md](../architecture/COST_OPTIMIZATION_STRATEGY.md)
- [RUN_COMMUNICATION_POLICY.md](../architecture/RUN_COMMUNICATION_POLICY.md)
- [promotion.py](../../src/project_os_core/gateway/promotion.py)
- [service.py](../../src/project_os_core/gateway/service.py)
- [service.py](../../src/project_os_core/router/service.py)
- [service.py](../../src/project_os_core/api_runs/service.py)
- [research_scaffold.py](../../src/project_os_core/research_scaffold.py)

### Sources externes

- [Function Calling in the OpenAI API](https://help.openai.com/en/articles/8555517)
- [Human-in-the-loop - OpenAI Agents SDK](https://openai.github.io/openai-agents-python/human_in_the_loop/)
- [Introducing deep research](https://openai.com/index/introducing-deep-research/)
- [How to implement tool use - Claude API Docs](https://platform.claude.com/docs/en/agents-and-tools/tool-use/implement-tool-use)
- [Human-in-the-Loop - AutoGen](https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/tutorial/human-in-the-loop.html)
