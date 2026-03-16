# Audit Project OS 2026-03-15 : 6 améliorations concrètes pour fiabiliser deep research, orchestration et sécurité

## Statut

- `completed`
- genere le 2026-03-16T00:05:41.051959+00:00
- type: `audit`
- seo_slug: `pour-un-audit-de-mon-projet`

## Question de recherche

- recherche appronfondie  pour un audit de mon projet de ce qu'on pourrait ameliorer

## Synthese

- Le repo est assez mûr pour un audit de hardening, pas pour une réarchitecture totale. Les meilleures améliorations pour Project OS aujourd'hui sont : 1) standardiser les longs runs sur Responses + exécution asynchrone + validation stricte, 2) poser une vraie colonne vertébrale de traces locales via OpenTelemetry, 3) transformer les prompts et dossiers en surface testée en continu, 4) verrouiller la supply chain GitHub, puis 5) seulement étudier les patterns de durabilité type Temporal avant toute adoption d'un moteur externe. Sur les écosystèmes inspectés, je n'ai pas trouvé de fork plus fort que les upstreams officiels ; les satellites utiles existent, mais ils sont complémentaires, pas remplaçants.

## Pourquoi on fait ca

- Le repo est en phase active sur `deep_research`, `gateway`, `api_runs` et `session`, donc les contrats d'exécution sont encore faciles à durcir avant gel plus profond de l'architecture.
- OpenAI pousse désormais le `Responses API` comme primitive cible et a fixé le sunset de l'Assistants API au 2026-08-26, ce qui crée une vraie contrainte de trajectoire pour les runs agentiques longs.
- Les docs Promptfoo utiles pour CI/CD et red teaming ont été mises à jour le 2026-03-15, ce qui donne un cadre très frais pour mettre des gates réels sur vos prompts et vos sorties JSON.
- Les docs OpenTelemetry Python et Collector ont encore bougé entre 2026-02-21 et 2026-03-04, avec une base suffisamment stable pour instrumenter maintenant sans partir sur une stack propriétaire.
- Project OS a déjà ses briques locales de vérité (`memory`, `runtime`, `session`, evidence append-only). C'est donc le bon moment pour renforcer l'auditabilité sans créer une seconde vérité externe.

## Coherence Project OS

- La doctrine locale-first et auditable du repo favorise des briques standards et exportables, mais interdit qu'un SaaS externe devienne la vérité canonique.
- Les packages coeur existent déjà (`api_runs`, `gateway`, `orchestration`, `scheduler`, `session`, `memory`) ; il faut surtout étendre, relier et tester, pas remplacer.
- Les fichiers sales montrent que le point chaud actuel est la jonction `deep_research -> gateway -> api_runs -> session`, donc les recommandations ciblent ce flux précis.
- Le repo a déjà des fichiers de tests unitaires sur `api_runs`, `deep_research`, `gateway`, `session` et `openclaw`, ce qui rend réaliste l'ajout de preuves exécutables rapidement.
- Les docs `DEEP_RESEARCH_PROTOCOL.md`, `BUILD_STATUS_CHECKLIST.md` et `docs/systems/README.md` sont déjà les bons points d'ancrage pour fixer les nouvelles règles sans inventer une seconde doc racine.

## Point de depart repo

- branche active: `project-os/roadmap-freeze-lot4`
- packages coeur detectes:
  - `api_runs`
  - `gateway`
  - `github`
  - `learning`
  - `memory`
  - `mission`
  - `orchestration`
  - `router`
  - `runtime`
  - `scheduler`
  - `session`
- fichiers modifies observes:
  - `M docs/roadmap/BUILD_STATUS_CHECKLIST.md`
  - ` M docs/roadmap/NATURAL_MANAGER_MODE_PLAN.md`
  - ` M docs/systems/README.md`
  - ` M docs/workflow/DEEP_RESEARCH_PROTOCOL.md`
  - ` M integrations/openclaw/project-os-gateway-adapter/index.js`
  - ` M src/project_os_core/api_runs/service.py`
  - ` M src/project_os_core/deep_research.py`
  - ` M src/project_os_core/gateway/service.py`
  - ` M src/project_os_core/session/state.py`
  - ` M tests/unit/test_api_run_service.py`
  - ` M tests/unit/test_deep_research_service.py`
  - ` M tests/unit/test_gateway_and_orchestration.py`

