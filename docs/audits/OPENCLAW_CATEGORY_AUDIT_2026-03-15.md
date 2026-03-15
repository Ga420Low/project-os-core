# OpenClaw Category Audit 2026-03-15

## Scope

Audit cible `OpenClaw + Discord + lane locale Windows-first`.

Sources retenues:

- `openclaw doctor`
- `openclaw truth-health --channel discord`
- `openclaw validate-live --channel discord`
- `doctor --strict`
- `router model-health`
- runtime `D:/ProjectOS/runtime/openclaw/openclaw.json`
- tests repo et tests gateway

## Verdict

Etat `fort`, mais pas "magiquement parfait".

Niveau reel retenu:

- facade `OpenClaw` saine
- policy Discord durcie
- trust boundary plugin/pairing bornee
- lane locale Windows-first reelle via `Ollama`
- `S3` traite localement quand la voie locale est prete
- blocage ferme si la voie locale tombe

Verdict d'ensemble:

- `doctor --strict`: `ready`
- `openclaw doctor`: `OK`
- `openclaw truth-health --channel discord`: `OK`
- `openclaw validate-live --channel discord`: `success = true`

## Etat prouve

- gateway `OpenClaw` gere par tache planifiee Windows
- listener local actif et RPC joignable
- runtime `OpenClaw` relie au plugin `project-os-gateway-adapter`
- `threadBindings`, `autoPresence`, `execApprovals` actifs
- allowlist plugin explicite
- secrets live sortis du snapshot runtime
- voie locale reelle:
  - provider `ollama`
  - URL `http://127.0.0.1:11434`
  - modele `qwen2.5:14b`
- `S3`:
  - route `s3_local_route` si la voie locale est `ready`
  - blocage si la voie locale n'est pas `ready`
  - jamais de fallback cloud

## Findings

### [P1] La doc melange encore deux niveaux de preuve live

Le runtime accepte maintenant une `preuve canonique enregistree`:

- un event `source=openclaw`
- passe par `Gateway -> Mission Router`
- laisse une trace `channel_event + dispatch + decision/mission`

C'est ce que lisent aujourd'hui `truth-health` et `validate-live`.

Mais cette preuve n'est pas identique a une `preuve operateur manuelle Discord reelle` avec un message utilisateur observe depuis le reseau Discord.

Conclusion:

- la preuve canonique existe
- la preuve operateur manuelle reste une marche plus stricte
- les docs doivent le dire explicitement

### [P1] Plusieurs docs racontent encore une histoire pre-lane-locale

Exemples:

- "aucun vrai modele local"
- "local absent par defaut"
- "`S3` souvent bloque"

Ce n'est plus vrai sur le poste cible actuel.

### [P2] Un runbook Discord garde du mojibake

`OPENCLAW_DISCORD_OPERATIONS_UX.md` contenait encore un mot corrompu par encodage.

## Conclusion

La categorie `OpenClaw` est maintenant suffisamment mature pour etre exploitee serieusement.

Le point restant a distinguer proprement n'est plus la sante technique de la pile.
C'est la difference entre:

- `preuve canonique runtime`
- `preuve operateur manuelle Discord reelle`

Les docs canoniques doivent maintenant refleter cette distinction sans ambiguite.
