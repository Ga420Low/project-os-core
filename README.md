# Project OS Core

Pour la vue globale machine et workflow humain, commencer par [../README.md](../README.md).

`Project OS` est un systeme local-first de copilote PC autonome, supervise et multi-canaux.

Le point important pour un humain comme pour une IA qui arrive sur le projet est simple:

- il n'y a qu'un seul agent systeme
- `Codex`, les runs `OpenAI API`, `Discord` et plus tard `WebChat` sont des surfaces du meme agent
- le runtime local est la verite machine
- les fichiers runtime sont des preuves, pas l'interface humaine

## Demarrage rapide

Si tu arrives sur le projet:

1. lis ce `README.md`
2. si tu es une IA qui va modifier le repo, lis ensuite [AGENTS.md](./AGENTS.md)
3. si tu travailles sur les gros runs API, lis [API_LEAD_AGENT_V1.md](./docs/integrations/API_LEAD_AGENT_V1.md)
4. si tu travailles sur la surface humaine, lis [DISCORD_OPERATING_MODEL.md](./docs/integrations/DISCORD_OPERATING_MODEL.md)
5. si tu travailles sur la communication de run, lis [RUN_COMMUNICATION_POLICY.md](./docs/architecture/RUN_COMMUNICATION_POLICY.md)

## Ce que le systeme doit faire pour un humain

Un humain ne doit pas etre force de lire des JSON dans `runtime/` pour comprendre ce qui se passe.

Le workflow humain cible est:

1. l'humain parle dans `Codex` ou `Discord`
2. `Codex` cadre, prepare et lance si necessaire
3. le gros run API travaille en silence pendant l'execution
4. l'etat visible remonte dans une surface humaine
5. les fichiers runtime restent consultables comme preuves

Surfaces humaines par ordre d'importance:

1. `Discord` pour discuter, arbitrer, bloquer, reprendre, recevoir le resultat
2. dashboard local pour voir que le run vit vraiment
3. terminal live pour supervision locale robuste
4. fichiers runtime pour audit et preuves seulement

## Regle produit a retenir

Les artefacts suivants ne sont pas des interfaces humaines:

- `runtime/api_runs/raw_results/*.json`
- `runtime/api_runs/structured_results/*.json`
- `runtime/api_runs/latest_terminal_snapshot.json`

Ils servent a:

- prouver
- rejouer
- auditer
- debugger

Ils ne doivent pas etre le point d'entree principal d'un operateur.

## Workflow attendu pour un gros run API

1. contrat court comprehensible
2. validation humaine
3. execution silencieuse
4. signal humain au minimum sur:
   - demarrage
   - `clarification_required`
   - fin de run
5. revue et integration

Si un run a besoin d'une clarification:

- il doit s'arreter
- il doit poser une seule question bloquante si possible
- il doit remonter cette question dans une surface humaine
- il ne doit pas forcer l'humain a fouiller les artefacts techniques

## Vision cible

Le systeme n'est pas un simple chatbot.
Mais il ne doit pas non plus se comporter comme un batch muet que seul un developpeur sait lire.

La bonne cible est:

- cerveau unique
- plusieurs surfaces
- preuves fortes
- interface humaine simple
- arbitrages visibles dans `Discord`

Aujourd'hui, si un run API travaille mais ne remonte pas clairement son demarrage, son blocage ou son verdict dans une vraie surface humaine, le workflow est considere incomplet.
