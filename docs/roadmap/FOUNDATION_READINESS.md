# Foundation Readiness

## Decision

Project OS doit etre construit comme un produit separe du repo UEFN.
Le coeur vise la version finale suivante:

- `OpenClaw` pour le shell operateur et Discord
- `LangGraph` pour l'orchestration durable
- `OpenMemory` pour la memoire long terme primaire
- `GPT API` pour le cerveau
- `UFO` style worker pour Windows
- `Stagehand` pour le web
- `pywinauto` et UIA pour la perception structuree
- `OmniParser` en secours vision
- `WindowsAgentArena`, `OSWorld`, `WorldGUI` pour l'evaluation
- `Letta` comme backup et benchmark memoire

`DECISION CONFIRMED`

Le socle de production reste `Windows-first`.
`WSL2` est retenu comme extension future possible pour des cellules de travail isolees par projet, pas comme fondation unique du produit.

Reference:

- `docs/architecture/WINDOWS_FIRST_HOST_AND_WSL_FABRIC.md`

## Etat actuel

Le repo socle est pose.
Les briques suivantes sont deja presentes localement dans l'ancien workspace:

- `UFO`
- `pywinauto-mcp`
- `WindowsAgentArena`
- `GroundCUA`
- `gstack-main`
- `sigstack-main`

Les briques suivantes ne sont pas encore presentes localement:

- aucune pour la stack cible immediate

## Outillage local verifie

Disponibles:

- `python 3.14.3`
- `git 2.53.0.windows.1`
- `node 24.14.0`
- `npm 11.9.0`
- `pnpm 10.32.1`
- `uv 0.10.9`
- `pip 25.3`
- `infisical cli 0.43.58`

Manquants ou non exploitables pour la stack cible:

- `docker`
- `bun`
- `poetry`
- `rg` reste ambigu a cause de l'alias embarque par l'environnement local, mais ce n'est pas un blocage noyau

## Verdict

La vision finale est verrouillee, et l'environnement est maintenant suffisant pour commencer l'integration du noyau.

Etat reel de la fondation:

- `OpenMemory` branche et valide
- `SQLite + sqlite-vec` branches et valides
- `Memory OS` local branche et valide
- blocs partages / thoughts / curator / supersession poses
- `Mission Router` branche et valide
- frontiere `OpenClaw` vs `Project OS` figee
- policy `Discord selective sync` posee
- graphe mission canonique a 6 roles pose
- adaptateur gateway interne `ChannelEvent -> Mission Router` implemente
- `ExecutionTicket` emis par le graphe canonique, pas par la facade operateur
- `Infisical` installe et relie au repo
- projet secrets dedie cree: `Project OS Core`
- secret `OPENAI_API_KEY` migre dans `Infisical`
- policy locale passee en `infisical_required`
- support `Universal Auth` ajoute dans le resolver
- credentials `Universal Auth` ranges sur la machine hors repo
- `doctor --strict` vert sans dependre d'une session utilisateur

Points encore non critiques:

1. `docker` reste absent si on veut executer certains quickstarts ou services isoles.
2. Il faudra figer la strategie de dependances du repo (`python`, `node`, ou dual stack`).
3. Il faudra choisir si `third_party/` reste un cache de lecture ou devient un espace de reference plus structure.
4. `OpenClaw` est maintenant branche jusqu'au runtime live et a la voie locale Windows-first; `LangGraph` reste le prochain gros branchement.
5. Le reste du chantier `OpenClaw` tient surtout a la preuve operateur manuelle Discord/WebChat, pas a l'absence d'integration coeur.
6. La trajectoire `multi-WSL` est admise pour plus tard, mais sous supervision du host Windows et sans deplacer la verite runtime hors de l'hote.

## Regle de demarrage

Le branchement live coeur `OpenClaw` est maintenant pose.

Les prochains chantiers utiles sont:

1. cloturer la preuve operateur manuelle `Discord` / `WebChat`
2. brancher `LangGraph` sur les interfaces deja figees
3. garder `OpenClaw` comme facade durcie, pas comme seconde source de verite

Le renforcement post-bootstrap d'`OpenClaw` suit maintenant la feuille de route:

- `docs/roadmap/OPENCLAW_REINFORCEMENT_PLAN.md`

La couche de securite `sanctuaire` devient aussi un chantier explicite:

- `docs/roadmap/SANCTUARY_SECURITY_LAYER.md`
