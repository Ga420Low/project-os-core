# Project OS Fallback And Incident Recovery Contract

## Statut

ACTIVE - Pack 0 locked contract

## But

Definir comment `Project OS` degrade, explique la degradation et reprend sans perdre
la verite ni mentir a l'operateur.

## Regle racine

Un fallback n'est jamais:

- un mensonge
- une rustine silencieuse
- une nouvelle source de verite

Un incident doit devenir visible, traque et rejouable.

## Triple fallback canonique

Le systeme doit garder trois niveaux:

1. `PWA` normale
2. terminal fallback dans l'app
3. acces d'urgence hors app au `control plane`

## Incident objects obligatoires

Le contrat repose sur:

- `IncidentRecord`
- `DecisionRecord`
- `ApprovalRecord`
- `ActionEvidence`
- `RunEvent`
- `RuntimeState`

## Inputs obligatoires

Les incidents et fallbacks peuvent etre declenches par:

1. perte de `RunnerHeartbeat`
2. perte de `RuntimeState`
3. echec de dispatch
4. timeout
5. echec upload artefact
6. echec `Cloudflare` / `Tailscale` / auth
7. ordre humain explicite

## Outputs obligatoires

Le systeme doit produire:

1. etat degrade visible
2. `IncidentRecord`
3. guidance de reprise
4. preservation de l'historique
5. reprise borne quand elle est possible

## Matrice minimale de reprise

### Panne du local runner

Le systeme doit:

- marquer le local comme indisponible
- rerouter vers le distant si possible
- sinon exposer clairement la limite

### Panne du remote runner

Le systeme doit:

- garder l'UI et l'historique
- garder le terminal fallback
- proposer le local si disponible

### Panne du home relay

Le systeme doit:

- perdre seulement la reprise locale automatisee
- pas la maison mere

### Panne du control plane

Le systeme doit:

- basculer vers les voies d'urgence admin documentees
- ne pas pretendre que la maison mere est encore la

## Politique de reprise

Une reprise correcte doit:

1. lire l'historique
2. marquer le contexte degrade
3. relancer seulement ce qui est rejouable
4. ne pas doubler un effet critique deja parti

## Interdits

Le systeme ne doit pas:

- relancer aveuglement un run critique
- cacher un incident derriere un simple retry
- faire d'un fallback un comportement permanent non documente
- perdre les approvals ou decisions liees a un run

## Home relay dans la reprise

Le `home relay` peut:

- reveiller le PC
- relancer la VM
- relancer un service local

Il ne peut pas:

- remplacer le `control plane`
- remplacer le `remote runner`
- valider qu'une reprise metier est terminee

## Acceptance checks

Le contrat sera considere respecte quand:

1. un `remote runner` down produit un incident visible et un etat degrade clair
2. un `local runner` down n'emporte pas la maison mere
3. un `home relay` down ne coupe pas la `PWA`
4. le terminal fallback reste utilisable si le chat principal casse
5. une reprise laisse une preuve canonique et n'efface pas l'historique

## References

- `docs/architecture/PROJECT_OS_MOTHER_CONTROL_PLANE_ARCHITECTURE.md`
- `docs/architecture/PROJECT_OS_CANONICAL_DATA_MODEL_CONTRACT.md`
- `docs/roadmap/PROJECT_OS_AUTOPILOT_PACK_PLAN.md`
- `src/project_os_core/session_continuity.py`
- `src/project_os_core/security_boundaries.py`
- `src/project_os_core/gateway/execution_evidence.py`

