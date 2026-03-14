# Output Schema

## But

Normaliser les sorties des angles et des reunions pour:

- comparaison
- synthese
- audit
- promotion memoire
- affichage Discord

## AngleResponse

Format logique:

```yaml
angle: Technical Architecture
verdict: favorable_under_conditions
priority: high
main_reading: >
  La separation actuelle est viable mais couple encore trop fortement
  orchestration, persistance et execution pour une croissance axee reprise.
main_risk: >
  La reprise et le debug vont se degrader si l'etat et l'execution restent fusionnes.
main_opportunity: >
  Une separation de frontieres maintenant peut proteger la reprise et l'observabilite plus tard.
assumptions:
  - La reprise apres interruption est requise dans les 2 prochains lots.
  - La croissance memoire augmentera la pression de couplage.
open_questions:
  - Faut-il une reprise complete en v1 ou en v1.5 ?
recommendation: split boundaries before broader autonomy
confidence: medium
reply_requested_from:
  - Execution Delivery
  - Operations Workflow
suggested_measurements:
  - time_to_resume_after_failure
  - hidden_cross_module_dependencies
evidence_tags:
  - fact
  - inference
```

## Verdicts autorises

- `favorable`
- `favorable_under_conditions`
- `neutral`
- `reserved`
- `unfavorable`
- `blocking`
- `premature`
- `insufficiently_defined`
- `not_applicable`

## Recommandations autorisees

- `execute`
- `test`
- `narrow_scope`
- `split`
- `reformulate`
- `delay`
- `secure`
- `document`
- `reject`
- `escalate`
- `ask_human_arbitration`
- `generate_plan`

## ContradictionReply

```yaml
from_angle: Execution Delivery
to_angle: Technical Architecture
objection: >
  Une separation complete maintenant peut ralentir excessivement le premier palier vraiment utile.
concession: >
  Le couplage actuel deviendra douloureux plus tard.
unresolved_point: >
  Savoir si reprise et resume sont necessaires en v1 ou peuvent attendre un lot.
proposed_test: >
  Construire un pilote contraint avec journal explicite et hooks de reprise seulement.
```

## MeetingSynthesis

```yaml
meeting_type: architecture_review
topic: persistent memory architecture
agreements:
  - la memoire persistante est au coeur du sujet
  - la reprise compte tot
disagreements:
  - l'architecture veut une separation plus tot
  - l'execution prefere un pilote contraint
blocking_issues:
  - aucun modele d'etat de reprise explicite
recommendation: proceed_with_constrained_pilot
next_step: generate_implementation_plan
decision_state: approved_with_conditions
conditions:
  - journalisation d'abord
  - frontiere memoire explicite
  - aucun writeback autonome sans borne
metrics_to_watch:
  - resume_success_rate
  - incident_recovery_time
```

## DecisionRecord

```yaml
record_id: decision_record_x
topic: persistent memory architecture
meeting_type: architecture_review
date: 2026-03-14T22:00:00Z
angles_activated:
  - Technical Architecture
  - Operations Workflow
  - Security Governance
  - Execution Delivery
  - Red Team
  - Clarity Anti-Bullshit
decision: approved_with_conditions
conditions:
  - journalisation d'abord
  - modele de reprise avant extension d'autonomie
next_actions:
  - generer un plan de pilote contraint
promote_to_memory: true
```

## Echelle de confiance

- `low`
- `medium`
- `high`

La confiance doit refleter:

- la completude des donnees
- la stabilite du contexte
- l'ambiguite du sujet

## Regles de tags de preuve

Chaque point important doit pouvoir etre tague comme:

- `fact`
- `inference`
- `hypothesis`
- `preference`
- `constraint`
- `risk`
- `bet`

## Profil d'affichage Discord

Les cartes Discord doivent compresser la meme semantique en:

- verdict
- main risk
- main recommendation
- next step

Aucun champ ne doit forcer la lecture de JSON brut pour comprendre la decision.