## A faire

### OpenAI Responses API + exécution en background + frontière JSON stricte

Etat:

- `ADAPT`

Pourquoi il compte:

- Le flux `deep_research` de Project OS ressemble exactement au cas d'usage des longs runs asynchrones : dossiers potentiellement longs, multi-étapes, avec besoin de polling et d'annulation propre.
- OpenAI recommande désormais `Responses` pour les nouveaux projets et a daté la fin de l'Assistants API au 2026-08-26, donc rester sur des patterns plus anciens augmente la dette de migration.
- Le repo a déjà `session` et `api_runs` : il faut utiliser l'API distante comme moteur d'exécution, mais garder la vérité locale dans `SessionState` et l'evidence locale.
- La sortie de dossier exigée par Project OS est strictement JSON ; il faut donc coupler Structured Outputs côté modèle et validation stricte côté Python, sinon les erreurs silencieuses vont s'infiltrer dans `deep_research_pdf.py` et les adaptateurs gateway.

Ce qu'on recupere:

- Le pattern `create -> persist response_id -> poll/retrieve -> terminal status -> persist result` pour les runs longs.
- Un contrat unique de schéma JSON généré depuis les modèles Python canoniques, puis envoyé au modèle et revalidé localement au retour.
- La reprise de contexte par `previous_response_id` ou objets de conversation, mais uniquement comme optimisation d'exécution, jamais comme mémoire canonique.
- La gestion explicite des refus, statuts terminaux et sorties tronquées avant toute persistence ou rendu PDF.

Ce qu'on n'importe pas:

- Ne pas laisser les objets stockés côté OpenAI devenir la source de vérité de session ou d'audit.
- Ne pas maintenir un schéma JSON écrit à la main d'un côté et des modèles Python divergents de l'autre.
- Ne pas supposer que tous les modèles haut de gamme exposent exactement la même surface de Structured Outputs sans test de compatibilité.
- Ne pas propager un payload modèle non validé jusqu'au PDF ou à Discord.

Signal forks / satellites:

- Aucun fork, wrapper ou satellite inspecté n'est plus fort que l'upstream officiel OpenAI pour ce sujet ; la doc officielle reste la source à suivre.
- La bonne adaptation pour Project OS n'est pas un wrapper magique supplémentaire, mais une couche locale claire dans `api_runs` et `session`.

Ou ca entre dans Project OS:

- src/project_os_core/api_runs/service.py
- src/project_os_core/deep_research.py
- src/project_os_core/deep_research_pdf.py
- src/project_os_core/session/state.py
- tests/unit/test_api_run_service.py
- tests/unit/test_deep_research_service.py
- tests/unit/test_session_state.py

Preuves a obtenir:

- Exécuter un run `deep_research` en mode background, persister le `response_id` dans `SessionState`, tuer le process, redémarrer, puis prouver que le polling reprend et que le JSON final est identique après validation stricte.
- Ajouter dans `tests/unit/test_api_run_service.py` des cas de retrieve, cancel et status terminal idempotents ; la suite doit passer sans toucher à la mémoire canonique.
- Ajouter dans `tests/unit/test_deep_research_service.py` trois cas minimaux : sortie valide, refus explicite, sortie tronquée/invalide ; seuls les cas sûrs doivent franchir la frontière de persistence.
- Générer le schéma du dossier depuis les modèles Python, comparer ce schéma à celui réellement envoyé au modèle, et faire échouer le gate si le diff n'est pas vide.

Sources primaires:

