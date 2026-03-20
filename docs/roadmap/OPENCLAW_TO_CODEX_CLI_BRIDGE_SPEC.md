# OpenClaw To Codex CLI Bridge Spec

## Statut

ACTIVE

## But

Figer le lien cible entre:

- `OpenClaw` comme cockpit/runtime
- `Project OS` comme couche entreprise
- `Codex CLI` comme moteur officiel d'execution code/shell/patch

## Chaine retenue

```text
OpenClaw UI
  -> OpenClaw runtime
    -> Project OS execution bridge
      -> Codex CLI runner
        -> workspace Git isole
```

## Regles

1. `OpenClaw` ne remplace pas `Codex CLI` pour l'execution
2. `Codex CLI` ne devient pas une verite metier concurrente
3. `Project OS` garde les objets canoniques:
   - run
   - task
   - decision
   - evidence
   - approval
4. le clone humain ne doit jamais etre la cible de run par defaut

## Ce que le bridge doit exposer

Minimum:

1. prompt operateur / mission
2. mode d'execution
3. workspace cible
4. sortie streaming
5. resultat final
6. statut run
7. liens vers artefacts produits

Sorties attendues cote `Codex CLI`:

- `patch`
- `branch`
- `PR proposal`
- logs et terminal output utiles

## Ce que l'UI OpenClaw doit voir

L'UI `OpenClaw` doit pouvoir afficher:

1. qu'un run part sur `Codex CLI`
2. dans quel mode
3. dans quel workspace
4. son statut
5. ses sorties principales

L'UI n'a pas besoin de devenir toute la verite execution.

## Horizon

Decision:

- `EXTEND NOW`

Pourquoi:

- c'est la prochaine vraie brique de valeur
- sans ce lien, `OpenClaw` reste un bon cockpit mais pas encore notre systeme de production code

## Reference

- `docs/roadmap/PROJECT_OS_V1_OPENCLAW_ENTERPRISE_EXECUTION_PLAN.md`
- `docs/roadmap/OPENCLAW_UI_KEEP_1TO1_AND_EXTEND_MATRIX.md`
