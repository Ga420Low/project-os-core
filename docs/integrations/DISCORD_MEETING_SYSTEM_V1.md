# Discord Meeting System V1

`Discord` reste la surface fondateur.
Le systeme de reunion ajoute une deliberation structuree avant les decisions importantes de code, d'autonomie ou de cap.

Il ne cree pas:

- un second runtime
- une seconde memoire
- un salon multi-agent libre

## But

Fournir un workflow de `board` visible mais discipline dans `Discord`:

- lisible pour le fondateur
- compact
- oriente decision
- aligne avec la verite runtime

## Posture V1

- un seul bot
- plusieurs identites logiques
- threads d'abord, pas une multiplication de salons fixes
- thread visible toujours pour chaque reunion
- templates stricts
- synthese finale obligatoire
- transcript machine interne toujours conserve dans le runtime

## Modele de salons

Salons permanents:

- `#pilotage` -> discussion fondatrice, ouverture de reunion, recap compact
- `#runs-live` -> cartes de run, signaux de progression, lien vers un thread si necessaire
- `#approvals` -> validations sensibles et decisions a risque
- `#incidents` -> incidents reels, reprises et pre-mortems operationnels

Surface de reunion:

- threads ouverts depuis `#pilotage`
- threads ouverts depuis `#incidents` seulement pour un incident actif

## Identites logiques autorisees

- `[Moderator]`
- `[Vision]`
- `[Product]`
- `[Tech]`
- `[Execution]`
- `[Ops]`
- `[Security]`
- `[RedTeam]`
- `[Clarity]`
- `[Research]`

Identites reservees:

- `[Finance]`
- `[Legal]`
- `[Brand]`

## Declenchement d'une reunion

Triggers naturels:

- "ouvre une reunion architecture"
- "fais une review multi-angles"
- "conseil strategique sur ca"
- "pre-mortem avant de coder"
- "debatez avant implementation"

Triggers structures:

- `/meeting implementation-review`
- `/meeting architecture-review`
- `/meeting strategy-council`
- `/meeting premortem`
- `/meeting custom`

## Types de reunion

- `implementation_review`
- `architecture_review`
- `strategy_council`
- `pre_mortem`
- `trust_review`

Voir:

- `docs/analysis-angles/07-meeting-types.md`

## Cycle de vie de reunion

1. demande recue dans `#pilotage`
2. `Moderator` ouvre un thread
3. brief canonique poste
4. une reponse initiale par angle
5. round de contradictions ciblees
6. synthese finale
7. decision fondateur
8. synthese humaine finale republiquee dans `#pilotage`
9. si sensible, miroir dans `#approvals`

## Profils de sortie Discord

- `notification_card`: cartes courtes de `#runs-live` et notifications operateur courantes, 3 lignes max
- `meeting_thread`: thread visible de deliberation multi-angles, format structure, pas de limite fixe en lignes
- `founder_synthesis`: recap final dans `#pilotage`, concis mais non borne a 3 lignes si le sujet demande plus de contexte

La regle `3 lignes max` ne s'applique qu'aux `notification_card`.

## Format des messages

Message initial d'angle:

```text
[Tech]
Verdict: favorable_under_conditions
Priority: high
Main reading: la structure actuelle fonctionne mais reste trop couplee
Main risk: la reprise et le debug vont se degrader avec la croissance
Main opportunity: isoler plus tot persistance et execution
Assumptions:
- la reprise apres interruption compte vite
Recommendation: separer les frontieres avant d'elargir l'autonomie
Confidence: medium
Reply requested from: Execution, Ops
```

Reponse de contradiction:

```text
[Execution -> Tech]
Objection: une separation complete maintenant peut ralentir excessivement le premier vrai palier utile
Concession: le couplage actuel fera mal plus tard
Unresolved point: savoir si la reprise est necessaire en v1 ou peut attendre v1.5
Proposed test: construire d'abord un pilote contraint avec journal explicite
```

Synthese finale:

```text
[Moderator]
Agreements:
- la journalisation compte
- la reprise doit etre explicite
Disagreements:
- Tech veut une separation plus tot
- Execution veut un premier scope plus etroit
Blocking issues:
- aucun modele clair de reprise
Recommendation: approve_with_conditions
Next step: generate implementation plan
Decision state: approved_with_conditions
```

## Regles dures

- 1 message initial par angle
- 1 reponse de contradiction max par angle
- 2 a 4 paires de contradiction max
- pas de discussion libre apres synthese sauf demande du fondateur
- pas de dump runtime brut dans le thread
- pas de gros bloc de code sauf demande explicite du fondateur

## Machine d'etats de reunion

- `draft`
- `opened`
- `brief_ready`
- `initial_round`
- `contradiction_round`
- `synthesis_ready`
- `awaiting_founder`
- `approved`
- `approved_with_conditions`
- `needs_narrower_scope`
- `needs_more_evidence`
- `blocked`
- `converted_to_implementation_plan`
- `archived`

## Decisions fondateur

Actions fondateur autorisees:

- `approve`
- `approve_with_conditions`
- `narrow_scope`
- `ask_another_round`
- `generate_plan`
- `start_coding`
- `block`

## Contrat runtime

`Discord` n'est pas la verite canonique.

Le runtime doit garder:

- `MeetingIntent`
- `MeetingBrief`
- `AngleResponse`
- `ContradictionReply`
- `MeetingSynthesis`
- `DecisionRecord`
- transcript machine complet du thread

`Discord` montre:

- le thread visible pour la reunion
- la synthese humaine finale dans `#pilotage`
- un miroir dans `#approvals` seulement si la decision est sensible

## Politique memoire

Promouvoir vers la memoire:

- synthese finale si elle est durable
- decision record
- contraintes stables

Ne pas promouvoir par defaut:

- transcript complet du thread
- chaque detail de contradiction
- bruit exploratoire

## Frontieres de securite

Le systeme de reunion ne peut pas:

- approuver seul des actions dangereuses
- elever les permissions
- contourner le `Mission Router`
- remplacer le `Guardian`
- creer une nouvelle source de verite hors runtime

## Criteres de succes V1

- le fondateur peut declencher une reunion naturellement
- le thread reste lisible
- la synthese est exploitable pour decider
- le runtime garde la trace
- `Discord` ne devient pas un theatre bruyant
