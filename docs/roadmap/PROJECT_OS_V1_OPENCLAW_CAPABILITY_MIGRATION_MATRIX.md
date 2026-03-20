# Project OS V1 OpenClaw Capability Migration Matrix

## Statut

ACTIVE - First migration matrix for the `OpenClaw + notre entreprise` rebuild

## But

Donner une premiere table de tri pour savoir:

- ce qu'on garde tel quel comme fondation
- ce qu'on reconstruit au-dessus
- ce qu'on rejette
- ce qui reste en attente

## Regle de lecture

- `KEEP` = garde comme fondation ou reference directe
- `REBUILD` = reconstituer proprement dans la nouvelle base
- `REJECT` = ne pas remonter tel quel
- `DEFER` = utile plus tard, pas dans le premier lot

## Matrice initiale

| Capacite | Source dominante | Decision | Cible | Pourquoi |
| --- | --- | --- | --- | --- |
| boucle autonome runtime | `OpenClaw` | `KEEP` | foundation runtime | fondation plus saine que le runtime historique |
| discipline de session | `OpenClaw` | `KEEP` | foundation runtime | meilleure hygiene que l'existant |
| compaction / continuite de contexte | `OpenClaw` | `KEEP + ADAPT` | foundation + enterprise memory | bonne base, mais la memoire canonique reste `Project OS` |
| controle runtime / queue discipline | `OpenClaw` | `KEEP` | foundation runtime | vrai gain agentique |
| execution code / shell / patch | `Codex CLI` | `KEEP` | executor bridge | meilleur moteur d'execution |
| control plane PWA | `Project OS` | `REBUILD` | `project-os-platform` | coeur produit proprietaire |
| preferences fondateur | `Project OS` | `REBUILD` | enterprise memory layer | memoire d'entreprise canonique |
| decision log | `Project OS` | `REBUILD` | enterprise memory layer | preuve et gouvernance |
| tasks / issues internes | `Project OS` | `REBUILD` | control plane | verite operateur |
| docs metadata / PDF explorer | `Project OS` | `REBUILD` | control plane | maison mere operateur |
| timeline / runs / approvals | `Project OS` | `REBUILD` | control plane | audit et supervision |
| preview -> branch -> PR flow | `Project OS` | `REBUILD` | execution bridge + UI | flow produit specifique |
| runtime local Windows historique | `project-os-core` legacy | `REJECT` | none | contredit la topologie V1 |
| surfaces historiques trop locales | `project-os-core` legacy | `REJECT` | none | trop de dette et de confusion |
| wrappers temporaires sales | `project-os-core` legacy | `REJECT` | none | ne doivent pas polluer la nouvelle base |
| home relay | `Project OS` doctrine | `REBUILD` | infra local complementaire | utile mais hors fondation OpenClaw |
| runner local Linux | `Project OS` doctrine | `REBUILD` | execution plane | puissance locale controlee |
| stockage canon docs / policies | `project-os-core` docs | `KEEP + REBUILD` | canon docs + enterprise platform | docs gardees, implementation reconstruite |
| memory SDK externes optionnels | `OpenMemory` / `Mem0` / `Zep` | `DEFER` | later packs | a reevaluer apres la memoire canonique V1 |

## Lecture immediate

Le centre de gravite V1 est:

1. `OpenClaw` garde le runtime
2. `Codex CLI` garde l'execution
3. `Project OS` reconstruit:
   - control plane
   - memoire d'entreprise
   - policies
   - audit
   - surfaces operateur

## Tris explicites

### A ne pas faire

- injecter massivement des couches historiques `Project OS` dans `OpenClaw`
- deployer `project-os-core` tel quel comme base finale
- recrire `Codex CLI`
- traiter la memoire OpenClaw comme memoire d'entreprise suffisante

### A faire

- reprendre les contrats canoniques `Project OS`
- reconstruire au-dessus de la fondation
- garder le repo actuel comme canon de migration
- valider chaque brique reconstruite contre cette matrice

## Prochains ajouts a cette matrice

1. `Discord/OpenClaw` live capabilities
2. `Mission Router` et equivalents a reconstruire ou non
3. `evidence pipeline`
4. `approval engine`
5. `research / deep research`
6. `voice / audio`
7. `search / retrieval / index`

## Reference

- `docs/roadmap/PROJECT_OS_V1_OPENCLAW_ENTERPRISE_REBUILD_ROADMAP.md`
