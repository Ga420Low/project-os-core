# Automation Modes and Chaining

Ce document definit les modes d'automatisation et le chainage de runs dans Project OS.

## Vue d'ensemble

Project OS execute du travail via des **runs API**. Chaque run est une unite atomique.
Les runs peuvent etre enchaines en **missions** pour des objectifs plus grands.

```text
Run (atomique) -> Mission (sequence de runs) -> Schedule (missions recurrentes)
```

## Les 4 modes de run

Definis dans `docs/integrations/API_LEAD_AGENT_V1.md`.

### Audit

- **Objectif**: analyser un perimetre de code ou d'architecture
- **Entree**: context pack + perimetre cible
- **Sortie**: rapport structure avec severites (P0, P1, P2)
- **Cout type**: ~0.40 EUR
- **Quand**: avant un refactoring, apres un merge, verification periodique

### Design

- **Objectif**: concevoir une architecture ou un lot de travail
- **Entree**: context pack + objectif + contraintes
- **Sortie**: design structure avec interfaces, dependances, alternatives, risques
- **Cout type**: ~0.60 EUR
- **Quand**: nouveau module, refactoring majeur, nouvelle integration

### Patch plan

- **Objectif**: planifier les modifications fichier par fichier
- **Entree**: context pack + design valide
- **Sortie**: plan de patch avec fichiers, ordre, tests, risques
- **Cout type**: ~0.50 EUR
- **Quand**: apres un design valide, avant le code

### Generate patch

- **Objectif**: produire le code
- **Entree**: context pack + patch plan valide
- **Sortie**: code structure, pret pour review
- **Cout type**: ~0.80 EUR
- **Quand**: apres un patch plan valide

## Chaine canonique

La sequence standard pour un lot de travail complet:

```text
1. audit -> comprendre l'etat actuel
2. design -> concevoir la solution
3. patch_plan -> planifier les modifications
4. generate_patch -> produire le code
5. tests / verifications -> prouver la sortie
6. review (Claude API) -> auditer cross-model
7. decision (fondateur) -> approuver ou rejeter
```

Chaque etape peut:

- **reussir** -> passer a la suivante
- **echouer** -> retry ou escalade
- **demander clarification** -> attendre la reponse du fondateur
- **etre rejetee** -> retour a l'etape precedente ou abandon

## Missions

### Definition

Une mission est une sequence de runs lies par un objectif commun.

```python
@dataclass
class Mission:
    mission_id: str
    objective: str              # "Refactorer le module memory"
    branch: str                 # "project-os/refactor-memory"
    steps: list[MissionStep]
    max_steps: int = 8          # guard: pas plus de 8 etapes
    status: str                 # "active", "completed", "paused", "failed"

@dataclass
class MissionStep:
    step_id: str
    mission_id: str
    run_mode: str               # "audit", "design", "patch_plan", "generate_patch"
    run_id: str | None          # lie au run API execute
    status: str                 # "pending", "executing", "completed", "failed"
    depends_on: str | None      # step_id precedent
```

### Workflow mission

1. `create_mission(objective, branch)` -> cree la mission et le premier step (audit ou design)
2. le premier run est execute automatiquement
3. a la completion, `advance_mission()` est appele
4. `advance_mission()` injecte le contexte du run precedent dans le context pack du suivant
5. la mission avance step par step jusqu'a completion ou echec
6. le fondateur n'est notifie qu'aux points utiles: contrat, clarification, blocage reel, terminal state ou synthese importante

### Guards

| Guard | Valeur | Raison |
|-------|--------|--------|
| Max steps par mission | 8 | Eviter les missions infinies |
| Max missions actives | 3 | Eviter la surcharge |
| Max cout par mission | 5 EUR | Budget safety |
| Timeout mission | 48h | Pas de mission zombie |

### Context injection entre steps

Chaque step recoit dans son context pack:

- le resultat du step precedent (resume, pas brut)
- les decisions prises pendant la mission
- les clarifications resolues
- les lecons apprises (LESSONS_LEARNED, max 800 tokens)

## Runs schedules

### Definition

Un run schedule est un run qui se declenche automatiquement a un moment defini.

```python
@dataclass
class ScheduledRun:
    schedule_id: str
    run_mode: str               # mode du run
    branch: str | None          # branche cible
    cron: str                   # expression cron ou "daily", "weekly"
    context_template: str       # template de context pack
    max_active_schedules: int = 5  # guard
    enabled: bool = True
```

### Cas d'usage

| Schedule | Mode | Frequence | Objectif |
|----------|------|-----------|----------|
| Health audit | `audit` | Quotidien | Verifier la sante du code |
| Security scan | `audit` | Hebdomadaire | Detecter les failles |
| Doc freshness | `audit` | Hebdomadaire | Verifier que les docs sont a jour |
| Budget review | `review` | Quotidien | Rapport de depenses |

### Integration avec le monitor

Le monitor loop verifie periodiquement:

```python
def check_scheduled_runs():
    schedules = db.get_active_schedules()
    for schedule in schedules:
        if schedule.is_due():
            if guardian.can_run(schedule):
                create_run_from_schedule(schedule)
```

### Guards

| Guard | Valeur | Raison |
|-------|--------|--------|
| Max schedules actifs | 5 | Eviter la surcharge |
| Budget journalier respecte | Oui | Les schedules ne depassent pas le budget |
| Pas de schedule pendant un blocage | Oui | Si un run est bloque, pas de nouveau schedule |

## Modes autonomes vs assistes

### Mode autonome

Le systeme agit seul tant que:

- le budget est dans les limites
- pas de boucle detectee
- pas de clarification requise
- le run est dans le perimetre du contrat approuve

### Mode assiste

Le systeme demande au fondateur quand:

- clarification requise (ambiguite, contradiction)
- nouveau contrat a approuver
- budget depasse
- boucle detectee
- decision strategique (pas technique)

### Escalade progressive

```text
1. Le systeme decide seul (pattern connu, budget ok)
2. Le systeme propose et agit apres timeout (fallback_if_no_answer)
3. Le systeme demande et attend (clarification_required)
4. Le systeme bloque et attend (securite, budget, boucle)
```

## Interactions avec le learning

Chaque run produit des signaux pour la couche learning:

| Signal | Origine | Destination |
|--------|---------|-------------|
| `DECISION CONFIRMED` | Review acceptee | Memoire durable |
| `DECISION CHANGED` | Review rejetee + correction | Pattern a eviter |
| `LOOP DETECTED` | 3+ echecs meme branche | Alerte + blocage |
| `REFRESH RECOMMENDED` | Contexte degrade | Rebuild context pack |
| `LESSONS LEARNED` | Completion report | Injection dans futurs runs |

## Etat d'implementation

| Composant | Status |
|-----------|--------|
| Runs unitaires (4 modes) | Operationnel |
| Review cross-model | Operationnel (_call_reviewer) |
| Traduction operateur | Operationnel (_call_translator) |
| Filtre `run_started` et bruit operateur | Operationnel |
| Missions (chaining) | A implementer (lot planifie) |
| Scheduled runs | A implementer (lot planifie) |
| Guardian pre-spend | A implementer (lot planifie) |
| Learning injection | A implementer (lot planifie) |

## References

- `docs/integrations/API_LEAD_AGENT_V1.md`
- `docs/decisions/0008-canonical-six-role-mission-graph.md`
- `docs/decisions/0013-dual-model-operating-model.md`
- `docs/roadmap/BUILD_STATUS_CHECKLIST.md`
- `docs/architecture/HYBRID_LARGE_CONTEXT_WORKFLOW.md`
