# Discord Facade And Continuity Patch Plan

## Statut

Feuille de route canonique proposee.

Note de cadrage:

- pour la doctrine `single visible agent / multi-surface / Discord = remote conversation / Project OS.exe = control plane`, lire aussi `docs/roadmap/DISCORD_FOUNDER_SURFACE_REPAIR_V2_PLAN.md`

Ce document organise le patch conversationnel demande pour `Project OS`.
Il ne remplace pas:

- `docs/roadmap/NATURAL_MANAGER_MODE_PLAN.md`
- `docs/roadmap/PERSONA_V2_CONTEXT_INTEGRITY_PLAN.md`
- `docs/roadmap/DISCORD_AUTONOMY_NO_LOSS_PLAN.md`

Il sert de roadmap d'execution resserree pour un patch cible:

- facade conversationnelle plus naturelle
- continuite de travail plus credible
- preservation stricte des systemes produit deja voulus

## But

Livrer un patch global, mergeable en plusieurs packs, qui:

- masque la tuyauterie interne inutile dans la conversation normale
- garde les signaux utiles de presence et de pilotage
- preserve les confirmations volontaires liees au produit
- fiabilise une continuite durable en trois couches
- n'ouvre pas de reecriture generale
- ne touche pas a `Deep Research`

Recadrage directeur:

- on ne pense plus `patch Discord isole`
- on pense `agent unique multi-surface`
- `Discord` = `remote conversation plane`
- `Project OS.exe` = `operational control plane`
- la continuite cible est `founder-session first`

## Point de depart reel

### Ce qui existe deja dans le repo

- une frontiere explicite entre conversation normale et `deep research` dans `AGENTS.md` et `docs/workflow/DEEP_RESEARCH_PROTOCOL.md`
- une persona canonique et une couche de contexte deja posees via `docs/roadmap/PERSONA_V2_CONTEXT_INTEGRITY_PLAN.md`
- une roadmap `manager naturel` qui couvre deja l'intention libre, le contrat d'action et les gates de clarification dans `docs/roadmap/NATURAL_MANAGER_MODE_PLAN.md`
- une logique `Discord no-loss` et un fallback `artifact_summary / PDF` deja assumes dans `docs/roadmap/DISCORD_AUTONOMY_NO_LOSS_PLAN.md`
- des policies de cout et de reporting deja posees dans `docs/architecture/COST_OPTIMIZATION_STRATEGY.md` et `docs/architecture/RUN_COMMUNICATION_POLICY.md`
- une doctrine `single visible voice` et une identite agent unique dans `docs/architecture/AGENT_IDENTITY_AND_CHANNEL_MODEL.md` et `docs/integrations/DISCORD_OPERATING_MODEL.md`
- une infrastructure memoire riche, mais encore inegalement exploitee dans la boucle Discord

### Ce que ce patch doit corriger

- la fuite de la tuyauterie interne dans les reponses normales
- la confusion entre signaux utiles de produit et details inutiles de pipeline
- la fragilite de la continuite percue sur plusieurs jours
- la dispersion des regles visibles entre plusieurs surfaces de reponse

### Ce que ce patch ne doit pas changer

- la pipeline `Deep Research`
- le mode `deep research` / `recherche approfondie`
- le systeme de modes existant
- les niveaux `simple / avance / extreme`
- l'affichage des prix quand il est volontairement prevu
- les confirmations de changement de modele
- les confirmations liees au passage vers une autre IA ou un autre mode
- le fallback `artifact_summary / PDF`

## Regles d'architecture

### System invariants

`Project OS` doit toujours garantir:

- `runtime truth`
  - pas de bluff
  - pas de promesse d'execution non verifiee
- `artifact evidence`
  - un livrable, un run ou une execution longue doivent rester prouvables
- `explicit cost disclosure when required`
  - le cout reste visible quand le produit le demande vraiment
- `deep research pipeline isolation`
  - `Deep Research` reste un systeme distinct de la conversation normale
- `single visible agent identity`
  - une seule identite publique, meme si plusieurs modeles ou lanes existent
