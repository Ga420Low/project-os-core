# TEMP - OpenClaw Upstream Feature Packs (2026-03-15)

Statut: note de travail temporaire, non canonique.

La feuille de route canonique issue de cette note est maintenant:

- `docs/roadmap/OPENCLAW_REINFORCEMENT_PLAN.md`

Objet: lister les idees les plus exploitables vues dans l'upstream OpenClaw et quelques forks utiles, puis les regrouper en packs d'integration pour `Project OS`.

## Sources retenues

- Upstream officiel `openclaw/openclaw`
- Fork `sunkencity999/localclaw`
- Fork `OpenBMB/EdgeClaw`
- Docs OpenClaw Discord / plugins / gateway / doctor / Windows

## Pack 1 - Model Health and Routing

Source principale: `localclaw`

Idees a reprendre:

- startup health check du stack modeles
- routage 3 tiers `fast / local / API`
- auto-escalation si le modele local timeoute
- proactive briefing depuis les sessions recentes

Interet pour `Project OS`:

- meilleure visibilite de sante avant run
- economie cout/latence sur les tours simples
- meilleure resilience quand le modele local ou lent patine
- meilleure continuity de contexte pour l'operateur

Statut recommande:

- `adapt`

Notes:

- ne pas copier le fork entier
- brancher ca sur notre futur `LLMProvider` / `ModelRouter`
- garder `Claude API` pour discussion Discord et `GPT API` pour code lourd

## Pack 2 - Privacy Guard and Sensitive Routing

Source principale: `EdgeClaw`

Idees a reprendre:

- protocole `GuardAgent` `S1 passthrough / S2 desensitize / S3 local`
- double memoire `full / clean`
- routage edge-cloud selon sensibilite

Interet pour `Project OS`:

- vrai garde-fou avant envoi cloud
- meilleure hygiene memoire pour les contenus sensibles
- bon candidat pour renforcer `Guardian`

Statut recommande:

- `adapt` fortement

Notes:

- ne pas absorber leur architecture complete
- garder notre runtime truth
- utiliser cette idee comme surcouche de classification et de promotion memoire

## Pack 3 - Discord Operations UX

Source principale: docs officielles OpenClaw Discord

Idees a reprendre:

- `autoPresence` pour refleter l'etat runtime dans la presence Discord
- `execApprovals` via boutons Discord
- `threadBindings` pour binder un thread a une session durable
- `components v2` / `modals` / `picker` pour des interactions plus riches

Interet pour `Project OS`:

- meilleur pilotage operateur
- approvals plus propres que du texte libre
- threads `run` / `audit` / `incident` plus stables

Statut recommande:

- `keep` pour `threadBindings` et `execApprovals`
- `adapt` pour `autoPresence`
- `defer` pour les `components v2` complexes tant que le flux simple n'est pas beton

## Pack 4 - Plugin and Pairing Hardening

Source principale: docs officielles OpenClaw + changelog

Idees a reprendre:

- hardening plugins:
  - installs registry-only
  - versions pinees
  - `--ignore-scripts`
  - allowlist explicite
- pairing bootstrap tokens courts

Interet pour `Project OS`:

- reduction de surface d'attaque plugin
- meilleur modele de confiance
- pas de credentials durables partages en chat

Statut recommande:

- `keep`

Notes:

- on est deja en bonne direction sur l'allowlist
- le principe des bootstrap tokens courts doit devenir une regle absolue

## Recommandation de lotissement

Ordre recommande:

1. Pack 4 `Plugin and Pairing Hardening`
2. Pack 3 `Discord Operations UX` (thread bindings + approvals)
3. Pack 1 `Model Health and Routing`
4. Pack 2 `Privacy Guard and Sensitive Routing`

Pourquoi:

- on ferme d'abord la confiance et l'auth
- on stabilise ensuite l'ergonomie operateur
- on optimise ensuite le routage et la sante modeles
- on termine par la couche de privacy classification, plus structurante

## Ce qu'on ne fait pas

- pas de fork OpenClaw complet
- pas de rebranding d'un fork existant
- pas de deuxieme architecture concurrente
- pas de migration opportuniste vers des canaux non utiles au projet

## Question ouverte pour la suite

Si OpenClaw reste natif Windows chez nous:

- brancher les packs directement dans `Project OS`

Si OpenClaw bascule un jour sous WSL2:

- decider si OpenClaw devient un gateway isole
- garder `Project OS` et la verite runtime sur l'hote Windows
