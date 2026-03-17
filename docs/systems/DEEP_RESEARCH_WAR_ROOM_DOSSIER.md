# Deep Research War Room

## Statut

- `active`

## But

- definir le mode `extreme`
- cadrer un `War Room` ambitieux sans sortir du modele de cout actuel

## Point de depart reel

- le projet vise des recherches plus agressives sur des gros sujets
- le besoin n'est pas juste plus de tokens, mais une meilleure separation entre scouts, trust gate et synthese experte

## Hypothese de travail

- les cheap scouts doivent elargir puis trier
- l'expert doit etudier de l'evidence curatee, pas du bruit web brut
- la securite source doit etre obligatoire dans ce mode
- en v2, cette orchestration garde un parent detache mais lance de vrais child workers locaux par lane
- le cheap scout swarm doit produire des briefs par lane et des seeds de sources avant les scouts experts
- un echec partiel d'une lane doit degrader le run et rester visible, pas effacer tout le travail valide des autres lanes
- les passes auxiliaires et la synthese finale doivent reutiliser l'etat Responses quand c'est possible, pour eviter de repayer la meme remise en contexte
- la reputation source doit persister localement d'un run a l'autre
- par defaut, les passes de recherche `extreme` restent sur la route canonique `OpenAI`; une route `Anthropic Sonnet` n'est autorisee qu'en debug explicite avec logs de tokens et de cout par phase

## A faire

### War Room execution plan

Etat:

- `A_FAIRE`

Pourquoi il compte:

- c'est le mode pour les dossiers a fort levier ou a fort angle mort

Ce qu'on recupere:

- parent planner
- cheap scout swarm
- source safety gate
- repo scout
- official-doc scout
- GitHub/forks/satellites scout
- papers/benchmarks scout
- skeptic
- expert synthesizer
- publisher
- lane workers locaux avec artefacts propres sous `lanes/`

Ce qu'on n'importe pas:

- crawler autonome sans bornes
- nouvelle infra de scraping externe
- download-and-run depuis des sources inconnues

Preuves a obtenir:

- le plan `extreme` montre plusieurs lanes et un trust gate obligatoire
- le cheap scout swarm produit des briefs exploitables pour `official_docs`, `github` et `papers`
- les sources faibles sont downgradees ou quarantinees
- le mesh parent/child ecrit `mesh_manifest.json` et des artefacts par lane
- le moteur de reputation source garde un historique local observable
- le resume d'execution montre l'etat des lanes, pas seulement la liste des phases
- le resume d'execution montre aussi si la continuite Responses a ete exploitee jusqu'a la synthese finale
- la synthese finale mentionne ce que les scouts ont filtre, pas seulement ce qu'ils ont trouve
- un run `extreme` debug produit `model_debug.jsonl` et `usage_summary.json` pour audit de cout et de perf

Ou ca entre dans Project OS:

- `deep_research.py`
- `docs/workflow/DEEP_RESEARCH_INTENSITY_STANDARD.md`
- `docs/workflow/DEEP_RESEARCH_QUALITY_STANDARD.md`

Sources primaires:

- [OpenAI - Introducing deep research](https://openai.com/index/introducing-deep-research/)
- [Anthropic - Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)

## A etudier

### Scout specialization tuning

Etat:

- `A_ETUDIER`

Pourquoi il compte:

- un War Room trop uniforme gaspille du cout

Ce qu'on recupere:

- lanes mieux specializees
- meilleur tri cheap vs expert

Ce qu'on n'importe pas:

- un nombre arbitraire de sous-agents sur chaque run

Preuves a obtenir:

- montrer un vrai gain sur un audit projet ou subsysteme de haut niveau

Ou ca entre dans Project OS:

- `deep_research.py`

Sources primaires:

- [OpenAI - Deep research FAQ](https://help.openai.com/en/articles/10500283-deep-research)

## A rejeter pour maintenant

### Arbitrary crawler platform

Etat:

- `REJECT`

Pourquoi on le rejette:

- v1 doit rester dans la pile provider/cout actuelle
- la valeur est dans l'orchestration et le trust gate, pas dans une nouvelle infra lourde

Ce qu'on recupere:

- rien comme comportement par defaut

Ce qu'on n'importe pas:

- navigateur autonome contre des sites inconnus
- execution de code collecte pendant la recherche

Preuves a obtenir:

- si un jour cette piste revient, elle doit prouver un gain net et un cadre de securite fort

Ou ca entre dans Project OS:

- nulle part en v1

Sources primaires:

- [Anthropic - Tool use overview](https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/overview)

## Sources

- [DEEP_RESEARCH_PROTOCOL.md](../workflow/DEEP_RESEARCH_PROTOCOL.md)