- `no-loss Discord delivery`
  - un incident de delivery ne doit pas faire disparaitre le travail produit
- `control-plane data stays out of normal chat unless explicitly requested`
- `cross-surface continuity must not create contradictory agent state`

Ces invariants sont superieurs au patch.
Si un lot les fragilise, le lot doit etre recadre ou coupe.

### Table canonique des cas visibles

### Question normale

- montrer:
  - reponse utile
  - presence utile
- cacher:
  - provider
  - API
  - routing
  - pipeline
  - taxonomie interne
- confirmer:
  - rien

### Approval reel

- montrer:
  - objectif
  - livrable attendu
  - cout estime utile
  - temps estime utile
- cacher:
  - route_reason
  - pipeline interne
  - taxonomie inutile
- confirmer:
  - `go / stop`

### Changement de modele

- montrer:
  - modele ou IA cible
  - cout estime si prevu par le produit
  - raison utile de la bascule
- cacher:
  - routing interne detaille
  - pipeline interne
- confirmer:
  - confirmation explicite

### Deep research explicite

- montrer:
  - modes `Deep Research`
  - cout estime
  - temps estime
- cacher:
  - pipeline interne non necessaire
- confirmer:
  - confirmation explicite

### Reponse moyenne

- montrer:
  - reponse lisible dans Discord
  - presence utile
  - mention d'artefact seulement si necessaire
- cacher:
  - internals de delivery
  - metadata technique
- confirmer:
  - rien

### Incident delivery

- montrer:
  - incident formule humainement
  - prochain pas
  - etat de reprise
- cacher:
  - trace brute adapter
  - payload technique
- confirmer:
  - rien

### 1. Facade naturelle, pas opacite totale

La cible n'est pas un bot muet ou opaque.
La cible est une facade naturelle, lisible et humaine.

Donc:

- on masque `provider`, `API`, `routing`, `pipeline`, `route_reason`, `query_scope`, labels techniques et taxonomie interne quand ils ne servent pas la decision utilisateur
- on garde les signaux utiles de presence, dont l'indicateur d'ecriture
- on garde les confirmations importantes quand elles sont voulues par le produit
- on montre les details techniques seulement sur demande, ou quand ils servent une vraie decision

### 2. `Deep Research` reste un systeme a part

Le patch ne doit pas normaliser ou diluer `Deep Research`.

Regle dure:

- si le fondateur ecrit `deep research` ou `recherche approfondie`, le systeme doit continuer a proposer les modes `Deep Research` existants
- la UX de `Deep Research` reste gouvernee par `docs/workflow/DEEP_RESEARCH_PROTOCOL.md`

### 3. Les confirmations volontaires restent visibles

Le patch ne doit pas "nettoyer" les disclosures produit legitimes.

Regle dure:

- une bascule vers une autre IA ou un autre modele continue a demander confirmation
- le cout estime continue a etre affiche dans les cas ou le produit le veut
- une operation couteuse ou sensible continue a produire la confirmation voulue

### 4. La continuite cible est une memoire en trois couches

Le patch ne vise pas une "memoire courte".
Il vise une continuite durable et credible:

- memoire conversationnelle immediate
- memoire de continuite du thread ou de la mission
- memoire projet long terme

Le bon resultat percu est:

- `Project OS` sait ce qu'on fait depuis plusieurs jours
- il connait les decisions recentes
- il ne donne pas l'impression d'avoir oublie le travail en cours

Corollaire:

- la continuite ne doit plus etre pensee seulement par thread Discord
- elle doit suivre une `founder session spine`
- partageable entre Discord et desktop sans seconde personnalite

### 5. Pas de seconde verite, pas de reecriture

Le patch doit:

- extraire
- aligner
- resserrer
- proteger

Il ne doit pas:

- recreer un nouveau pipeline parallele
- dupliquer les docs canoniques existantes
- lancer une reecriture de `gateway`, `api_runs`, `database` ou `models`

## Pourquoi cet ordre

L'ordre retenu suit une logique de risque:

1. figer d'abord la frontiere entre ce qu'on masque et ce qu'on preserve
2. nettoyer ensuite la facade standard hors `Deep Research`
3. ameliorer le rendu Discord moyen format et le delivery humain
4. fiabiliser ensuite la continuite proche et la continuite thread/mission
5. brancher enfin la continuite projet long terme et les garde-fous durables

Pourquoi pas l'inverse:

- commencer par la memoire longue sans contrat visible stable augmenterait les faux rappels et la confusion
- commencer par un refactor structurel elargirait le scope trop tot
- toucher `Deep Research` ou le systeme de modes au premier lot casserait des systemes volontaires

## Relecture de vision des packs

- `Pack 1 - Surface split`
  - separer clairement `chat plane` et `control plane`
- `Pack 2 - Clarification and referent anchoring`
  - dernier referent explicite gagne
  - pas de boucle de clarification inutile
- `Pack 3 - Discord medium format and human delivery`
  - Discord court, utile, actionnable
- `Pack 4 - Founder session spine`
  - continuite unique entre Discord et desktop
- `Pack 5 - Cross-surface evals and regression rails`
  - tests Discord seul, desktop seul, Discord <-> desktop

## Packs

- [x] `Pack 1 - Visibility Contract And Protected Cases`
- [x] `Pack 2 - Standard Reply Cleanup Outside Deep Research`
- [x] `Pack 3 - Discord Medium Format And Human Delivery`
- [x] `Pack 4 - Immediate And Thread Continuity`
- [x] `Pack 5 - Project Continuity, Retention And Regression Rails`

## Pack 1 - Visibility Contract And Protected Cases

### Statut

`IMPLEMENTE`

### Objet

Figer la regle canonique `masquer / garder / montrer sur demande / toujours confirmer` pour toutes les reponses standard hors `Deep Research`.

### Probleme vise

Aujourd'hui, les surfaces visibles melangent:

- la presence utile du bot
- des controles produit legitimes
- et de la tuyauterie interne inutile

Sans contrat explicite, un nettoyage UX peut casser des disclosures voulus.

### Pourquoi maintenant

Ce pack vient en premier parce qu'il protege tout le patch.
Il fixe ce qu'on a le droit de nettoyer et ce qu'on doit preserver.

### Livrables effectivement poses

- table canonique des cas visibles dans cette roadmap
- section `System invariants` dans cette roadmap
- module `src/project_os_core/operator_visibility_policy.py`
- seam minimal branche dans:
  - `src/project_os_core/gateway/service.py`
  - `src/project_os_core/api_runs/service.py`
- tests cibles:
  - `tests/unit/test_operator_visibility_policy.py`
  - cas proteges verifies aussi dans `tests/unit/test_gateway_and_orchestration.py`

### Reuse explicite

- `docs/roadmap/NATURAL_MANAGER_MODE_PLAN.md`
- `docs/roadmap/PERSONA_V2_CONTEXT_INTEGRITY_PLAN.md`
- `docs/architecture/RUN_COMMUNICATION_POLICY.md`
- `docs/architecture/COST_OPTIMIZATION_STRATEGY.md`
- `docs/integrations/DISCORD_OPERATING_MODEL.md`

### Carte de surfaces

- safe-ish:
  - `docs/roadmap/DISCORD_FACADE_AND_CONTINUITY_PATCH_PLAN.md`
  - `tests/unit/`
  - `docs/workflow/DISCORD_MESSAGE_TEMPLATES.md`
- blast radius eleve:
  - `src/project_os_core/gateway/service.py`
  - `src/project_os_core/api_runs/service.py`
- hors perimetre:
  - `src/project_os_core/deep_research.py`
  - `src/project_os_core/research_scaffold.py`
  - `src/project_os_core/router/service.py`
  - `src/project_os_core/database.py`
  - `src/project_os_core/models.py`

### Ce qui doit changer

- produire une table canonique des disclosures visibles
- lister noir sur blanc:
  - ce qu'on masque par defaut
  - ce qu'on garde visible
  - ce qu'on montre seulement sur demande
  - ce qu'on confirme toujours
