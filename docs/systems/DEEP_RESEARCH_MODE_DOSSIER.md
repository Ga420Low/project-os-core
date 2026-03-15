# Deep Research Mode

## Statut

- `active`

## But

- standardiser les recherches approfondies demandees en conversation
- eviter les recherches larges mais peu utiles au repo reel
- transformer les recherches lourdes en artefacts durables, reouvrables et comparables

## Question de recherche

- definir un mode `deep research` plus automatique pour `Project OS`, avec un vrai protocole, un scaffold et une sortie canonique exploitable

## Declencheurs

- `deep research`
- `recherche approfondie`
- `audit profond`
- `fouille github`
- `cherche les pepites`
- `regarde les forks`
- `va chercher plus loin`

## Point de depart reel

Avant ce chantier:

- le repo avait deja un standard de roadmap et un standard de dossier systeme
- la recherche etait mieux documentee qu'au debut, mais encore trop dependante de la conversation en cours
- il n'existait pas de declencheur canonique `deep research`
- il n'existait pas de commande pour scaffold automatiquement un audit ou un dossier de recherche

Packages coeur detectes au moment de la mise en place:

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

References locales a relire avant synthese:

- [AGENTS.md](../../AGENTS.md)
- [PROJECT_OS_MASTER_MACHINE.md](../../PROJECT_OS_MASTER_MACHINE.md)
- [BUILD_STATUS_CHECKLIST.md](../roadmap/BUILD_STATUS_CHECKLIST.md)
- [ROADMAP_AUTHORING_STANDARD.md](../workflow/ROADMAP_AUTHORING_STANDARD.md)
- [SYSTEM_DOSSIER_AUTHORING_STANDARD.md](../workflow/SYSTEM_DOSSIER_AUTHORING_STANDARD.md)
- [DEEP_RESEARCH_PROTOCOL.md](../workflow/DEEP_RESEARCH_PROTOCOL.md)
- [README.md](README.md)

## Hypothese de travail

- le bon systeme n'est pas un crawler autonome qui decide seul
- le bon systeme est un protocole de recherche fort, branche sur le repo reel, avec un scaffold rapide et des sorties durables
- les vraies pepites viennent souvent des `satellites` et `bridges`, pas seulement des forks directs
- pour `Project OS`, la valeur d'une recherche vient de sa traduction en `KEEP / ADAPT / DEFER / REJECT`

## Protocole obligatoire

- 1. `repo-first` : inspecter d'abord le code, les docs et les contraintes reelles de `Project OS` avant de chercher des briques externes.
- 2. `sources primaires + recence` : privilegier docs officielles, papiers originaux, repos officiels, changelogs et pages produit recentes.
- 3. `lane GitHub upstream` : lire le `README`, verifier licence, surface d'installation, activite recente, releases, security/dependency graph si disponible.
- 4. `lane forks et satellites` : verifier les forks actifs et les repos satellites, puis dire explicitement s'il n'existe pas de vraie pepite au-dela de l'upstream.
- 5. `lane integration Project OS` : classer chaque piste en `KEEP`, `ADAPT`, `DEFER` ou `REJECT`, avec les packages ou docs impactes dans le repo.
- 6. `lane preuve` : pour toute recommandation actionnable, definir une preuve ou un test concret a obtenir sur la machine ou dans le repo.

## A faire

### Protocole `deep research` comme convention canonique

Etat:

- `A_FAIRE`

Pourquoi il compte:

- OpenAI decrit une `deep research` multi-etapes avec citations, sources nombreuses et navigation adaptee, pas un simple prompt long
- Anthropic pousse aussi des workflows decoupes en etapes et outils specialises pour les taches complexes
- sans protocole explicite, le niveau de recherche depend trop du contexte de la conversation

Ce qu'on recupere:

- `repo-first`
- `sources primaires + recence`
- `lane GitHub`
- `lane forks et satellites`
- traduction finale en `KEEP / ADAPT / DEFER / REJECT`

Ce qu'on n'importe pas:

- l'idee d'un agent qui browse indefiniment sans borne
- une recherche qui oublie le repo courant au profit de la nouveaute pure

Preuves a obtenir:

- le protocole existe dans [DEEP_RESEARCH_PROTOCOL.md](../workflow/DEEP_RESEARCH_PROTOCOL.md)
- les declencheurs existent dans [AGENTS.md](../../AGENTS.md)
- le protocole impose bien `repo -> web -> integration -> preuve`

Ou ca entre dans Project OS:

- [AGENTS.md](../../AGENTS.md)
- [DEEP_RESEARCH_PROTOCOL.md](../workflow/DEEP_RESEARCH_PROTOCOL.md)

Sources primaires:

- [OpenAI - Introducing deep research, 2 fevrier 2025, maj 10 fevrier 2026](https://openai.com/index/introducing-deep-research/)
- [OpenAI - Deep research in ChatGPT FAQ](https://help.openai.com/en/articles/10500283-deep-research)
- [Anthropic - Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)

### Scaffold CLI pour ne plus repartir de zero

Etat:

- `A_FAIRE`

Pourquoi il compte:

- une bonne convention qui n'a pas de raccourci outille retombe vite dans l'oubli
- le repo avait `docs audit`, mais pas de commande pour initialiser un vrai dossier de recherche

Ce qu'on recupere:

- commande `py scripts/project_os_entry.py docs scaffold-research`
- generation automatique vers `docs/audits/` ou `docs/systems/`
- injection des references locales et des packages coeur detectes

Ce qu'on n'importe pas:

- de generation automatique de contenu de recherche
- de scoring automatique pseudo-intelligent sans lecture reelle des sources

Preuves a obtenir:

- la commande existe dans [cli.py](../../src/project_os_core/cli.py)
- le module existe dans [research_scaffold.py](../../src/project_os_core/research_scaffold.py)
- les tests passent dans [test_research_scaffold.py](../../tests/unit/test_research_scaffold.py)

Ou ca entre dans Project OS:

- [cli.py](../../src/project_os_core/cli.py)
- [research_scaffold.py](../../src/project_os_core/research_scaffold.py)
- [test_research_scaffold.py](../../tests/unit/test_research_scaffold.py)

Sources primaires:

- [OpenAI - Eval Driven System Design](https://cookbook.openai.com/examples/partners/eval_driven_system_design/receipt_inspection)
- [OpenAI - Graders guide](https://platform.openai.com/docs/guides/graders)
- [Anthropic - Tool use overview](https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/overview)

### Split canonique `audit / system / roadmap`

Etat:

- `A_FAIRE`

Pourquoi il compte:

- les recherches ponctuelles, les veilles de stack et les roadmaps n'ont pas le meme role
- sans separation, les roadmaps deviennent trop verbeuses et les audits deviennent des pseudo-roadmaps

Ce qu'on recupere:

- `docs/audits/` pour l'enquete ponctuelle
- `docs/systems/` pour la veille structurelle
- `docs/roadmap/` seulement apres synthese et ordre d'execution

Ce qu'on n'importe pas:

- une nouvelle categorie documentaire pour chaque cas
- une seconde logique de classement a cote de l'existant

Preuves a obtenir:

- le split est decrit dans [DEEP_RESEARCH_PROTOCOL.md](../workflow/DEEP_RESEARCH_PROTOCOL.md)
- les standards existants sont relies entre eux
- les nouveaux artefacts passent le `docs audit`

Ou ca entre dans Project OS:

- [README.md](README.md)
- [ROADMAP_AUTHORING_STANDARD.md](../workflow/ROADMAP_AUTHORING_STANDARD.md)
- [SYSTEM_DOSSIER_AUTHORING_STANDARD.md](../workflow/SYSTEM_DOSSIER_AUTHORING_STANDARD.md)

Sources primaires:

- [GitHub Docs - About repository graphs](https://docs.github.com/en/repositories/viewing-activity-and-data-for-your-repository/about-repository-graphs)
- [GitHub Docs - Understanding connections between repositories](https://docs.github.com/en/repositories/viewing-activity-and-data-for-your-repository/understanding-connections-between-repositories)

## A etudier

### Enrichissement GitHub semi-automatique

Etat:

- `A_ETUDIER`

Pourquoi il compte:

- beaucoup de temps part dans la verification repetitive de licence, releases, activite, forks et dependances
- un enrichissement semi-automatique pourrait accelerer les audits sans remplacer le jugement

Ce qu'on recupere:

- pre-remplissage de metadonnees repo
- capture date de derniere release
- capture licence, stars, forks, activity signals

Ce qu'on n'importe pas:

- un classement automatique des repos base uniquement sur stars et forks
- une confiance aveugle dans les metriques GitHub

Preuves a obtenir:

- definir une heuristique simple qui ne pousse pas de faux positifs
- prouver que le temps gagne est reel sur 2 ou 3 audits

Ou ca entre dans Project OS:

- futur enrichissement de [research_scaffold.py](../../src/project_os_core/research_scaffold.py)

Sources primaires:

- [GitHub Docs - About forks](https://docs.github.com/pull-requests/collaborating-with-pull-requests/working-with-forks/about-forks)
- [GitHub Docs - About the dependency graph](https://docs.github.com/en/code-security/supply-chain-security/understanding-your-software-supply-chain/about-the-dependency-graph)

### Memoire de recherche branchee sur `learning`

Etat:

- `A_ETUDIER`

Pourquoi il compte:

- aujourd'hui la recherche durable passe surtout par des docs
- plus tard, certaines decisions de veille pourraient alimenter la memoire canonique si elles deviennent repetitives

Ce qu'on recupere:

- index de decisions de recherche deja tranchees
- reduction des re-analyses steriles sur les memes systemes

Ce qu'on n'importe pas:

- une pollution de la memoire canonique par des notes faibles ou temporaires
- une ingestion automatique de toute recherche dans `learning`

Preuves a obtenir:

- definir ce qui merite d'etre memorise
- prouver que cela ameliore une recherche ulterieure sans bruit excessif

Ou ca entre dans Project OS:

- futur lien entre dossiers de recherche et [service.py](../../src/project_os_core/learning/service.py)

Sources primaires:

- [OpenAI - Graders guide](https://platform.openai.com/docs/guides/graders)
- [deepseek-ai/DeepSeek-R1](https://github.com/deepseek-ai/DeepSeek-R1)

## A rejeter pour maintenant

### Crawler autonome qui recherche sans cadrage

Etat:

- `REJECT`

Pourquoi on le rejette:

- sans question claire et sans lecture du repo, la recherche derive vite vers de la nouveaute sans levier reel
- OpenAI et Anthropic montrent de meilleures pratiques avec navigation structuree, outils et bornes de tache

Ce qu'on recupere:

- rien comme comportement par defaut

Ce qu'on n'importe pas:

- une boucle web autonome qui produit des recommandations hors contexte

Preuves a obtenir pour rouvrir la question:

- montrer qu'un tel crawler surpasse le protocole actuel sur des cas reels du repo

Ou ca entre dans Project OS:

- nulle part comme doctrine principale

Sources primaires:

- [OpenAI - Deep research in ChatGPT FAQ](https://help.openai.com/en/articles/10500283-deep-research)
- [Anthropic - Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)

### Scoring des repos base seulement sur stars et forks

Etat:

- `REJECT`

Pourquoi on le rejette:

- les vraies pepites de ce projet viennent souvent des `satellites` et non des depots les plus gros
- stars et forks ne disent pas la compatibilite, la maintenance locale, la licence ni la valeur d'integration

Ce qu'on recupere:

- stars et forks comme signaux secondaires seulement

Ce qu'on n'importe pas:

- un classement mecanique qui remplacerait la lecture des `README`, docs, licence et limitations

Preuves a obtenir pour rouvrir la question:

- montrer qu'un scoring simple predit vraiment les meilleures integrations pour `Project OS`

Ou ca entre dans Project OS:

- nulle part comme critere principal

Sources primaires:

- [GitHub Docs - About repository graphs](https://docs.github.com/en/repositories/viewing-activity-and-data-for-your-repository/about-repository-graphs)
- [GitHub Docs - About forks](https://docs.github.com/pull-requests/collaborating-with-pull-requests/working-with-forks/about-forks)

## Sources

- [DEEP_RESEARCH_PROTOCOL.md](../workflow/DEEP_RESEARCH_PROTOCOL.md)
