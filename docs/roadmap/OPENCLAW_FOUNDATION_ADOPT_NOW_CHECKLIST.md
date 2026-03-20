# OpenClaw Foundation Adopt Now Checklist

## Statut

ACTIVE

## But

Transformer les "pepite" retenues en actions concretement absorbables dans la fondation V1 sans:

- forker trop tot
- injecter la couche entreprise
- casser la lisibilite du substrate officiel

## Regle

On adopte:

- des patterns
- des guardrails
- des conventions de separation
- des simplifications de bootstrap

On n'adopte pas:

- une nouvelle base runtime
- une nouvelle verite memoire
- une nouvelle couche produit

## `digitalknk/openclaw-runbook` -> adopt now

### A internaliser maintenant

1. checklist de hardening ops
2. checklist de couts et quotas
3. limites explicites de memoire/contexte
4. patterns de run boring et stables
5. logique de survie et d'exploitation longue duree

### Traduction attendue chez nous

1. `Project OS` runbook serveur V1
2. garde-fous de consommation modele
3. modes de run explicites:
   - normal
   - budget
   - recovery
4. conventions de logs et health checks

### Interdit

1. copier le runbook tel quel comme doctrine produit
2. laisser un repo externe devenir la reference operatoire canonique

## `essamamdani/openclaw-coolify` -> adopt now partiellement

### A internaliser maintenant

1. bootstrap simple et lisible
2. exposition dashboard par URL privee/tunnel
3. logique de "service ready" simple a verifier
4. parcours onboarding clair apres deploiement

### Traduction attendue chez nous

1. stack `docker compose` lisible sur OVH
2. URL privee `Tailscale` ou tunnel prive pour surfaces admin
3. point d'entree unique pour l'onboarding substrate
4. checks de readiness faciles a relire

### Interdit

1. importer Coolify comme dependance de plateforme
2. refaire notre stack autour d'un outil de panel qu'on n'a pas choisi

## `sunkencity999/localclaw` -> adopt now partiellement

### A internaliser maintenant

1. separation d'etat
2. separation de config
3. separation de profils
4. separation de ports
5. coexistence propre entre installations / lanes

### Traduction attendue chez nous

1. distinction claire entre:
   - upstream `openclaw`
   - canon `project-os-core`
   - futures lanes runtime
2. racines d'etat distinctes par role
3. configs distinctes par surface
4. ports distincts quand une lane additionnelle apparait

### Interdit

1. reorienter la V1 entiere vers local-model-first
2. faire du fork `localclaw` notre nouvelle base

## Actions immediates

1. documenter les chemins d'etat de l'upstream clone OVH
2. documenter les ports utilises et reserves
3. ecrire le mini runbook serveur `OpenClaw V1`
4. poser une checklist readiness substrate
5. conserver tous ces apports dans nos docs, pas dans le coeur upstream

Livrable cree:

- `docs/roadmap/OPENCLAW_V1_SERVER_RUNBOOK.md`

## Definition of done

Cette phase est terminee si:

1. les patterns critiques des pepites sont internalises
2. la base runtime reste `openclaw/openclaw`
3. aucune dependance structurelle non voulue n'a ete ajoutee
4. la couche entreprise peut commencer au-dessus d'une fondation plus propre