- verrouiller les cas proteges:
  - `deep research` explicite
  - changement de modele
  - changement d'IA
  - cout volontaire
  - approval reel

### Ce qui ne doit surtout pas changer

- `Deep Research`
- systeme de modes existant
- `simple / avance / extreme`
- confirmations de changement de modele ou d'IA
- prix visibles dans les cas volontaires
- indicateur d'ecriture

### Criteres d'acceptation

- un message standard ne montre plus `provider`, `API`, `route_reason`, `query_scope`, pipeline interne ou taxonomie systeme inutile
- un changement de modele reste confirme et cote
- `deep research` explicite continue a ouvrir les modes existants
- les disclosures utiles restent visibles quand ils servent une decision reelle

### Risques principaux

- masquer un signal utile a la decision
- confondre disclosure legitime et bruit de tuyauterie

### Dependances

- aucune

### Rollback contract

Revert immediat si un des symptomes suivants apparait:

- un cas protege perd une confirmation volontaire
- `deep research` explicite ne declenche plus les modes attendus
- un changement de modele ne montre plus le cout ou la confirmation prevus
- une reponse standard devient plus opaque qu'utile

### Case de fermeture visee

- `Patch Discord facade - Pack 1 - Visibility Contract`

### Etat de fermeture

`FERME`

## Pack 2 - Standard Reply Cleanup Outside Deep Research

### Statut

`IMPLEMENTE`

### Objet

Nettoyer le langage, le contenu visible et les disclosures des reponses standard hors `Deep Research`.

### Probleme vise

Les conversations normales exposent encore:

- labels techniques
- details de pipeline
- taxonomie systeme
- formulations trop "bot / process"

Le probleme de ce pack est un probleme de `langage / contenu / disclosure`.
Ce n'est pas encore un pack de `format / chunking / delivery`.

### Pourquoi maintenant

Une fois le contrat visible fige, ce pack livre le gain UX le plus immediate sans toucher aux systemes profonds.

### Reuse explicite

- `docs/roadmap/PERSONA_V2_CONTEXT_INTEGRITY_PLAN.md`
- `docs/roadmap/NATURAL_MANAGER_MODE_PLAN.md`
- `src/project_os_core/gateway/service.py`
- `src/project_os_core/api_runs/service.py`
- `docs/workflow/DISCORD_MESSAGE_TEMPLATES.md`

### Carte de surfaces

- safe-ish:
  - `src/project_os_core/operator_visibility_policy.py`
  - `tests/unit/test_operator_visibility_policy.py`
  - `docs/workflow/DISCORD_MESSAGE_TEMPLATES.md`
- blast radius eleve:
  - `src/project_os_core/gateway/service.py`
  - `src/project_os_core/api_runs/service.py`
- hors perimetre:
  - `src/project_os_core/deep_research.py`
  - `src/project_os_core/research_scaffold.py`
  - `src/project_os_core/router/service.py`
  - `src/project_os_core/session/state.py`

### Ce qui doit changer

- clarifications standard
- reponses de statut simples
- replies guardian standard
- formulations visibles qui exposent inutilement:
  - `API utilisee`
  - `mode selectionne`
  - `profil recommande`
  - labels locaux
  - chemins techniques
  - details de routing
  - details de pipeline

### Ce qui ne doit surtout pas changer

- confirmations volontaires de changement de modele
- confirmations de bascule vers une autre IA
- affichage de prix volontaire
- approvals reellement necessaires
- flux et UX `Deep Research`
- transport Discord
- regles de chunking
- fallback `artifact_summary / PDF`

### Criteres d'acceptation

- les clarifications deviennent contextuelles et courtes
- les reponses standard n'exposent plus de tuyauterie inutile
- le ton reste aligne sur la persona canonique
- les cas proteges du `Pack 1` restent intacts

### Risques principaux

- rendre la facade trop opaque
- casser une disclosure produit voulue si le perimetre derive
- melanger par erreur le nettoyage de langage avec le format de delivery

