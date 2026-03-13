# Handoff Conversation Suivante

## Etat reel au 13 mars 2026

- `Project OS` force maintenant une control room locale avant un vrai run API.
- Le dashboard ne doit plus seulement "tourner en fond": il doit recevoir un beacon live du navigateur.
- Si ce beacon n'arrive pas, le run echoue ferme.

## Ce qui a ete fini

- snapshot live du dashboard pendant les runs
- auto-demarrage du dashboard avant run
- auto-ouverture du navigateur sur le PC
- beacon de visibilite navigateur -> dashboard
- garde-fou documente: une implementation n'est pas validee par la conversation seule

## Preuves code deja posees

- `src/project_os_core/api_runs/dashboard.py`
  - bootstrap dashboard
  - ouverture UI
  - beacon `/api/operator-beacon`
- `src/project_os_core/api_runs/service.py`
  - blocage ferme si la control room n'est pas visible
- `tests/unit/test_api_run_service.py`
  - test beacon HTML
  - test fail-closed si UI non verifiee

## Prochain lot recommande

Finir `OpenClaw live` avant `LangGraph live`.

Ordre conseille:

1. valider les tests et la vraie preuve du beacon
2. lancer un vrai message `Discord` ou `WebChat`
3. prouver `OpenClaw -> Gateway -> Mission Router`
4. produire une vraie carte `#runs-live`
5. seulement ensuite ouvrir `LangGraph live`

## Ce que le prochain agent doit garder en tete

- ne pas se fier a la memoire de conversation
- ne pas declarer "live" tant qu'un vrai message entrant n'a pas ete prouve
- ne pas laisser `OpenClaw` contourner la verite canonique
- garder toutes les sorties operateur en francais clair
- utiliser l'API grande fenetre pour les patch-plans lourds, puis verifier localement
