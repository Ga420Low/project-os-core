# Deep Research Protocol

## Objet

Ce document fixe le protocole canonique quand `Project OS` doit faire une recherche approfondie sur:

- un systeme
- une stack
- un repo GitHub
- des forks
- un benchmark
- une categorie produit ou recherche

Le but n'est pas de produire un joli resume.
Le but est de produire une recherche exploitable, reliee au repo reel, avec une barre de preuve plus haute.

## Declencheurs

Les formulations suivantes doivent activer ce protocole:

- `deep research`
- `recherche approfondie`
- `audit profond`
- `fouille github`
- `cherche les pepites`
- `regarde les forks`
- `va chercher plus loin`

Si la demande ressemble clairement a ce mode sans reprendre ces mots exacts, le protocole s'applique quand meme.

## Protocole obligatoire

### 1. Repo-first

Avant la veille externe, il faut:

- inspecter le repo reel
- relire les docs et ADR pertinentes
- identifier les packages deja presents
- lister les contraintes qui rendent certaines pistes inutiles, prematurees ou dangereuses

Pourquoi:

- pour eviter les recommandations deconferencees du projet
- pour ne pas proposer une seconde verite architecturale
- pour distinguer `ce qui manque` de `ce qui existe deja mal exploite`

### 2. Sources primaires et recence

La recherche doit privilegier:

- docs officielles
- pages produit officielles
- papiers originaux
- repos officiels
- changelogs, releases et pages benchmark officielles

La reponse doit:

- preferer des dates explicites quand le sujet est recent
- signaler clairement quand une affirmation est une inference
- distinguer `source primaire`, `source secondaire` et `signal faible`

Pourquoi:

- OpenAI decrit la deep research comme une recherche multi-etapes basee sur des centaines de sources avec citations et navigation adaptative, pas comme un simple resume de surface
- pour les sujets recents, la valeur vient souvent des mises a jour et non du papier d'origine seulement

### 3. Lane GitHub obligatoire

Quand un repo est central a la question, il faut inspecter au minimum:

- le `README`
- la licence
- l'activite recente
- les releases si elles existent
- la surface d'installation
- les issues ou limitations evidentes
- la dependency graph et les signaux de securite si disponibles

Pourquoi:

- GitHub expose des graphes et des vues utiles sur l'activite, les dependances, les contributeurs, le traffic, la network graph et les forks
- une pepite repo n'est pas seulement une idee; c'est aussi un objet maintenable, installable et licitement reutilisable

### 4. Lane forks et satellites

Quand les forks comptent, il faut:

- verifier la liste des forks et la network graph
- dire s'il existe un vrai fork actif ou seulement des mirrors
- inspecter aussi les repos satellites et wrappers, souvent plus utiles que les forks directs

Pourquoi:

- dans beaucoup de categories, les vraies pepites ne sont pas dans les forks bruts de l'upstream mais dans les bridges, plugins, wrappers et benchmarks adjacents

### 5. Lane integration Project OS

Toute recherche doit finir par une traduction `Project OS`:

- `KEEP`
- `ADAPT`
- `DEFER`
- `REJECT`

Et pour chaque element retenu:

- `ce qu'on recupere`
- `ce qu'on n'importe pas`
- `ou cela entre dans Project OS`
- `quelle preuve il faut obtenir`

Pourquoi:

- une recherche sans traduction d'integration reste un document de veille, pas un levier produit

### 6. Sortie canonique

Si le sujet est durable et structurel:

- produire ou mettre a jour un dossier dans `docs/systems/`

Si le sujet est une enquete ponctuelle ou une note de travail:

- produire un audit dans `docs/audits/`

Si la recherche debouche sur un ordre d'execution:

- produire ensuite une roadmap dans `docs/roadmap/`

## Mecanique repo

Commande de scaffold:

```powershell
py scripts/project_os_entry.py docs scaffold-research --title "Nom du sujet" --kind audit
```

Pour un dossier systeme:

```powershell
py scripts/project_os_entry.py docs scaffold-research --title "Nom du systeme" --kind system
```

Le scaffold injecte:

- les mots declencheurs
- le protocole obligatoire
- les references locales detectees
- les packages coeur detectes

## Integration Discord / OpenClaw

Quand un message entrant contient un declencheur `deep research`, le gateway peut preparer automatiquement un scaffold de recherche avant le routage missionnel, lancer un job detache de recherche, puis faire revenir le rapport sur Discord.

Effet attendu:

- creation d'un fichier dans `docs/systems/` ou `docs/audits/`
- ajout du chemin du dossier dans les metadonnees de dispatch
- lancement d'un job asynchrone qui inspecte le repo, fait la veille web, puis remplit le dossier
- retour final sur Discord avec un resume compact et le `.md` joint en piece jointe
- le dossier dans le repo devient la source durable de la recherche, pas seulement le message Discord

Implementation locale:

- le scaffold manuel reste disponible via `py scripts/project_os_entry.py docs scaffold-research --title "..."`
- le runner interne passe par `py scripts/project_os_entry.py research run-job --job-path ...`
- le job ecrit ses artefacts runtime sous `runtime/deep_research/`, met a jour le dossier du projet, puis publie le resume final via la queue `operator_deliveries`

## Pourquoi cette mecanique existe

Le projet a besoin d'une recherche plus proche d'un `analyst workflow` que d'une simple reponse conversationnelle.

On reprend ici:

- d'OpenAI: l'idee de recherche multi-etapes avec citations, navigation adaptee, sources nombreuses et possibilité de restreindre la recherche a des sources de confiance
- d'OpenAI Evals: l'idee que la qualite doit etre testable et que les sorties doivent alimenter une boucle d'amelioration
- d'Anthropic: l'idee qu'une tache complexe gagne a etre decoupee en sous-etapes et en outils specialises
- de GitHub: l'idee qu'un repo doit etre juge aussi par ses graphes, ses dependances, ses forks, ses contributeurs et sa maintenance
- de DeepSeek-R1: l'idee que les taches difficiles beneficient d'une trajectoire de raisonnement plus structuree et non d'une reponse improvisée

## Sources

### OpenAI

- [Introducing deep research, 2 fevrier 2025, avec mises a jour jusqu'au 10 fevrier 2026](https://openai.com/index/introducing-deep-research/)
- [Deep research in ChatGPT FAQ](https://help.openai.com/en/articles/10500283-deep-research)
- [Graders guide](https://platform.openai.com/docs/guides/graders)
- [Eval Driven System Design - From Prototype to Production](https://cookbook.openai.com/examples/partners/eval_driven_system_design/receipt_inspection)

### Anthropic

- [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)
- [Tool use with Claude](https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/overview)
- [Computer use tool](https://docs.anthropic.com/en/docs/build-with-claude/computer-use)
- [Chain prompts](https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/chain-prompts)

### GitHub

- [About repository graphs](https://docs.github.com/en/repositories/viewing-activity-and-data-for-your-repository/about-repository-graphs)
- [Understanding connections between repositories](https://docs.github.com/en/repositories/viewing-activity-and-data-for-your-repository/understanding-connections-between-repositories)
- [About forks](https://docs.github.com/pull-requests/collaborating-with-pull-requests/working-with-forks/about-forks)
- [About the dependency graph](https://docs.github.com/en/code-security/supply-chain-security/understanding-your-software-supply-chain/about-the-dependency-graph)

### DeepSeek

- [deepseek-ai/DeepSeek-R1](https://github.com/deepseek-ai/DeepSeek-R1)
