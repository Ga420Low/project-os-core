# Debate Protocol

## But

Organiser une deliberation multi-angles courte, utile et audit-able.

## Entrees

Toute session part d'un `MeetingBrief` canonique:

- `meeting_type`
- `topic`
- `objective`
- `context`
- `constraints`
- `risk_level`
- `time_horizon`
- `requested_output`
- `activated_angles`
- `reply_rules`

## Flux canonique

### Etape 0 - Demande

Le fondateur ou un composant interne demande:

- une review avant codage
- un conseil strategique
- un pre-mortem
- une review architecture
- une review trust/external behavior

### Etape 1 - Typage de reunion

Le `Moderator` ou le `Planner` choisit:

- le type de reunion
- les angles a activer
- le niveau de profondeur

### Etape 2 - Brief canonique

Tous les angles recoivent le meme brief.

Regle dure:

- pas de brief prive par angle
- pas de brief contradictoire

### Etape 3 - Passe independante

Chaque angle poste une seule reponse initiale.

Format:

- `Verdict`
- `Priority`
- `Main reading`
- `Main risk`
- `Main opportunity`
- `Assumptions`
- `Recommendation`
- `Confidence`
- `Reply requested from`

### Etape 4 - Contradictions ciblees

Le `Moderator` choisit 2 a 4 contradictions maximum.

Chaque reponse croisee suit ce format:

- `Objection`
- `Concession`
- `Unresolved point`
- `Proposed test`

### Etape 5 - Synthese arbitree

Le `Moderator` publie:

- `Agreements`
- `Disagreements`
- `Blocking issues`
- `Recommendation`
- `Next step`
- `Decision state`

### Etape 6 - Decision fondateur

Le fondateur choisit:

- `approve`
- `approve_with_conditions`
- `narrow_scope`
- `ask_another_round`
- `generate_plan`
- `start_coding`
- `block`

### Etape 7 - Promotion

Le `Memory Curator` promeut:

- la synthese finale
- le `DecisionRecord`
- les conditions durables

Le transcript brut reste dans le runtime.

## Regles de reponse

Regles dures:

- 1 message initial par angle
- 1 contradiction max par angle
- pas de conversation libre
- pas de second tour sans demande explicite
- pas de roman Discord

## Conditions d'arret

Une session doit s'arreter si:

- elle atteint un etat final
- il manque de la preuve dure
- le sujet sort du perimetre
- les contradictions n'ajoutent plus rien
- le `Guardian` ou un veto dur bloque

## Etats finaux

- `approved`
- `approved_with_conditions`
- `needs_narrower_scope`
- `needs_more_evidence`
- `blocked`
- `converted_to_implementation_plan`
- `archived`

## Attentes runtime

Le protocole doit etre representable plus tard par:

- `MeetingIntent`
- `MeetingBrief`
- `AngleResponse`
- `ContradictionReply`
- `MeetingSynthesis`
- `DecisionRecord`

## Attentes Discord

Discord ne voit jamais tout le detail machine par defaut.

Il voit:

- l'ouverture de reunion
- les reponses structurees
- la synthese finale
- la decision

Le runtime garde l'historique complet.
