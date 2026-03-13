# Run Communication Policy

Ce document fixe comment `Project OS` parle pendant les runs.

Le principe central est simple:

- le texte naturel doit creer de la valeur
- sinon il doit disparaitre

## Objectif

Eviter:

- le bavardage couteux
- la narration inutile
- les messages qui consomment des tokens sans aider

Garantir:

- visibilite
- comprehensibilite
- cout controle
- blocages clairs

## Modes de parole

### 1. Silent Until Terminal State

Mode par defaut des gros runs de code.

Autorise:

- phase courante
- cout estime
- budget restant
- branche
- statut tests
- fichiers touches
- blocage machine-lisible

Interdit:

- narration intermediaire
- messages naturels a chaque etape
- commentaires sur l'effort en cours

### 2. Phase Markers Only

Mode intermediaire pour des runs visibles mais encore peu bavards.

Autorise:

- `demarrage`
- `generation`
- `tests`
- `review`
- `termine`
- `bloque`

Messages tres courts uniquement.

### 3. Dialogue Rich

Reserve:

- a la discussion Discord
- aux clarifications operateur
- aux arbitrages
- aux incidents qui exigent un vrai echange

## Regles par contexte

### Gros run de code

Ordre obligatoire:

1. contrat de run
2. validation humaine
3. silence operationnel
4. rapport final

### Blocage reel

Format:

- cause
- impact
- choix attendus
- recommandation

Style:

- court
- non technique si inutile
- sans roman

### Rapport final

Format impose:

- `Verdict`
- `Ce qui a ete produit`
- `Tests`
- `Risques`
- `Decisions confirmees ou changees`
- `Prochaine action recommandee`

## UI au lieu du bavardage

Le dashboard et les cartes Discord remplacent la narration.

Regle dure supplementaire:

- un gros run API ne doit pas partir sans control room locale sur le PC
- le dashboard local doit etre lance automatiquement avant l'execution
- l'interface doit s'ouvrir localement pour que l'operateur puisse verifier visuellement que le run vit vraiment
- l'ouverture doit etre prouvee par un signal live du navigateur vers le dashboard, pas seulement par le lancement silencieux d'un serveur
- si le dashboard ne peut pas etre lance, le run doit echouer ferme

Ils doivent montrer:

- est-ce qu'il travaille
- sur quoi
- quelle phase
- combien ca coute
- si c'est bloque
- si c'est termine

## Signals a apprendre

Si un run parle trop:

- emettre un `NoiseSignal`

Si un run n'explique pas assez un blocage reel:

- emettre un signal de capacite ou de qualite

La communication est donc aussi un objet d'apprentissage.

## Regle anti-memoire-de-conversation

Une implementation n'est jamais consideree valide parce qu'elle "marchait pendant la conversation".

Elle doit etre prouvee par le code lui-meme via au moins un de ces mecanismes:

- test automatise
- doctor dedie
- replay harness
- health snapshot
- evidence persistante
- beacon live pour les interfaces visibles
