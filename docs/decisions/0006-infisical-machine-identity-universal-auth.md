# 0006 - Infisical Machine Identity via Universal Auth

## Statut

Accepted

## Contexte

Le noyau `Project OS` dependait encore d'une session CLI Infisical ouverte sur le poste fondateur.
Ce n'etait pas bloquant pour le bootstrap, mais ce n'etait pas assez propre pour une base `production-like mono-PC`.

Le risque principal etait structurel:

- dependre d'une session utilisateur Google ouverte
- melanger auth humaine et auth machine
- rendre `doctor --strict` ambigu sur la vraie source d'authentification

## Decision

Le coeur `Project OS` doit sortir du login utilisateur Infisical pour passer sur une **machine identity dediee** avec **Universal Auth**.

Le resolver secrets supporte maintenant, dans cet ordre:

1. `INFISICAL_TOKEN`
2. `INFISICAL_UNIVERSAL_AUTH_CLIENT_ID` + `INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET`
3. fallback session CLI utilisateur uniquement si `mode != infisical_required`

En mode `infisical_required`:

- la simple presence d'un projet lie `.infisical.json` ne suffit plus
- `doctor --strict` ne doit etre vert que si l'auth machine est vraiment exploitable
- la resolution des secrets doit rester `source = infisical`

## Pourquoi Universal Auth

`Universal Auth` est la meilleure option immediate pour `Project OS` car:

- la machine identity est dediee au projet
- l'auth reste locale au poste
- le token d'acces peut etre regenere a la volee depuis `client_id + client_secret`
- on ne depend plus de la session utilisateur Google
- l'integration CLI est simple et scriptable

## Consequences

- les credentials machine ne doivent pas vivre dans le repo
- ils doivent etre ranges dans les variables d'environnement Windows utilisateur ou dans un futur provider machine dedie
- `SecretResolver` expose explicitement:
  - `auth_mode`
  - `machine_auth_ready`
  - `active_token_source`
  - `resolution_ready`

## Notes

La migration est consideree completement terminee seulement lorsque:

- la machine identity `Project OS Machine` existe
- `Universal Auth` est configure
- `Client ID` et `Client Secret` sont ranges sur la machine hors repo
- `doctor --strict` confirme que `Infisical` fonctionne sans dependre de la session utilisateur