### Dependances

- `Pack 1`

### Livrables effectivement poses

- extension du seam `src/project_os_core/operator_visibility_policy.py`
- branchement du seam dans `src/project_os_core/gateway/service.py`
- nettoyage des reponses standard:
  - accusés de lancement standard
  - messages de blocage standard
  - resumes post-approval standard hors `Deep Research`
  - resumes `status_request`
  - ack de doublon d'entree
- tests cibles et regression update dans:
  - `tests/unit/test_operator_visibility_policy.py`
  - `tests/unit/test_gateway_and_orchestration.py`

### Rollback contract

Revert immediat si un des symptomes suivants apparait:

- les approvals standard perdent une information produit necessaire
- une disclosure volontaire disparait
- les reponses standard cassent les cas proteges du `Pack 1`
- la facade standard devient incoherente entre deux surfaces voisines

### Case de fermeture visee

- `Patch Discord facade - Pack 2 - Standard Reply Cleanup`

## Pack 3 - Discord Medium Format And Human Delivery

### Statut

`IMPLEMENTE`

### Objet

Garder les reponses moyennes dans Discord via un meilleur format de sortie et un delivery plus humain, sans changer le contenu produit valide par `Pack 2`.

### Probleme vise

Aujourd'hui, les reponses moyennes tombent trop vite vers:

- cartes trop techniques
- `artifact_summary / PDF` trop precoce
- messages de delivery trop "transport"

Le probleme de ce pack est un probleme de `format / chunking / cards / delivery`.
Ce n'est pas un pack de redefinition du langage visible.

### Pourquoi maintenant

Une facade nettoyee sans bon rendu Discord resterait une amelioration inachevee.
Ce pack ferme le ressenti "le systeme me sort du chat trop tot".

### Reuse explicite

- `docs/roadmap/DISCORD_AUTONOMY_NO_LOSS_PLAN.md`
- `docs/architecture/RUN_COMMUNICATION_POLICY.md`
- `integrations/openclaw/project-os-gateway-adapter/index.js`
- `src/project_os_core/gateway/service.py`
- `src/project_os_core/api_runs/service.py`

### Carte de surfaces

- safe-ish:
  - `src/project_os_core/operator_visibility_policy.py`
  - `tests/unit/`
- blast radius eleve:
  - `src/project_os_core/api_runs/service.py`
  - `integrations/openclaw/project-os-gateway-adapter/index.js`
  - `src/project_os_core/gateway/service.py`
- hors perimetre:
  - `src/project_os_core/deep_research.py`
  - `src/project_os_core/router/service.py`
  - `src/project_os_core/models.py`

### Ce qui doit changer

- vrai palier `thread_chunked_text` pour les reponses moyennes
- cartes Discord compactes
- formulation humaine des erreurs de delivery
- maintien des signaux utiles de presence pendant execution
- regles de format entre `inline`, `notification_card` et `artifact_summary`

### Ce qui ne doit surtout pas changer

- fallback `artifact_summary / PDF`
- no-loss delivery
- confirmations cout / modele voulues
- pipeline `Deep Research`
- contrat visible de disclosure fige par `Pack 1`
- contenu conversationnel deja valide par `Pack 2`

### Criteres d'acceptation

- une reponse moyenne reste lisible dans le chat
- le PDF reste un fallback utile, pas un reflexe premature
- les erreurs Discord ne montrent plus la tuyauterie brute
- les signaux de presence utiles restent visibles

### Risques principaux

- chunking trop verbeux
- regression de delivery
- degradation du fallback long
- chevauchement de perimetre avec `Pack 2`

### Dependances

- `Pack 1`
- `Pack 2`

### Livrables effectivement poses

- palier explicite `thread_chunked_text` dans `src/project_os_core/gateway/service.py`
- seuils de fallback `artifact_summary` repousses pour garder plus de reponses moyennes dans Discord
- cartes et livraisons operateur compactees dans `src/project_os_core/operator_visibility_policy.py`
- notices d'echec Discord humanisees dans `integrations/openclaw/project-os-gateway-adapter/index.js`
- tests cibles et regression update dans:
  - `tests/unit/test_operator_visibility_policy.py`
  - `tests/unit/test_gateway_context_builder.py`

