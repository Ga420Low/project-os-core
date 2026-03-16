# Deep Research Simple Mode

## Statut

- `active`

## But

- fixer le contrat du mode `simple`
- eviter qu'un run leger se transforme en pseudo-comite mal controle

## Point de depart reel

- `Project OS` avait deja un moteur de deep research structure
- le besoin nouveau est de separer `profil` et `intensite`
- le mode `simple` doit rester la voie rapide et propre

## Hypothese de travail

- un seul worker fort suffit pour beaucoup de dossiers
- la qualite vient du protocole et du repo-first, pas d'un comite obligatoire

## A faire

### Single-worker research lane

Etat:

- `A_FAIRE`

Pourquoi il compte:

- il couvre la majorite des audits normaux sans latence ou cout excessifs

Ce qu'on recupere:

- repo context
- un main pass
- une traduction lecteur FR
- rendu Markdown EN + PDF FR

Ce qu'on n'importe pas:

- comite complet
- scout swarm

Preuves a obtenir:

- le job `simple` publie bien Markdown + PDF
- l'archive garde manifest, result et reader payload

Ou ca entre dans Project OS:

- `deep_research.py`
- `deep_research_pdf.py`
- `docs/workflow/DEEP_RESEARCH_INTENSITY_STANDARD.md`

Sources primaires:

- [OpenAI - Introducing deep research](https://openai.com/index/introducing-deep-research/)
- [Anthropic - Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)

## A etudier

### Auto-upgrade from simple to complex

Etat:

- `A_ETUDIER`

Pourquoi il compte:

- certains sujets demarrent legers puis meritent plus de profondeur

Ce qu'on recupere:

- un futur signal de downgrade/upgrade

Ce qu'on n'importe pas:

- une escalation automatique opaque

Preuves a obtenir:

- prouver que l'upgrade reduit les angles morts sans surprendre l'operateur

Ou ca entre dans Project OS:

- `gateway`
- `deep_research`

Sources primaires:

- [OpenAI - Deep research FAQ](https://help.openai.com/en/articles/10500283-deep-research)

## Sources

- [DEEP_RESEARCH_PROTOCOL.md](../workflow/DEEP_RESEARCH_PROTOCOL.md)
