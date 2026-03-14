# Mini Roadmap Patch - 14 mars 2026

## But

Garder une feuille de route courte pour ne pas perdre le cap.

Cette note ne change pas la cible d'architecture.
Elle change seulement l'ordre d'execution:

- pragmatique pour le premier vrai test live
- professionnelle pour la suite
- pensee 2-3 coups a l'avance

## Regle de lecture

- `Now` = ce qu'on fait pour brancher et prouver le live
- `Next` = ce qu'on ajoute juste apres pour fermer la boucle qualite
- `Later` = ce qu'on active quand le systeme tourne vraiment

Le bon test a garder en tete:

> est-ce que cette decision tient encore quand l'agent fait 100 runs par jour au lieu de 3 ?

## Now

### 1. Premier setup live minimal

Objectif: ne pas perdre du temps en infra prematuree.

- garder un setup local simple pour le premier smoke test
- `gh auth login` interactif suffit pour maintenant
- brancher les vraies cles `OPENAI_API_KEY` et `ANTHROPIC_API_KEY`
- creer le bot Discord de test et stocker `DISCORD_BOT_TOKEN`

## 2. Premier smoke test end-to-end

Objectif: prouver la boucle complete en vrai.

- message reel `Discord -> OpenClaw -> Gateway -> Mission Router`
- run reel `GPT -> Claude reviewer -> Claude translator`
- notification retour sur Discord
- verifier que rien ne contourne la verite canonique locale

## 3. Fixer les derniers frottements live

Objectif: corriger apres preuve, pas avant.

- finir les derniers blocages live observes
- durcir `doctor` avec les checks manquants reellement utiles
- declarer "ready" seulement apres preuve d'un message entrant et sortant reel

## Next

### 4. Fermer la boucle review -> revision -> review

Objectif: sortir du rerun manuel.

- si le reviewer renvoie `needs_revision`, relancer automatiquement
- injecter le feedback reviewer dans le prompt suivant
- re-reviewer apres correction
- mettre des garde-fous durs:
  - max `2` ou `3` iterations
  - budget cap
  - stop si la critique se repete

## 5. Exploiter vraiment GitHub Issues comme memoire de fiabilite

Objectif: transformer les bugs resolus en apprentissage durable.

- faire tourner le sync GitHub sur de vraies issues closes
- verifier que les resolutions remontent bien dans `learning`
- utiliser ces signaux pour eviter les regressions et les patterns repetes

## 6. Ajouter un Mission Planner en mode suggestion

Objectif: passer d'executant a joueur d'echecs sans autonomie prematuree.

- ne pas laisser l'agent improviser une chain complete sans garde-fou
- commencer par un planner qui propose la chain la plus solide
- raisonner en sequence, dependances, reutilisation, kill criteria
- viser un planner qui voit `2-3` coups d'avance avant execution

## Later

### 7. Scheduler proactif base sur les signaux

Objectif: faire reflechir le scheduler au lieu de seulement nettoyer.

- lancer des audits ou optimisations a partir des metriques reelles
- ne l'activer qu'apres stabilisation du live
- ne jamais ajouter de proactivite sans levier mesurable

## 8. Passer en mode exploitation propre

Objectif: professionnaliser quand le systeme n'est plus seulement local.

- identite projet dediee
- `GH_TOKEN` non interactif
- `Infisical` / secrets propres selon le mode d'exploitation retenu
- readiness multi-machine
- preparation delegation / collaboration / jobs autonomes

Declencheurs pour ce passage:

- deuxieme machine
- scheduler autonome reel
- collaborateur
- besoin de runs sans presence humaine

## Non-negociables

- pas de bricolage
- pas d'ambiguite silencieuse
- pas de side effects sans trace
- pas de complexite sans levier reel
- pas de vision sans ordre d'execution

## Doctrine de priorite

Avant d'ajouter une nouvelle couche d'intelligence, verifier dans cet ordre:

1. la boucle live est-elle prouvee ?
2. la boucle qualite est-elle fermee ?
3. la decision est-elle tracable ?
4. la nouvelle complexite apporte-t-elle un vrai levier ?

Si la reponse est non, on consolide avant d'ajouter.