### Rollback contract

Revert immediat si un des symptomes suivants apparait:

- les reponses moyennes rebasculent trop tot en `artifact_summary`
- les incidents de delivery redeviennent techniques ou bruyants
- le `no-loss delivery` se degrade
- les signaux utiles de presence disparaissent

### Case de fermeture visee

- `Patch Discord facade - Pack 3 - Medium Format Delivery`

## Pack 4 - Immediate And Thread Continuity

### Statut

`IMPLEMENTE`

### Objet

Fiabiliser la memoire conversationnelle immediate et la memoire de continuite du thread ou de la mission.

### Probleme vise

Le bot suit deja le contexte proche, mais:

- le `working set` peut etre bruite
- des follow-ups courts peuvent etre mal interpretes
- les decisions recentes et livrables en cours ne sont pas assez robustement rappeles

### Pourquoi maintenant

La continuite durable n'est credible que si le contexte proche est deja propre.
Ce pack doit venir avant l'injection de rappel projet long terme.

### Livrables effectivement poses

- enrichissement du ledger thread dans `src/project_os_core/gateway/stateful.py`:
  - `questions` inbound capturees
  - `decisions recentes` deduites des reponses
  - `next_step` proche extrait des reponses
- enrichissement du `working set` dans `src/project_os_core/gateway/stateful.py`:
  - `Sujet actif`
  - `Prochain pas proche`
  - `Decisions recentes`
  - reduction du bruit sur les follow-ups courts ambigus
- regle anti-hallucination memoire branchee dans `src/project_os_core/gateway/stateful.py`:
  - matching de hints sur vrais mots/expressions
  - clarification uniquement s'il existe un ancrage de rappel reel
  - `low recall confidence -> clarify`
- resume du ledger enrichi dans `src/project_os_core/gateway/context_builder.py`
- branche de clarification cerveau ajoutee dans `src/project_os_core/gateway/service.py`
- persistence des reponses `inline_text` et `thread_chunked_text` dans le ledger pour soutenir les follow-ups
- tests cibles:
  - `tests/unit/test_gateway_context_builder.py`
  - `tests/unit/test_gateway_and_orchestration.py`

### Reuse explicite

- `docs/roadmap/NATURAL_MANAGER_MODE_PLAN.md`
- `docs/roadmap/PERSONA_V2_CONTEXT_INTEGRITY_PLAN.md`
- `src/project_os_core/gateway/stateful.py`
- `src/project_os_core/gateway/context_builder.py`
- `src/project_os_core/session/state.py`

### Carte de surfaces

- safe-ish:
  - `src/project_os_core/gateway/stateful.py`
  - `src/project_os_core/gateway/context_builder.py`
  - `tests/unit/`
- blast radius eleve:
  - `src/project_os_core/session/state.py`
  - `src/project_os_core/gateway/service.py`
- hors perimetre:
  - `src/project_os_core/deep_research.py`
  - `src/project_os_core/memory/store.py`
  - `src/project_os_core/memory/os_service.py`
  - `src/project_os_core/database.py`

### Ce qui doit changer

- desambiguisation avant callback faible
- nettoyage du `working set`
- meilleure continuite de thread et de mission
- rappel fiable des decisions recentes, artefacts actifs, livrables en cours, prochaines etapes proches

### Regle anti-hallucination memoire

Si la confiance de rappel memoire est faible:

- demander une clarification courte
- ne jamais fabriquer une continuite
- ne jamais convertir un pronom vague en rappel certain

Regle dure:

- `low recall confidence -> clarify`
- `never fabricate continuity`

### Ce qui ne doit surtout pas changer

- pas de memoire sociale envahissante
- pas de cross-thread implicite sur signal faible
- pas d'injection massive de memoire brute
- pas de running gags persistants

### Criteres d'acceptation

