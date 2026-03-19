# Project OS Agentic Git Workflow Contract

## Statut

ACTIVE - Pack 0 locked contract

## But

Definir comment le code bouge entre:

- l'humain
- le `remote runner`
- le `local runner`
- `GitHub`
- la maison mere `Project OS`

Sans salir la verite du code ni casser le travail humain.

## Workflow operateur canonique

Le workflow a respecter est:

1. `discuss`
2. `try in preview`
3. `save branch`
4. `open PR`
5. `merge`

Regles:

- `discuss` n'ecrit rien
- `try in preview` modifie un workspace runner sans push obligatoire
- `save branch` conserve sur `GitHub`
- `open PR` ouvre la review
- `merge` reste une decision distincte

## Verite canonique

- `GitHub` = verite du code
- `Project OS DB` = verite operateur des propositions, approvals, reviews et evidence

## Regle racine

Un agent ne modifie jamais directement le clone humain Windows comme source canonique.

Il travaille dans:

- un workspace runner isole

Et il rend:

- un patch
- une branche
- une PR
- ou un `GitChangeProposal`

Par defaut, le premier retour attendu pour un changement est:

- un workspace de preview
- puis un `GitChangeProposal`
- pas un merge

## Objet canonique

L'objet central de workflow Git agentique est:

- `GitChangeProposal`

Il doit porter au minimum:

- `gitprop_id`
- repo cible
- base branch
- mode de retour (`patch`, `branch`, `pr`)
- resume humain
- refs d'artefacts ou preuves
- statut

## Statuts recommandes

- `proposed`
- `prepared`
- `reviewed`
- `approved`
- `rejected`
- `merged`
- `superseded`

## Inputs obligatoires

Pour lancer un run code, le systeme doit avoir:

1. repo cible
2. ref de base
3. scope de travail
4. policy de retour Git
5. approvals necessaires

## Outputs obligatoires

Le workflow Git doit produire:

1. `GitChangeProposal`
2. `RunEvent`
3. `ArtifactRef`
4. `ActionEvidence`

Selon le cas:

- patch texte
- branche distante
- PR
- preview URL ou preuve de preview

## Preview policy

Pour une demande de changement, le systeme doit preferer:

1. workspace runner
2. preview/test
3. diff visible
4. seulement ensuite push de branche si confirme

Le preview peut etre:

- visuel pour UI
- comportemental pour backend

## Interdits

Le workflow Git agentique ne doit pas:

- pousser directement dans `main`
- ecrire dans le clone humain Windows
- cacher des modifs critiques hors `GitChangeProposal`
- faire d'un log de run un substitut a une review
- exiger un push `GitHub` juste pour voir un changement

## Politique de promotion

Ordre canonique:

1. proposition
2. execution en workspace runner
3. preuves et artefacts
4. review
5. confirmation humaine si necessaire
6. merge

Le merge n'est jamais un effet implicite du run lui-meme.

## Politique de conflit

Si la base branche a diverge:

- le run ne fait pas semblant d'avoir reussi
- il produit:
  - un echec propre
  - ou une nouvelle proposition de rebase/refresh

## Failure modes

### Dirty workspace

Reaction:

- reset du workspace runner
- jamais du clone humain

### Git auth fail

Reaction:

- patch exportable si possible
- sinon blocage propre

### Merge conflict

Reaction:

- proposition de resolution
- pas de merge silencieux

## Acceptance checks

Le contrat sera considere respecte quand:

1. le clone humain Windows n'est jamais cible d'ecriture agent
2. les agents rendent un `GitChangeProposal` propre
3. `main` n'est jamais mutee directement par un runner
4. une divergence de branche est visible dans la timeline
5. `Project OS` peut lier un run a une proposition Git sans dupliquer la verite du code
6. un changement UI ou app peut etre vu avant push `GitHub`

## References

- `docs/architecture/PROJECT_OS_CHAT_TO_PREVIEW_AND_GIT_CONTRACT.md`
- `docs/architecture/PROJECT_OS_CANONICAL_DATA_MODEL_CONTRACT.md`
- `docs/integrations/API_RUN_CONTRACT.md`
- `C:/Users/theod/.codex/skills/project-os-git-flow/SKILL.md`
