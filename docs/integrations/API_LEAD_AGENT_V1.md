# API Lead Agent v1

`API Lead Agent v1` est le premier systeme de gros runs de raisonnement et de production dans `Project OS`.

Il expose quatre modes controles :

- `audit`
- `design`
- `patch_plan`
- `generate_patch`

Chaque run suit la meme chaine :

1. construire un `ContextPack`
2. rendre un `MegaPrompt`
3. executer `gpt-5.4`
4. stocker le brut dans le runtime
5. stocker la sortie structuree dans le runtime
6. preparer un paquet de revue
7. laisser `Codex` ou l'humain relire
8. promouvoir les signaux valides dans la couche `learning`

## CLI

Entrees principales :

- `project-os api-runs build-context`
- `project-os api-runs render-prompt`
- `project-os api-runs execute`
- `project-os api-runs review-result`
- `project-os api-runs set-status`
- `project-os api-runs show-artifacts`
- `project-os api-runs monitor`
- `project-os api-runs dashboard`

Aides `learning` :

- `project-os learning confirm-decision`
- `project-os learning change-decision`
- `project-os learning record-loop`
- `project-os learning recommend-refresh`

## Separation du stockage

Dans le repo :

- `config/api_run_templates.json`
- docs validees et ADR

Dans le runtime :

- `D:\ProjectOS\runtime\api_runs\context_packs`
- `D:\ProjectOS\runtime\api_runs\prompts`
- `D:\ProjectOS\runtime\api_runs\raw_results`
- `D:\ProjectOS\runtime\api_runs\structured_results`
- `D:\ProjectOS\runtime\api_runs\review_packages`
- `D:\ProjectOS\runtime\api_runs\reviews`
- `D:\ProjectOS\runtime\api_runs\latest_terminal_snapshot.json`

## Supervision visuelle

Le lead agent expose aussi un dashboard web local.

Lancement :

- `py D:\ProjectOS\project-os-core\scripts\project_os_entry.py api-runs dashboard --open-browser`
- ou `D:\ProjectOS\project-os-core\scripts\project_os_api_dashboard.ps1 -OpenBrowser`

Le dashboard actuel est :

- en francais
- compact
- centre sur `Execution en cours`
- avec terminal integre dans le bloc principal
- avec colonne droite plus legere pour `Budget`, `Apercu`, `Artefacts`, `Historique` et `Regles`
- avec IDs et chemins longs compactes pour eviter les debordements

Validation reelle deja faite :

- lancement live du dashboard local
- mini run API reel `audit`
- mise a jour du budget et des artefacts en temps reel

## Contrat de surface humaine

Le runtime stocke des preuves sous `runtime/api_runs/`.

Mais:

- ces fichiers ne sont pas une interface humaine
- un humain ne doit pas devoir lire `raw_results` ou `structured_results` pour suivre un run

Le minimum produit attendu pour un gros run est:

1. une surface de supervision locale
2. une surface de conversation humaine
3. une remontee claire des blocages et des verdicts

En cible:

- dashboard local = preuve visuelle que le run vit vraiment
- terminal live = supervision robuste
- `Discord` = canal humain principal pour discuter, arbitrer et recevoir les clarifications ou rapports finaux

Si `Discord` n'est pas encore completement branche pour cette boucle:

- c'est un manque de workflow
- pas un comportement normal a accepter

## Politique de revue

- aucun run n'ecrit directement dans `main`
- aucun run ne contourne le `Mission Router`
- `Codex` garde le role d'inspection locale
- les runs acceptes, rejetes ou a revoir alimentent `learning`

## Contradiction guard

Les quatre modes `audit`, `design`, `patch_plan` et `generate_patch` peuvent stopper pour clarification.

Workflow cible:

1. le run detecte une ambiguite ou contradiction majeure
2. il passe en `clarification_required`
3. il produit un rapport de clarification structure
4. le contrat courant est amende
5. un nouveau `go` est enregistre
6. le run repart sur le contrat amende

## Politique d'apprentissage

La couche `learning` promeut :

- `DECISION CONFIRMED`
- `DECISION CHANGED`
- les signaux de patch rejete
- les signaux de boucle
- les recommandations de refresh
- les candidats dataset/eval

But :

- ne pas oublier les bonnes decisions
- ne pas repeter les mauvaises
- garder une progression cumulative et propre
