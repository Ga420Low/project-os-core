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

## Meme agent, plusieurs surfaces

Le workflow hybride doit garder une identite agent unique.

Cela veut dire:

- meme charte mentale
- meme memoire canonique
- memes decisions de reference
- adaptation par canal seulement sur le format et le cout cognitif

References:

- `docs/architecture/AGENT_IDENTITY_AND_CHANNEL_MODEL.md`
- `docs/architecture/HANDOFF_MEMORY_POLICY.md`
- `docs/integrations/DISCORD_OPERATING_MODEL.md`
- `docs/architecture/RUN_COMMUNICATION_POLICY.md`
- `docs/architecture/FRENCH_OPERATOR_OUTPUT_POLICY.md`
- `docs/integrations/API_RUN_CONTRACT.md`

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

### Phase D - Contrat de run

Avant un run reel:

- produire un contrat de run lisible
- le rendre en francais simple
- attendre `go`, `go avec correction` ou `stop`

Sans contrat approuve:

- pas de run reel

### Phase E - Run API

L'API travaille sur:

- `audit`
- `design`
- `patch-plan`
- `generate-patch`

Le run API doit produire une sortie structuree.

Pendant les gros runs de code:

- silence operationnel
- pas de narration intermediaire
- la visibilite passe par le dashboard, le terminal et les cartes compactes

### Phase F - Inspection

On revient dans `Codex`.

`Codex` doit:

- verifier la coherence
- verifier le repo reel
- verifier les interfaces
- verifier les risques
- verifier les tests a lancer
- corriger les erreurs de raisonnement
- detecter les signes de boucle, d'appauvrissement ou de baisse de capacite
- forcer un `refresh` de contexte si la sortie perd en qualite ou recycle les memes idees

### Phase G - Integration

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

## Regle de communication

Les gros runs de code ne doivent pas parler pour exister.

Le texte naturel est reserve:

- au contrat de run
- au blocage reel
- au rapport final

Tout le reste doit passer par des signaux compacts et visibles.

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

## Detection de derive et prise de recul

Le workflow doit explicitement traiter les cas suivants:

- l'agent tourne en rond
- l'agent repete des solutions deja invalidees
- l'agent oublie des decisions deja confirmees
- la qualite du raisonnement baisse
- la capacite apparente diminue a cause d'un contexte mal rafraichi

Quand ces signaux apparaissent, le systeme doit:

- remonter l'alerte
- relire la memoire canonique utile
- recharger les decisions confirmees et changees
- aller chercher plus loin dans les sources et dans le contexte
- produire une proposition de correction ou de recentrage

Objectif:

- garder un niveau haut
- eviter les faux mouvements
- maintenir une trajectoire intelligente et autonome

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

## Routing adaptatif

Le workflow futurproof doit aussi router intelligemment le niveau de raisonnement.

Policy cible:

- banal / Discord simple -> `gpt-5.4` avec `reasoning.effort=medium` si le deterministic first ne suffit pas
- standard -> `gpt-5.4 high`
- critique / ambigu -> `gpt-5.4 xhigh`
- exceptionnel -> `gpt-5.4-pro` avec approval

Le but est de garder:

- qualite
- continuité d'identite
- maitrise du budget