- [Migrate to the Responses API](https://developers.openai.com/api/docs/guides/migrate-to-responses) - OpenAI | unknown - Confirme que `Responses` est la primitive recommandée, décrit `previous_response_id` et fixe le sunset Assistants au 2026-08-26.
- [Background mode](https://developers.openai.com/api/docs/guides/background) - OpenAI | unknown - Décrit le pattern asynchrone officiel `background=true`, le polling, l'annulation et la contrainte de stockage temporaire.
- [Strict Mode](https://docs.pydantic.dev/latest/concepts/strict_mode/) - Pydantic | unknown - Justifie un fail-closed local à la frontière JSON au lieu d'accepter des coercions silencieuses.
- [JSON Schema](https://docs.pydantic.dev/latest/concepts/json_schema/) - Pydantic | unknown - Montre comment générer le schéma JSON canonique depuis les modèles Python pour éviter les doubles vérités.

### OpenTelemetry local-first pour traces, erreurs et corrélation d'evidence

Etat:

- `ADAPT`

Pourquoi il compte:

- Project OS veut être auditable et local-first ; OpenTelemetry apporte un format standard et exportable sans imposer de backend propriétaire.
- Le flux `gateway -> api_runs -> orchestration -> session` traverse plusieurs couches où les fautes se perdent vite ; des spans corrélés donneront enfin une lecture causale réelle des runs.
- Les conventions d'exception sur les spans sont stables, donc vous pouvez coder une discipline d'erreurs exploitable maintenant.
- Le Collector local permet de démarrer sans cloud et sans transformer une plateforme d'observabilité externe en vérité canonique.

Ce qu'on recupere:

- Une instrumentation manuelle sur les services coeur et éventuellement de l'auto-instrumentation seulement aux bords techniques.
- Un `trace_id` propagé jusqu'aux journaux et à l'evidence locale pour relier cause, action et artefacts.
- Les événements d'exception standardisés (`exception.type`, `exception.message`, stacktrace) sur les spans fautifs.
- Un Collector local OTLP comme point d'agrégation de départ, avec export vers console/fichiers ou backend optionnel plus tard.

Ce qu'on n'importe pas:

- Ne pas transformer les traces en nouvelle vérité métier ; la vérité métier reste dans `session`, `runtime` et l'evidence append-only.
- Ne pas instrumenter chaque micro-fonction courte au détriment de la lisibilité.
- Ne pas dépendre d'un backend cloud pour le debug de base d'un run local.
- Ne pas laisser les erreurs sans attributs standardisés, sinon les traces seront jolies mais peu actionnables.

Signal forks / satellites:

- Je n'ai pas trouvé de fork plus fort que l'upstream OpenTelemetry ; l'officiel `opentelemetry-python-contrib` est le satellite utile, pas un remplaçant.
- Le bon choix pour Project OS est upstream OpenTelemetry + un sous-ensemble de contrib, pas une fork locale.

Ou ca entre dans Project OS:

- src/project_os_core/gateway/service.py
- src/project_os_core/api_runs/service.py
- src/project_os_core/session/state.py
- src/project_os_core/orchestration
- docs/roadmap/BUILD_STATUS_CHECKLIST.md
- tests/unit/test_gateway_and_orchestration.py

Preuves a obtenir:

- Démarrer un Collector local, exécuter une mission simple, puis vérifier qu'un seul `trace_id` couvre au minimum la réception gateway, le run modèle, la planification/orchestration et la persistence de session.
- Injecter une exception forcée dans le flow `gateway -> orchestration` et vérifier qu'un événement `exception` apparaît avec `exception.type`, `exception.message` et un statut d'erreur sur le span fautif.
- Couper puis redémarrer le processus au milieu d'un run et confirmer que l'identifiant de trace reste visible dans les journaux/evidence des deux côtés du redémarrage.
- Bloquer le merge si la trace d'un run de smoke test n'expose pas les quatre spans coeur attendus.

Sources primaires:

- [Instrumentation](https://opentelemetry.io/docs/languages/python/instrumentation/) - OpenTelemetry | 2025-12-03 - Base officielle pour l'instrumentation Python manuelle, les providers, span processors et attributs sémantiques.
- [Semantic conventions for exceptions on spans](https://opentelemetry.io/docs/specs/semconv/exceptions/exceptions-spans/) - OpenTelemetry | unknown - Définit le contrat stable des événements d'exception à enregistrer sur les spans.
- [Quick start](https://opentelemetry.io/docs/collector/quick-start/) - OpenTelemetry | 2026-02-21 - Donne le point de départ officiel pour un Collector local et un test simple d'ingestion de traces.
- [open-telemetry/opentelemetry-python-contrib](https://github.com/open-telemetry/opentelemetry-python-contrib) - GitHub / OpenTelemetry | unknown - Satellite officiel utile pour l'auto-instrumentation et les intégrations, sans dépasser l'upstream principal.

### Promptfoo comme gate d'evals et de red team sur les prompts Project OS

Etat:

- `ADAPT`

Pourquoi il compte:

- Le repo a déjà des tests unitaires techniques, mais pas encore une vraie couche d'evals continue pour les comportements LLM les plus coûteux : dossier JSON, résumés opérateur en français, dates absolues, refus sûrs, fuites inter-session.
- Promptfoo fournit un mode local/CLI compatible CI pour les evals et le red teaming, avec des plugins et des politiques custom utiles pour vos standards d'agent.
- Les guides utiles Promptfoo ont été mis à jour le 2026-03-15, donc la surface d'intégration est fraîche et active.
- OpenAI rappelle qu'il faut définir objectif, dataset, métriques et évaluation continue ; Project OS a déjà des artefacts et des logs pour construire ce seed set.

Ce qu'on recupere:

- Une petite matrice de cas canoniques ciblant `deep_research`, `gateway` et les sorties opérateur en français clair.
- Des assertions centrées sur la conformité JSON, les dates absolues, l'absence d'invention de fichiers locaux et la présence d'un niveau de preuve suffisant.
- Des plugins/politiques de red team ciblés sur prompt extraction, fuite de contexte inter-session, contournement de règles, et réponses dangereusement spéculatives.
- Un calibrage humain initial pour fixer les seuils, puis un gate CI sur des cas de régression réellement vécus.

Ce qu'on n'importe pas:

- Ne pas lancer une batterie générique énorme avant d'avoir 20 à 50 cas Project OS vraiment pertinents.
- Ne pas faire de Promptfoo la source de vérité sur les prompts ; la vérité reste dans le repo, les tests et les docs canoniques.
- Ne pas s'appuyer uniquement sur un grader LLM sans revue humaine d'étalonnage.
- Ne pas mélanger sécurité, style opérateur et fidélité JSON dans une seule note opaque.

Signal forks / satellites:

- Aucun fork ou satellite inspecté n'est plus fort que l'upstream `promptfoo/promptfoo` ; l'upstream reste le bon point d'entrée.
- Les intégrations GitHub Actions et la doc CI/CD sont utiles, mais ce sont des compléments de l'upstream, pas des alternatives plus solides.

Ou ca entre dans Project OS:

- docs/workflow/DEEP_RESEARCH_PROTOCOL.md
- src/project_os_core/deep_research.py
- src/project_os_core/gateway/service.py
- tests/unit/test_deep_research_service.py
- tests/unit/test_gateway_prompt_ops.py

Preuves a obtenir:

- Faire échouer la CI si un cas canonique de dossier renvoie un JSON invalide, oublie une date absolue demandée, ou produit un résumé opérateur non francophone.
- Exécuter un lot mensuel d'au moins 20 probes adversariales ciblées sur `gateway` et `deep_research` ; aucun cas classé haute sévérité ne doit passer le gate.
- Constituer un held-out set d'au moins 25 cas Project OS et vérifier que les rubrics automatiques restent alignées avec la revue humaine avant activation du gate bloquant.
- Relier chaque nouveau bug LLM rencontré en prod locale à au moins un cas d'eval ou de red-team ajouté ensuite au corpus.

Sources primaires:

- [promptfoo/promptfoo](https://github.com/promptfoo/promptfoo) - GitHub / Promptfoo | unknown - Repo upstream principal, licence et surface d'installation pour un usage local et CI.
- [CI/CD Integration for LLM Evaluation and Security](https://www.promptfoo.dev/docs/integrations/ci-cd/) - Promptfoo | 2026-03-15 - Décrit l'intégration CI, les quality gates et le flow `eval` / `redteam run`.
- [Red Team Plugins](https://www.promptfoo.dev/docs/red-team/plugins/) - Promptfoo | 2026-03-15 - Montre la granularité des plugins, des politiques custom et des catégories de risques exploitables pour Project OS.
- [Evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices) - OpenAI | unknown - Cadre officiel pour transformer des comportements LLM flous en objectifs, datasets, métriques et évaluation continue.

### GitHub supply-chain hardening : dependency review, CodeQL Python, SBOM

Etat:

- `KEEP`

Pourquoi il compte:

- Project OS dépend de packages IA et d'intégrations mouvantes ; sans gate supply chain, une simple PR peut introduire une vulnérabilité indirecte ou une dérive de dépendances invisible.
- GitHub fournit déjà des briques natives pour revoir les dépendances en PR, scanner le Python et exporter un SBOM exploitable en audit.
- Le repo possède un package `github` et une discipline de build status ; ces garde-fous ont une vraie place naturelle dans votre workflow existant.

Ce qu'on recupere:

- Dependency Review sur toute PR touchant un manifest ou un lockfile.
- CodeQL Python avec le niveau `security-extended` sur cadence PR + planifiée.
- Génération d'un SBOM comme artefact de build pour rapprocher ce qui est réellement exécuté de ce qui est audité.
- Documentation du gate dans `BUILD_STATUS_CHECKLIST.md` pour que la vérité d'état reste lisible par l'humain.

Ce qu'on n'importe pas:

- Ne pas se contenter d'un `pip install` vert comme preuve de sûreté.
- Ne pas activer des workflows sécurité sans branch protections qui exigent leur passage.
- Ne pas oublier les dépendances soumises pendant la build si le graph classique ne les voit pas.
- Ne pas exporter un SBOM sans vérifier qu'il correspond aux dépendances réellement utilisées par les tests.

Signal forks / satellites:

- Aucun fork utile n'est plus fort que les upstreams GitHub officiels pour ces fonctions ; la valeur ici vient des actions et APIs natives.
- Les éventuelles actions tierces SBOM sont des compléments, pas une meilleure source de vérité que la documentation GitHub.

Ou ca entre dans Project OS:

- github
- docs/roadmap/BUILD_STATUS_CHECKLIST.md
- tests/unit/test_api_run_service.py
- tests/unit/test_gateway_and_orchestration.py
- .github/workflows

Preuves a obtenir:

- Ouvrir une PR de test qui introduit volontairement une dépendance vulnérable ou un lockfile régressif et vérifier que Dependency Review bloque le merge.
- Exécuter CodeQL sur `src/project_os_core` avec la suite Python `security-extended` et exiger zéro nouvelle alerte haute/critique.
- Générer un SBOM en CI et confirmer par revue que les packages listés correspondent aux dépendances effectivement résolues et testées.
- Refuser le merge si l'un des trois checks sécurité manque ou est contournable sur la branche protégée.

Sources primaires:

- [About dependency review](https://docs.github.com/en/code-security/concepts/supply-chain-security/about-dependency-review) - GitHub | unknown - Explique le fonctionnement du dependency review, son blocage en PR et sa relation avec la dependency graph et la submission API.
- [Python queries for CodeQL analysis](https://docs.github.com/en/code-security/reference/code-scanning/codeql/codeql-queries/python-built-in-queries) - GitHub | unknown - Décrit les suites `default` et `security-extended` pour le code Python.
- [Exporting a software bill of materials for your repository](https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/establish-provenance-and-integrity/exporting-a-software-bill-of-materials-for-your-repository) - GitHub | unknown - Donne la voie officielle pour exporter ou générer un SBOM exploitable dans le repo et en CI.

## A etudier

### Patterns Temporal pour crash-recovery, non-déterminisme et heartbeats

Etat:

- `DEFER`

Pourquoi il compte:

- Temporal formalise trois choses que Project OS doit de toute façon maîtriser tôt ou tard : reprise après crash, discipline anti non-déterminisme, et checkpoints/heartbeats sur les tâches longues.
- Le repo possède déjà `scheduler`, `orchestration`, `runtime` et `session` ; étudier Temporal maintenant a du sens comme benchmark de maturité, mais pas comme migration immédiate.
- L'adoption complète ajouterait un nouveau serveur, une nouvelle sémantique d'état et un nouveau plan de contrôle, donc un risque élevé de seconde vérité tant que les journaux/replays locaux ne sont pas encore béton.

Ce qu'on recupere:

- Les patterns de replay et de refus du non-déterminisme dans les chemins d'orchestration.
- Les heartbeats/cancellation checkpoints pour les activités longues et interruptibles.
- Les tests de crash/reprise et les scénarios de graceful shutdown comme standard de preuve interne.
- Le rôle de `samples-python` comme réservoir d'idées de test, pas comme architecture à importer.

Ce qu'on n'importe pas:

- Ne pas introduire un cluster/service Temporal dans le coeur tant que `session` et le journal local n'ont pas prouvé leur reprise sans effets de bord dupliqués.
- Ne pas déplacer la vérité de mission ou de mémoire dans un moteur externe d'orchestration.
- Ne pas adopter la sandbox ou les abstractions Temporal telles quelles si elles cassent le modèle local-first du repo.

Signal forks / satellites:

- Je n'ai pas trouvé de fork plus fort que l'upstream Temporal ; `temporalio/samples-python` est le satellite utile, pas un concurrent.
- L'upstream Python SDK et ses releases sont le bon matériau d'étude ; les forks visibles n'apportent pas un signal supérieur.

Ou ca entre dans Project OS:

- scheduler
- orchestration
- runtime
- session
- tests/unit/test_gateway_and_orchestration.py
- tests/unit/test_session_state.py
- docs/roadmap/BUILD_STATUS_CHECKLIST.md

Preuves a obtenir:

- Écrire un test de crash en milieu de mission longue, redémarrer le runtime, puis prouver qu'aucune action à effet de bord n'est exécutée deux fois.
- Ajouter un test de replay orchestration qui échoue lorsqu'un chemin non-déterministe est introduit dans la logique de mission.
- Mettre en place des checkpoints/heartbeats locaux pour une tâche longue, puis vérifier qu'un shutdown gracieux et une annulation restent observables et reprenables.
- Clore l'étude uniquement si au moins un gap réel du scheduler/orchestration actuel est objectivé par un test rouge puis vert.

Sources primaires:

- [Temporal Docs](https://docs.temporal.io/) - Temporal | unknown - Positionne officiellement Temporal comme moteur de durable execution et de reprise après crash.
- [temporalio/sdk-python](https://github.com/temporalio/sdk-python) - GitHub / Temporal | unknown - Repo upstream Python SDK, utile pour lire la sémantique réelle de sandbox, annulation et activités.
- [Releases · temporalio/sdk-python](https://github.com/temporalio/sdk-python/releases) - GitHub / Temporal | 2025-11-25 - Montre que le SDK continue d'évoluer sur les points qui comptent ici, notamment heartbeating et discipline runtime/forks.
- [temporalio/samples-python](https://github.com/temporalio/samples-python) - GitHub / Temporal | unknown - Satellite officiel pratique pour transformer l'étude en scénarios de preuve plutôt qu'en simple lecture théorique.

## A rejeter pour maintenant

### Langfuse comme plateforme primaire d'observabilité / eval / prompts pour Project OS

Etat:

- `REJECT`

Pourquoi il compte:

- Langfuse est attractif et actif, mais en faire la plateforme primaire de Project OS créerait presque immédiatement une seconde vérité externe pour les traces, prompts, datasets et annotations.
- Le repo upstream indique qu'une instance self-hosted remonte par défaut des statistiques d'usage basiques à PostHog tant que `TELEMETRY_ENABLED=false` n'est pas explicitement posé, ce qui est un mauvais défaut pour une doctrine locale-first stricte.
- Comme Langfuse est déjà basé sur OpenTelemetry, Project OS peut récupérer l'essentiel de la valeur structurante en adoptant d'abord OTel local, puis éventuellement un export opt-in plus tard si le besoin apparaît.

Ce qu'on recupere:

- Uniquement des idées d'UX de traces et, au besoin, un export optionnel derrière une frontière OTel claire.
- La compatibilité OTel comme preuve que vous pouvez garder un coeur standard et portable.
- Un éventuel pilote de lecture seule, isolé, sans dépendance canonique du runtime.

Ce qu'on n'importe pas:

- Ne pas en faire la vérité canonique de mission, session, mémoire, prompts ou évaluation.
- Ne pas brancher ses features de prompt management comme nouvelle source de vérité documentaire.
- Ne pas accepter la télémétrie par défaut ni un trafic sortant implicite sur une machine qui porte des runs sensibles.
- Ne pas complexifier le coeur local alors qu'OpenTelemetry couvre déjà le besoin architectural de base.

Signal forks / satellites:

- Je n'ai trouvé aucun fork plus fort que l'upstream Langfuse ; les satellites `langfuse-k8s` et modules de déploiement sont utiles pour l'hébergement, pas supérieurs au repo principal.
- Le meilleur usage éventuel pour Project OS est un rôle de sink optionnel et réversible, pas un rôle central.

Ou ca entre dans Project OS:

- docs/systems/README.md
- src/project_os_core/api_runs/service.py
- src/project_os_core/gateway/service.py
- docs/roadmap/BUILD_STATUS_CHECKLIST.md

Preuves a obtenir:

- Gate d'architecture : retirer complètement l'export optionnel vers un backend d'observabilité ne doit casser ni l'exécution locale, ni la reprise de session, ni l'inspection d'evidence.
- Si un pilote jetable est mené, vérifier explicitement `TELEMETRY_ENABLED=false` et tracer le trafic sortant pour confirmer l'absence d'émissions non prévues.
- Passer une revue de menace démontrant qu'aucune donnée opérateur ou inter-session n'est nécessaire dans un backend externe pour maintenir le fonctionnement de base.

Sources primaires:

- [langfuse/langfuse](https://github.com/langfuse/langfuse) - GitHub / Langfuse | 2025-12-15 - Repo upstream actif ; documente la télémétrie activée par défaut sur le self-hosted et la cadence de releases.
- [OTEL-based Python SDK v3 released in beta](https://github.com/orgs/langfuse/discussions/6993) - GitHub / Langfuse | 2025-05-23 - Confirme que leur SDK Python est désormais fondé sur OpenTelemetry, donc que l'ossature standard peut être prise sans adopter la plateforme entière.
- [Langfuse](https://langfuse.com/) - Langfuse | unknown - Présente l'ambition produit complète (traces, evals, prompt management, annotations), précisément le périmètre qui risquerait de dupliquer le coeur de Project OS.
- [langfuse/langfuse-k8s](https://github.com/langfuse/langfuse-k8s) - GitHub / Langfuse | unknown - Satellite utile de déploiement, mais explicitement communautaire et non supérieur à l'upstream principal.

## Preuves transverses a obtenir

- Figer un contrat JSON canonique pour les dossiers de recherche et les envelopes gateway, puis brancher `api_runs` et `deep_research` sur un flow `Responses API` avec validation stricte et reprise par `response_id`.
- Installer un Collector OpenTelemetry local, propager un `trace_id` unique à travers `gateway`, `api_runs`, `orchestration` et `session`, et relier les erreurs à l'evidence locale.
- Créer une première matrice d'evals et de red-team ciblée sur les sorties opérateur, les dates absolues, la conformité JSON et les risques de fuite inter-session.
- Activer les gates GitHub de supply chain : dependency review, CodeQL Python, SBOM artifact.
- Avant toute étude d'un moteur externe, écrire des tests de crash/reprise, heartbeat et non-déterminisme inspirés de Temporal sur le scheduler/orchestration existant.

## Risques et angles morts

- Si `Responses` est adopté sans checkpoint local strict, une partie du run peut dériver vers une dépendance cachée à l'état stocké côté fournisseur.
- Si l'instrumentation OTel est trop large ou trop floue, vous risquez un bruit massif sans gain réel d'auditabilité.
- Des evals mal calibrées peuvent optimiser les prompts pour la note et non pour l'utilité réelle de l'opérateur.
- Les gates GitHub n'apportent presque rien si les protections de branche ou la discipline de merge restent faibles.
- L'étude Temporal peut devenir une distraction coûteuse si elle glisse de benchmark de patterns vers migration prématurée.
- Une plateforme externe d'observabilité/prompt management peut violer la doctrine locale-first même quand elle est annoncée comme self-hosted.

## Questions ouvertes

- Le service `api_runs` utilise-t-il déjà `Responses` partout, ou existe-t-il encore des chemins `Chat Completions` / `Assistants` à migrer ?
- Quelle part des données de run peut légalement ou stratégiquement être stockée temporairement côté fournisseur, même pour 10 minutes de polling ?
- Le `SessionState` actuel sait-il déjà reprendre un run interrompu sans double exécution d'effets de bord, ou seulement restaurer du contexte ?
- Le repo dispose-t-il de GitHub Code Security / Advanced Security sur le plan courant, ou faut-il prévoir un fallback d'outillage ?
- Quel est le seed set minimal de cas réels Project OS à transformer immédiatement en evals bloquantes ?
- Le pipeline PDF doit-il consommer exclusivement le JSON canonique validé, sans jamais relire des fragments texte intermédiaires ?

## Sources globales

- [Migrate to the Responses API](https://developers.openai.com/api/docs/guides/migrate-to-responses) - OpenAI | unknown - Source racine pour la direction API recommandée et la date de fin Assistants.
- [Background mode](https://developers.openai.com/api/docs/guides/background) - OpenAI | unknown - Source racine pour les runs longs asynchrones pertinents pour `deep_research`.
- [Strict Mode](https://docs.pydantic.dev/latest/concepts/strict_mode/) - Pydantic | unknown - Base pour un fail-closed local sur les frontières de schéma.
- [Instrumentation](https://opentelemetry.io/docs/languages/python/instrumentation/) - OpenTelemetry | 2025-12-03 - Base de la colonne vertébrale de traces Python pour Project OS.
- [Quick start](https://opentelemetry.io/docs/collector/quick-start/) - OpenTelemetry | 2026-02-21 - Montre la voie la plus courte vers un Collector local.
- [CI/CD Integration for LLM Evaluation and Security](https://www.promptfoo.dev/docs/integrations/ci-cd/) - Promptfoo | 2026-03-15 - Source récente et directement exploitable pour les gates d'evals et de sécurité.
- [About dependency review](https://docs.github.com/en/code-security/concepts/supply-chain-security/about-dependency-review) - GitHub | unknown - Source clé pour les blocages de dépendances vulnérables en PR.
- [Python queries for CodeQL analysis](https://docs.github.com/en/code-security/reference/code-scanning/codeql/codeql-queries/python-built-in-queries) - GitHub | unknown - Source officielle pour le périmètre d'analyse Python.
- [Temporal Docs](https://docs.temporal.io/) - Temporal | unknown - Référence pour les patterns de durable execution à benchmarker.
- [langfuse/langfuse](https://github.com/langfuse/langfuse) - GitHub / Langfuse | 2025-12-15 - Source clé pour évaluer si Langfuse peut ou non devenir une brique primaire dans une architecture locale-first.
