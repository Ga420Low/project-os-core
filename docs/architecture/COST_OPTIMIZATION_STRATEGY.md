# Cost Optimization Strategy

Ce document definit les strategies d'optimisation des couts de Project OS.

## Budget cible

| Metrique | Valeur |
|----------|--------|
| Cout journalier type | ~3.50 EUR |
| Cout mensuel cible | <110 EUR |
| Runs par jour (type) | 5-8 |
| Budget alerte | 80% du plafond journalier |
| Budget blocage | 100% du plafond journalier |

## Politique de modele

Defini dans ADR 0003. Le modele par defaut est `gpt-5.4 high`.

| Complexite | Modele | Cout relatif |
|------------|--------|-------------|
| Banal (pattern connu) | `medium` | 1x |
| Standard (run normal) | `high` | 3x |
| Complexe (architecture) | `xhigh` | 8x |
| Exceptionnel (innovation) | `pro` | 20x |

Regle: jamais de `pro` sans approbation explicite du fondateur.
Le Guardian verifie le niveau de modele avant chaque appel.

## Decomposition du cout journalier

Journee type avec 5 runs:

| Composant | Calcul | Cout |
|-----------|--------|------|
| GPT API (cerveau) | 5 runs x ~100k tokens in x ~2k out | ~2.50 EUR |
| Claude API (auditeur) | 5 reviews x ~30k tokens in x ~3k out | ~1.20 EUR |
| Claude API (traducteur) | ~10 traductions x ~500 tokens | ~0.01 EUR |
| Embeddings | ~50 requetes x ~1k tokens | ~0.02 EUR |
| **Total** | | **~3.73 EUR** |

## Strategies d'optimisation

### 1. Context pack intelligent

Le context pack est le plus gros facteur de cout (tokens en entree).

Strategies:
- inclure seulement les fichiers pertinents (pas tout le projet)
- tronquer les fichiers longs aux sections relevantes
- utiliser des resumes plutot que le contenu brut pour les docs de reference
- maximum 200k tokens par context pack (sur 1M disponible)

### 2. Cache de prompts

| Type | TTL | Economie |
|------|-----|----------|
| Context packs identiques | 1h | Evite de reassembler |
| Embeddings de fichiers stables | 24h | Evite de re-embed |
| Resultats de review identiques | Session | Evite de re-auditer |

Regle: le cache est invalide si un fichier source change.

### 3. Batching des operations

- grouper les petites ecritures SQLite en transactions
- grouper les embeddings par lots de 20+
- grouper les notifications Discord en un seul message resume

### 4. Eviter les appels inutiles

Le Persistent Session State (SQLite) resout la plupart des interactions Discord sans appel API:

| Interaction | Cout |
|-------------|------|
| Message Discord resolu par le state | 0 EUR |
| Message ambigu escalade a Claude | ~0.001 EUR |
| Run complet GPT | ~0.50 EUR |

Objectif: 80% des messages Discord resolus a 0 EUR.

### 5. Learning loop

Les decisions confirmees alimentent le context pack des runs suivants.
Resultat: moins de `clarification_required`, donc moins de cycles.

Objectif: apres 1 mois, reduire les clarifications de 50%.

## Guardian pre-spend

Avant chaque appel API couteux:

1. verifier le budget restant du jour
2. verifier le nombre de runs actifs
3. detecter les boucles (3+ runs meme branche en 2h)
4. si budget depasse → bloquer et notifier
5. si boucle detectee → bloquer et notifier

```
budget_remaining = daily_limit - daily_spend
if budget_remaining < estimated_cost:
    block_run("budget_exceeded")
    notify_founder("Budget jour depasse")
```

## Token counting

Avant chaque appel API, estimer le nombre de tokens:

- context pack tokens = estimation basee sur la taille des fichiers
- prompt tokens = taille du MegaPrompt rendu
- output tokens = estimation basee sur le mode (audit ~3k, design ~5k, patch ~10k)

L'estimation est conservative (+20%) pour eviter les depassements.

## Calculateur canonique

Regle dure:

- toute surface qui affiche un `cout estime` doit passer par le calculateur canonique partage
- le calculateur canonique est `src/project_os_core/costing.py`
- les features ne doivent pas reintroduire des montants plats du type `0.05 / 0.13 / 0.27 EUR` dans leur propre code

Le calculateur canonique doit centraliser:

- la table de prix par modele
- la conversion `USD -> EUR`
- les heuristiques de tokens quand aucun provider count API n'est disponible
- les helpers communs `usage -> cout`

Regle d'implementation:

- si le provider expose un vrai comptage avant appel, il faut le preferer
- sinon, utiliser le fallback partage du calculateur canonique
- une feature ne doit pas inventer son propre estimateur local sans justification forte et sans mise a jour du calculateur partage

Application actuelle:

- `gateway` Discord / approvals / modes `simple / avance / extreme`
- `router` pour les estimations de mission
- `api_runs` pour les couts estimes issus de l'usage runtime

But produit:

- une seule logique de cout, plusieurs surfaces
- estimation coherente entre Discord, dashboard, router, runs API et futures lanes voice

## Estime vs reel

La verite produit doit distinguer:

- `cout estime avant run`
- `cout reel apres run`

Une UI ou un bot peut afficher une estimation, mais il ne doit pas laisser croire qu'elle est exacte au centime.

Formulation recommandee:

- `Cout estime: ~X EUR`
- puis, si la runtime truth existe, `Cout reel: Y EUR`

## Providers et precision

Precision attendue:

- `Anthropic`: utiliser le comptage officiel pre-run quand il est disponible
- `OpenAI` ou autres voies sans comptage pre-run branche: utiliser le fallback heuristique canonique
- `local`: afficher `0 EUR` seulement si aucune API externe n'est engagee

La priorite est:

1. comptage officiel provider
2. calculateur partage
3. jamais de hardcode local specifique a une feature

## Alertes

| Seuil | Action |
|-------|--------|
| 50% du budget jour | Log interne (pas de notification) |
| 70% du budget jour | Log + indicateur dashboard |
| 80% du budget jour | Notification fondateur sur Discord |
| 100% du budget jour | Bloquer les runs non urgents |
| 120% du budget jour | Bloquer tous les runs |

## Optimisation future

- prompt compression (resumer le contexte plutot que le copier)
- context reuse entre runs de la meme mission
- model downgrade automatique si le budget est serre
- cache distribue si multi-machine

## References

- `docs/decisions/0003-model-policy-gpt54-high-default.md`
- `docs/decisions/0013-dual-model-operating-model.md`
- `docs/integrations/API_LEAD_AGENT_V1.md`
- `docs/architecture/MEMORY_STORAGE_AND_OPS_BLUEPRINT.md`
