# Run Communication Policy

Ce document fixe comment `Project OS` parle pendant les runs.

Il doit rester coherent avec:

- `docs/roadmap/DISCORD_FOUNDER_SURFACE_REPAIR_V2_PLAN.md`
- `docs/roadmap/PROJECT_OS_DESKTOP_CONTROL_ROOM_V1_PLAN.md`

Le principe central est simple:

- le texte naturel doit creer de la valeur
- sinon il doit disparaitre

Regle produit complementaire:

- les artefacts runtime sont des preuves
- ils ne sont pas une interface humaine suffisante
- un humain ne doit pas avoir besoin d'ouvrir un JSON pour comprendre la vie d'un run
- si un message affiche un `cout estime`, il doit venir du calculateur canonique partage (`src/project_os_core/costing.py`)

Regle de surface supplementaire:

- les evenements systeme vont d'abord au `control plane`
- `Discord` ne recoit qu'une version courte, utile et actionnable
- les details d'execution restent inspectables dans `Project OS.exe`

Regle de handoff supplementaire:

- si `Discord` recoit une vraie demande de statut, il peut repondre
- mais il doit le faire en mode `synthese`
- si le detail runtime est demande ou utile, la reponse doit pointer explicitement vers `Project OS.exe`
- les vues cibles par defaut sont:
  - `Home`
  - `Session`
  - `Runs`
  - `Discord`
  - `Costs`

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

## Profils Discord

### `notification_card`

Usage:

- `contract_proposed`
- `clarification_required`
- `run_completed`
- `run_failed`
- `budget_alert`
- cartes `#runs-live`

Regles:

- 3 lignes max
- pas de code
- pas de chemin de fichier
- valeur operateur immediate

### `meeting_thread`

Usage:

- deliberation multi-angles visible
- contradictions ciblees
- synthese structuree avant decision

Regles:

- pas de limite fixe en lignes
- format structure obligatoire
- le runtime garde toujours le transcript machine complet

### `founder_synthesis`

Usage:

- synthese humaine finale republiquee dans `#pilotage`
- recap d'un arbitrage important apres thread ou review dense

Regles:

- concise
- pas bornee a 3 lignes si la clarte demande plus
- oriente decision et prochaine action

## Regles par contexte

### Gros run de code

Ordre obligatoire:

1. contrat de run
2. validation humaine
3. silence operationnel
4. visibilite humaine pendant le run via une vraie surface
5. rapport final

Visibilite humaine minimale obligatoire:

- preuve visible de vie dans la surface de supervision retenue
- message de blocage ou `clarification_required` avec question claire
- message final avec verdict et prochaine action

Regle supplementaire:

- `run_started` reste filtre comme bruit operateur
- la preuve de vie passe par le dashboard local, le terminal live, ou une `notification_card` deja ouverte dans `#runs-live`

Si `Discord` est configure:

- c'est une surface de conversation prioritaire et parallele
- un gros run ne doit pas exister uniquement dans le dashboard ou dans les fichiers runtime

Si l'app locale `Project OS.exe` existe:

- elle devient la control room locale de reference
- `Discord` reste la voie distante et conversationnelle
- les deux surfaces doivent rester coherentes sur les etats visibles, sans imposer une sync complete du chat en v1
- les signaux systeme detailles doivent vivre d'abord dans l'app

Si `Discord` n'est pas encore configure:

- dashboard local + terminal live sont acceptables comme fallback technique
- mais le workflow reste considere incomplet cote experience operateur

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

### Clarification requise

Si le run detecte un brief incoherent ou dangereux:

- il peut contredire le brief
- il doit s'arreter en `clarification_required`
- il doit poser une seule question bloquante si possible
- il doit demander un amendement du contrat puis un nouveau `go`

Ce cas n'est pas un crash.
Ce n'est pas non plus une autorisation a improvise.

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

Avec `Project OS Desktop Control Room v1`, cette regle devient:

- l'app locale, le dashboard et les cartes Discord remplacent la narration
- la preuve visible locale doit converger a terme dans `Project OS.exe`

Regle dure supplementaire:

- les fichiers sous `runtime/api_runs/` ne comptent pas comme communication humaine
- ils servent de preuves, pas de canal operateur
- une clarification ou un verdict final doit etre remonte dans une surface que l'humain lit vraiment

Regle dure supplementaire:

- un gros run API ne doit pas partir sans control room locale sur le PC
- le dashboard local doit etre lance automatiquement avant l'execution
- l'interface doit s'ouvrir localement pour que l'operateur puisse verifier visuellement que le run vit vraiment
- l'ouverture doit etre prouvee par un signal live du navigateur vers le dashboard, pas seulement par le lancement silencieux d'un serveur
- si le navigateur local refuse le beacon mais que le contrat a ete approuve localement par le fondateur il y a peu, le run peut continuer en `founder_approval_fallback`
- ce fallback doit rester borne dans le temps, journalise, et ne remplace pas la tentative d'ouverture locale du dashboard
- sans beacon live recent ni approbation fondatrice fraiche, le run doit echouer ferme

Ils doivent montrer:

- est-ce qu'il travaille
- sur quoi
- quelle phase
- combien ca coute
- si c'est bloque
- si c'est termine

## Matrice de communication

- `queue / backlog / runs / health / approvals techniques / traces / routing / provider details` -> `Project OS.exe`
- `conversation / clarification / decision courte / relance / rapport humain bref` -> `Discord`
- `artefacts / journaux / snapshots / evidence complete` -> `runtime local`

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
