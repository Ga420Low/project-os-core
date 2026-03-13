# Hybrid Large-Context Workflow

Ce document fixe le workflow officiel entre:

- `Codex`
- `OpenAI API` grande fenetre de contexte
- `Project OS` runtime local

L'objectif est simple:

- utiliser la grande fenetre de contexte de l'API pour penser plus large
- garder `Codex` comme inspecteur, integrateur et verificateur
- garder le runtime local comme verite reelle

## Role de chaque couche

### OpenAI API 1M

L'API grande fenetre est la force de frappe principale pour:

- audit massif
- design systeme
- comparaison d'options
- patch-plan de gros lot
- generation de branche complete sous contrainte
- coherence globale d'un chantier long

L'API est donc le `Lead Agent`.

Elle peut:

- raisonner
- planifier
- produire une implementation cible
- generer un patch-plan detaille
- proposer un patch ou pseudo-patch
- controler un lot complet a travers le runtime plus tard

Elle ne devient jamais:

- la verite du repo
- la verite machine
- la verite memoire canonique

### Codex

`Codex` reste le `Command Board`.

Roles:

- preparer les context packs
- preparer les mega prompts
- challenger les solutions
- inspecter les patchs
- comparer la sortie API au repo reel
- appliquer proprement dans le repo
- lancer les tests
- corriger les ecarts
- tenir la coherence globale

Regle dure:

- `Codex` ne s'efface pas devant l'API
- `Codex` agit comme inspecteur severe et integrateur

### Project OS Runtime

Le runtime local reste la verite pour:

- etat machine
- memory canonique
- approvals
- evidence
- health
- sessions
- workers

Regle dure:

- ni `Codex`
- ni l'API

ne remplacent le runtime reel.

## Workflow officiel

### Phase A - Direction

Ici, humain + Codex decident:

- quelle branche ou quel lot on ouvre
- quel resultat exact on attend
- quelles contraintes sont non negociables
- quels risques doivent etre evites
- quels fichiers et quelles interfaces sont concernes

### Phase B - Context Pack

On prepare un `context pack` propre.

Contenu minimal:

- objectif du lot
- etat actuel du repo
- docs maitre
- ADR et policies utiles
- fichiers cles
- derniers tests et limitations
- questions precises
- criteres d'acceptation

Le `context pack` doit etre:

- compact
- versionne
- sans bruit inutile
- centre sur un lot coherent

### Phase C - Mega Prompt

On envoie un `mega prompt` a l'API.

Le mega prompt doit contenir:

- identite de l'agent
- role de l'agent
- mission du lot
- contraintes produit
- contraintes architecture
- contraintes budget/securite
- format de sortie obligatoire
- skill tags du run

### Phase D - Run API

L'API travaille sur:

- `audit`
- `design`
- `patch-plan`
- `generate-patch`

Le run API doit produire une sortie structuree.

### Phase E - Inspection

On revient dans `Codex`.

`Codex` doit:

- verifier la coherence
- verifier le repo reel
- verifier les interfaces
- verifier les risques
- verifier les tests a lancer
- corriger les erreurs de raisonnement

### Phase F - Integration

Seulement apres inspection:

- on ecrit le code
- on modifie les fichiers
- on lance les tests
- on documente
- on commit si demande

## Types de runs autorises

### Audit Run

But:

- auditer un systeme ou un lot complet

Sortie attendue:

- findings
- risques
- dette
- incoherences
- recommandations
- ordre de correction

### Design Run

But:

- figer une architecture ou une decision systeme

Sortie attendue:

- decision
- alternatives
- tradeoffs
- interfaces
- risques
- acceptance gates

### Patch-Plan Run

But:

- decrire exactement comment coder un lot

Sortie attendue:

- fichiers a creer/modifier
- types/interfaces
- ordre de travail
- tests
- risques
- checklist d'acceptation

### Generate-Patch Run

But:

- produire un draft de patch pour un lot deja bien borne

Sortie attendue:

- diff ou pseudo-diff
- commentaires de design
- tests attendus

Regle:

- un `generate-patch` ne saute jamais la phase d'inspection locale

## Skills de mega prompt

Les `skills` de mega prompt sont des etiquettes de run qui disent a l'API quel mode de travail adopter.

Ils ne remplacent pas les skills Codex locaux.

Base minimale:

- `CODE`
- `AUDIT`
- `DESIGN`
- `PATCH_PLAN`
- `GENERATE_PATCH`
- `UEFN`
- `WINDOWS`
- `BROWSER`
- `MEMORY`
- `SECURITY`
- `OPS`

Exemples:

- `CODE + WINDOWS + MEMORY`
- `AUDIT + UEFN + SECURITY`
- `PATCH_PLAN + BROWSER + OPS`

Regle:

- chaque mega prompt doit declarer explicitement ses skills de run
- chaque run doit rester borne a un lot ou a une question centrale

## Format de sortie obligatoire pour l'API

Chaque run doit sortir au minimum:

1. `Decision`
2. `Why`
3. `Alternatives considered`
4. `Files to change`
5. `Interfaces / types`
6. `Patch outline`
7. `Tests`
8. `Risks`
9. `Acceptance criteria`
10. `Open questions`

Sans ce format, le run est considere comme moins fiable.

## Decision discipline

Le projet doit entretenir une discipline explicite de decision.

Marqueurs obligatoires:

- `DECISION CONFIRMED`
- `DECISION CHANGED`

Usage:

- `DECISION CONFIRMED` quand une direction est revalidee et reste active
- `DECISION CHANGED` quand une ancienne direction est remplacee

Regles:

- on ne laisse pas des changements d'architecture implicites
- on journalise regulierement les confirmations et changements importants
- une decision confirmee est presume valide jusqu'a changement explicite

## Memoire et decisions confirmees

Le systeme doit promouvoir regulierement en memoire durable:

- decisions confirmees
- decisions changees
- contraintes durcies
- policies confirmees
- lessons issues d'audits
- incidents et corrections structurelles

Le systeme ne doit pas attendre que l'humain pense a le demander.

Objectif:

- optimisation autonome
- reduction des oublis
- zero duplication inutile
- coherence sur le long terme

## Standing attendu

`Project OS` est construit avec un standard haut niveau:

- pas de spaghetti
- pas de doublons inutiles
- pas de verite implicite
- securite serieuse
- structure claire
- decisions explicites
- memoire locale protegee
- evolution continue sans casser le coeur

Reference mentale:

- on construit `Jarvis`
- pas un assemblage de scripts opportunistes