- le bot sait ce qu'on fait dans le thread ou la mission
- il sait ce qui a ete fait recemment et ce qui vient ensuite
- il clarifie quand une reference est trop vague
- il ne produit pas de faux rappels absurdes
- il n'invente jamais une continuite sur rappel faible

### Risques principaux

- sur-interpretation de messages courts
- confiance excessive sur un rappel referentiel

### Dependances

- `Pack 1`
- `Pack 5` commence a preparer les cas de non-regression

### Rollback contract

Revert immediat si un des symptomes suivants apparait:

- hausse des faux rappels
- hausse des clarifications absurdes
- continuite plus confiante mais moins exacte
- references vagues resolues sans preuve suffisante

### Case de fermeture visee

- `Patch Discord facade - Pack 4 - Immediate Thread Continuity`

## Pack 5 - Project Continuity, Retention And Regression Rails

### Statut

`IMPLEMENTE`

### Objet

Brancher une continuite projet long terme exploitable et poser les garde-fous durables de non-regression.

### Probleme vise

Le bot doit pouvoir donner l'impression credible:

- qu'il sait ce qu'on fait depuis plusieurs jours
- qu'il connait les dernieres decisions
- qu'il sait ce qu'on a fait les 5 derniers jours
- qu'il sait ce qu'on va faire dans les prochains jours

Sans:

- devenir creepy
- rappeler n'importe quoi
- casser la privacy

### Pourquoi maintenant

Ce pack vient en dernier car la memoire longue n'est utile que si:

- la facade visible est stabilisee
- la continuite proche est fiable
- les cas a preserver sont deja verrouilles

### Livrables effectivement poses

- seam `project continuity brief` dans `src/project_os_core/memory/os_service.py`:
  - decisions recentes bornees
  - thoughts utiles bornees
  - gaps differes / prochains jalons bornes
  - runs recents relies quand le contexte les justifie
  - retention de lecture explicite `5 jours / clean only / top N`
- injection de `Continuite projet recente` dans:
  - `src/project_os_core/gateway/context_builder.py`
  - `src/project_os_core/gateway/service.py`
- branchement de `MemoryOSService` dans `src/project_os_core/services.py`
- policy documentaire explicite dans `docs/architecture/HANDOFF_MEMORY_POLICY.md`
- tests cibles et rails de non-regression dans:
  - `tests/unit/test_memory_os.py`
  - `tests/unit/test_gateway_context_builder.py`
  - verification des cas proteges existants dans `tests/unit/test_gateway_and_orchestration.py`

### Reuse explicite

- `docs/architecture/HANDOFF_MEMORY_POLICY.md`
- `src/project_os_core/memory/store.py`
- `src/project_os_core/memory/os_service.py`
- `src/project_os_core/gateway/context_builder.py`
- `src/project_os_core/gateway/stateful.py`

### Carte de surfaces

- safe-ish:
  - `tests/unit/`
  - `docs/roadmap/`
  - `docs/architecture/HANDOFF_MEMORY_POLICY.md`
- blast radius eleve:
  - `src/project_os_core/memory/store.py`
  - `src/project_os_core/memory/os_service.py`
  - `src/project_os_core/gateway/context_builder.py`
  - `src/project_os_core/gateway/stateful.py`
- hors perimetre:
  - `src/project_os_core/deep_research.py`
  - `src/project_os_core/router/service.py`
  - `src/project_os_core/database.py`
  - `src/project_os_core/models.py`

### Ce qui doit changer

- branchement d'une continuite projet long terme utile et borne
- rappel limite des decisions stables et du contexte projet recent
- policy de retention et de suppression ciblee
- rails de non-regression sur:
  - conversation standard
  - `deep research` explicite
  - changement de modele
  - cout volontaire
  - reponse moyenne Discord
  - callbacks memoire
- suite d'evals conversationnelles explicites:
  - `golden transcripts`
  - `conversation eval suite`
  - `deep research trigger tests`
  - `model switch confirmation tests`

### Ce qui ne doit surtout pas changer

