# Project OS Core

Pour la vue globale machine et workflow humain, commencer par [../README.md](../README.md).

`Project OS` est un systeme local-first de copilote PC autonome, supervise et multi-canaux.

Surface produit cible a retenir des maintenant:

- `Project OS.exe` = future entree locale pilotable principale du projet
- `Discord` = surface de discussion, arbitrage et travail distant/parallele
- runtime local = verite machine

Le point important pour un humain comme pour une IA qui arrive sur le projet est simple:

- il n'y a qu'un seul agent systeme
- l'entree locale cible du projet est `Project OS.exe`, avec `Discord` comme surface de discussion et de travail parallele
- la discussion operateur peut passer par l'app locale et par `Discord`, les gros runs de code par `GPT API`, et la revue/traduction humaine par `Claude API`
- le runtime local est la verite machine
- les fichiers runtime sont des preuves, pas l'interface humaine

## Demarrage rapide

Si tu arrives sur le projet:

1. lis ce `README.md`
2. si tu es une IA qui va modifier le repo, lis ensuite [AGENTS.md](./AGENTS.md)
3. si tu travailles sur les gros runs API, lis [API_LEAD_AGENT_V1.md](./docs/integrations/API_LEAD_AGENT_V1.md)
4. si tu travailles sur la surface humaine, lis [DISCORD_OPERATING_MODEL.md](./docs/integrations/DISCORD_OPERATING_MODEL.md)
5. si tu travailles sur la communication de run, lis [RUN_COMMUNICATION_POLICY.md](./docs/architecture/RUN_COMMUNICATION_POLICY.md)
6. si tu travailles sur un arbitrage important, une review avant codage ou une deliberation multi-angles, lis [docs/analysis-angles/README.md](./docs/analysis-angles/README.md) puis [DISCORD_MEETING_SYSTEM_V1.md](./docs/integrations/DISCORD_MEETING_SYSTEM_V1.md)
7. si tu travailles sur la future app locale pilotable, lis [PROJECT_OS_DESKTOP_CONTROL_ROOM_V1_PLAN.md](./docs/roadmap/PROJECT_OS_DESKTOP_CONTROL_ROOM_V1_PLAN.md)
8. si tu dois comprendre la hierarchie exacte des surfaces fondatrices, lis [FOUNDER_SURFACE_MODEL.md](./docs/architecture/FOUNDER_SURFACE_MODEL.md)

## Ce que le systeme doit faire pour un humain

Un humain ne doit pas etre force de lire des JSON dans `runtime/` pour comprendre ce qui se passe.

Le workflow humain cible est:

1. l'humain travaille d'abord dans la surface locale `Project OS.exe` quand elle est disponible, ou dans `Discord` en parallele selon le contexte
2. `Claude API` filtre, traduit et remet les arbitrages humains dans le pipeline
3. `GPT API` cadre, prepare et lance si necessaire
4. l'etat visible remonte dans une surface humaine
5. les fichiers runtime restent consultables comme preuves

Surfaces humaines par ordre d'importance:

1. `Project OS.exe` comme future surface locale pilotable principale
2. `Discord` pour discuter, arbitrer, bloquer, reprendre et travailler a distance
3. dashboard local et terminal live pour supervision locale robuste
4. fichiers runtime pour audit et preuves seulement

## Workflow desktop local

Deux modes existent pour la future surface locale:

- `release stable`: ouvrir `desktop/control-room/dist/win-unpacked/Project OS.exe` ou installer `desktop/control-room/dist/Project OS Setup 0.1.0.exe`
- `dev live`: cliquer `desktop/control-room/Project OS Dev.cmd`

Le mode `dev live` lance l'app directement depuis les sources du repo et recharge la coque Electron quand on modifie le code. Il evite de rebuild l'installateur a chaque passe UI.

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
4. preuve visible pendant le run via dashboard local, terminal live, ou carte compacte deja ouverte
5. signal humain au minimum sur:
   - `clarification_required`
   - fin de run
6. revue et integration

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
- arbitrages visibles dans l'app locale et dans `Discord`

Quand un sujet depasse la simple reponse ou la simple execution, le systeme peut ouvrir une deliberation structuree:

- angles d'analyse bornes
- contradictions ciblees
- synthese arbitree
- `Discord` comme surface lisible
- runtime local comme trace canonique

Aujourd'hui, si un run API travaille sans preuve visible locale, ou sans remonter clairement son blocage ou son verdict dans une vraie surface humaine, le workflow est considere incomplet.