- pas de memoire sociale durable non bornee
- pas de rappel cross-thread social automatique
- pas de suppression des confirmations produit voulues
- pas de changement de pipeline `Deep Research`

### Criteres d'acceptation

- le bot sait resumer le travail recent de facon credible
- il rappelle les decisions stables sans bruit inutile
- il ne produit pas de rappel creepy ou faux sur signal faible
- les cas proteges restent verts en non-regression
- les suites d'evals conversationnelles couvrent les cas UX critiques du patch

### Risques principaux

- dette privacy
- faux rappel durable
- suite de tests trop rigide

### Dependances

- `Pack 1`
- `Pack 2`
- `Pack 3`
- `Pack 4`

### Rollback contract

Revert immediat si un des symptomes suivants apparait:

- rappel projet long terme faux ou creepy
- regression sur `deep research` explicite
- regression sur changement de modele ou cout volontaire
- perte de confiance visible dans la continuite du travail recent

### Case de fermeture visee

- `Patch Discord facade - Pack 5 - Project Continuity And Regression Rails`

## Ordre de livraison concret

1. `Pack 1 - Visibility Contract And Protected Cases`
2. `Pack 2 - Standard Reply Cleanup Outside Deep Research`
3. `Pack 3 - Discord Medium Format And Human Delivery`
4. `Pack 4 - Immediate And Thread Continuity`
5. `Pack 5 - Project Continuity, Retention And Regression Rails`

## Ce qu'il ne faut pas modifier au premier chantier

Au `Pack 1`, il est interdit de modifier:

- la pipeline `Deep Research`
- le mode `deep research` / `recherche approfondie`
- le systeme de modes existant
- les niveaux `simple / avance / extreme`
- l'affichage des prix dans les cas volontaires
- les confirmations de changement de modele
- les confirmations de bascule vers une autre IA ou un autre mode
- le fallback `artifact_summary / PDF`
- la logique coeur de routing
- les garde-fous d'ecriture

Le `Pack 1` ne doit faire qu'une chose:

- figer la frontiere visible du patch

## Premier pack concret a lancer

Le premier pack concret a lancer est:

- `Pack 1 - Visibility Contract And Protected Cases`

Livrable attendu:

- une table canonique de disclosure
- une liste de cas proteges
- une baseline de non-regression minimum

Cas obligatoires a verrouiller:

- conversation standard simple
- clarification standard
- approval reel
- demande explicite `deep research`
- demande explicite de changement de modele
- cas avec cout volontaire visible

## Sources

### Sources locales

- [AGENTS.md](../../AGENTS.md)
- [NATURAL_MANAGER_MODE_PLAN.md](./NATURAL_MANAGER_MODE_PLAN.md)
- [PERSONA_V2_CONTEXT_INTEGRITY_PLAN.md](./PERSONA_V2_CONTEXT_INTEGRITY_PLAN.md)
- [DISCORD_AUTONOMY_NO_LOSS_PLAN.md](./DISCORD_AUTONOMY_NO_LOSS_PLAN.md)
- [DEEP_RESEARCH_PROTOCOL.md](../workflow/DEEP_RESEARCH_PROTOCOL.md)
- [RUN_COMMUNICATION_POLICY.md](../architecture/RUN_COMMUNICATION_POLICY.md)
- [COST_OPTIMIZATION_STRATEGY.md](../architecture/COST_OPTIMIZATION_STRATEGY.md)
- [AGENT_IDENTITY_AND_CHANNEL_MODEL.md](../architecture/AGENT_IDENTITY_AND_CHANNEL_MODEL.md)
- [HANDOFF_MEMORY_POLICY.md](../architecture/HANDOFF_MEMORY_POLICY.md)
- [DISCORD_OPERATING_MODEL.md](../integrations/DISCORD_OPERATING_MODEL.md)

### Cartographie externe

Aucune recherche externe supplementaire n'est necessaire pour cette roadmap.

Decision:

- `KEEP` la base repo-first et audit-first
- `ADAPT` l'ordre et le perimetre des chantiers existants
- `DEFER` tout refactor structurel profond
