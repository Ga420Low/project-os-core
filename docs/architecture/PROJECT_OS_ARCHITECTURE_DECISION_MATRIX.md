# Project OS Architecture Decision Matrix

## Statut

ACTIVE - Canonical selection matrix before heavy implementation

## But

Choisir la meilleure option sur chaque branche d'architecture au lieu de laisser
coexister plusieurs caps partiellement vrais.

Ce document tranche:

- ce qui est retenu
- ce qui est reporte
- ce qui est refuse
- pourquoi

## Mantra unique

- centraliser la verite
- isoler le risque
- rendre chaque action rejouable
- garder Windows ennuyeux et stable
- ne jamais confondre prototype qui marche et systeme tenable

## Base de lecture

Cette matrice consolide les choix deja presents dans:

- `PROJECT_OS_MASTER_MACHINE.md`
- `docs/architecture/PROJECT_OS_MOTHER_CONTROL_PLANE_ARCHITECTURE.md`
- `docs/architecture/HOST_WINDOWS_VM_LINUX_MATRIX.md`
- `docs/architecture/MEMORY_STORAGE_AND_OPS_BLUEPRINT.md`
- `docs/architecture/HYBRID_LARGE_CONTEXT_WORKFLOW.md`
- `docs/systems/OPENCLAW_UPSTREAM_DOSSIER.md`
- `docs/roadmap/OPENCLAW_REINFORCEMENT_PLAN.md`
- `docs/roadmap/PROJECT_OS_PWA_VM_V0_1_PLAN.md`
- `docs/roadmap/PROJECT_OS_V1_BUDGET_OVH_PLAN.md`

## Selection par branche

| Branche | Options considerees | Choix retenu | Pourquoi | Reporte / refuse |
| --- | --- | --- | --- | --- |
| Maison mere | `tout local sur le PC` / `homelab maison` / `petit noeud Linux distant always-on` | `petit noeud Linux distant always-on` | seule option qui laisse la web app vivante quand le PC est eteint ou casse | `tout local` refuse comme maison mere ; `homelab` reporte comme lab ou secours |
| Surface operateur primaire | `Discord` / `desktop app` / `PWA privee` | `PWA privee` | seule surface credible pour PC + iPad + iPhone avec docs, timeline, PDF, approvals et chat | `Discord` historique/secondaire ; `desktop app` support local, pas surface mere |
| Control plane substrate | `Windows host` / `Kubernetes` / `Ubuntu LTS + Docker Compose` | `Ubuntu LTS + Docker Compose` | assez simple pour un solo, assez propre pour evoluer, pas de dependance a une session Windows | `Windows host` refuse ; `Kubernetes` reporte |
| Exposure publique | `ports entrants directs` / `Cloudflare Tunnel` | `Cloudflare Tunnel` | acces web sans exposer directement l'origine | `ports entrants directs` refuses |
| Admin privee | `SSH public` / `Tailscale` | `Tailscale` | admin privee, simple, operable depuis PC/iPad/iPhone | `SSH public` refuse comme voie normale |
| Execution autonome principale | `OS Windows direct` / `VM Linux locale` / `runner distant unique` | `binome runner distant minimal + VM Linux locale` | le distant garde le systeme utile PC eteint, le local apporte la puissance quand le PC est allume | `OS Windows direct` refuse ; `runner distant unique` seul n'exploite pas assez le PC |
| Runner distant always-on | `aucun` / `runner distant minimal always-on` / `tout sur le distant` | `runner distant minimal always-on` | garde chat, shell, Git workspaces et jobs standards quand le PC tombe | `aucun` refuse ; `tout sur le distant` refuse car sous-utilise le PC |
| Home relay / wake-recovery | `aucun` / `wake-on-lan ad hoc` / `home relay always-on` | `home relay always-on` | permet wake, restart, relance VM/services et etat local sans faire du PC la maison mere | `wake-on-lan ad hoc` trop fragile ; `aucun` prive de reprise locale elegante |
| Role d'OpenClaw | `facade primaire` / `substrate upstream adapte` / `fork massif` | `substrate upstream adapte` | garde les primitives runtime utiles sans salir le coeur | `fork massif` refuse ; facade primaire non retenue pour la V0.1 |
| Role de Codex CLI | `chat annexe` / `executor officiel` | `executor officiel` | c'est le bon moteur pour code, shell, patch et repo work | `chat annexe` refuse |
| Role de Project OS | `runtime complet unique` / `couche produit au-dessus` | `couche produit au-dessus` | concentre la vraie valeur: maison mere, docs, audit, memory, approvals, UI | reimplementer tout OpenClaw/Codex dans Project OS refuse |
| Verite du code | `clone Windows` / `workspace runner` / `GitHub prive` | `GitHub prive` | seule source saine pour branches, PR, reviews et historique | clones locaux et workspaces ne sont que des copies de travail |
| Verite operateur | `runtime local` / `Project OS DB centrale` | `Project OS DB centrale` | tasks, docs, PDF, timeline, preferences, decisions et runs doivent vivre dans la maison mere | `runtime local comme seule verite projet` refuse |
| Verite fichiers lourds | `disque PC` / `object storage central` | `object storage central` a terme | consultable depuis le web, compatible mobile, propre pour PDF/artefacts | `disque PC seul` refuse |
| Memoire froide | `8 To local` / `cloud archive` | `8 To local comme miroir/archive/cold memory` | utile, economique, exploite ton hardware sans devenir source unique | `8 To comme source unique` refuse |
| Recherche et retrieval | `prompt geant` / `DB + index + metadata` | `DB + index + metadata` | retrieval verifiable, rejouable, multi-device | `prompt geant` refuse |
| Store V1 | `SQLite locale unique` / `Postgres + Redis + local volume structure` / `Postgres + Redis + object storage` | `Postgres + Redis + local volume structure` | meilleur compromis V1 budget tout en gardant des frontieres propres | `SQLite unique` reporte a certains caches locaux seulement |
| Mounts du `8 To` | `RW global` / `zones contractuelles RO/RW` | `zones contractuelles RO/RW` | permet de nourrir les agents sans transformer le disque en bombe | `RW global` refuse |
| Fallback si l'app casse | `aucun` / `terminal dans l'app` / `triple fallback` | `triple fallback` | 1) UI normale, 2) terminal fallback dans l'app, 3) acces d'urgence hors app | les autres options sont insuffisantes |
| Pouvoir mobile | `full admin iPhone` / `lecture seule` / `mobile prudent` | `mobile prudent` | iPhone utile sans devenir dangereux ; iPad credible pour plus large | `full admin iPhone` refuse ; `lecture seule` trop limitee |
| Validation finale | `agent peut merger` / `humain dernier mot` | `humain dernier mot` | garde-fou non negociable sur architecture, policies, data, self-improvement | auto-merge critique refuse |
| Auto-learning | `logs append-only flous` / `learning decompose` | `memory + policy + execution + self-improvement` | seul modele exploitable et auditable | `autolearning` flou refuse |
| Self-improvement | `auto-rewrite direct` / `PR + tests + review + confirmation` | `PR + tests + review + confirmation` | permet le progres sans bombe auto-evolutive | `auto-rewrite prod` refuse |
| Fine-tuning | `des le debut` / `apres grounding + memory + evals` | `apres grounding + memory + evals` | evite de masquer un mauvais contexte par un mauvais remede | fine-tuning precoce refuse |
| Workflow Git agentique | `agent ecrit dans clone humain` / `workspace runner -> branche/PR` | `workspace runner -> branche/PR` | propre, auditable, compatible humain + agent | ecriture directe sur clone humain refusee |

## Contrats fermes avant implementation lourde

Avant de coder profondement, ces contrats doivent etre traites comme verrouilles:

1. `control plane contract`
2. `runner security contract`
3. `canonical data model`
4. `git workflow agentique`
5. `fallback + incident recovery contract`
6. `home relay / wake-recovery contract`

## Override d'implementation V1

Les choix ci-dessus restent canoniques comme topologie cible.

Mais l'implementation `V1` retenue est:

- `un noeud distant OVH unique`
- `control plane + runner distant minimal` sur cette meme machine
- `home relay`
- `runner local Linux`

Condition non negociable:

- meme sur un seul noeud, les services restent separes logiquement et extractibles

## V2 explicitement reportee

La `V2` robuste reportee contient:

1. split `projectos-control-01`
2. split `projectos-runner-01`
3. `object storage` externe pour les artefacts vivants
4. backups/restores plus durs

## Ordre officiel de construction

1. verrouiller les contrats
2. monter le noeud distant unique V1
3. ajouter le home relay / wake-recovery
4. brancher le runner local Linux de facon sure
5. faire de la web app la vraie maison mere
6. ajouter preferences et decision registry
7. ajouter learning et self-improvement sous garde-fous
8. extraire en V2 `control plane`, `runner distant` et `object storage`

## Phrase de reference

`La meilleure combinaison retenue pour la V1 est: PWA privee + noeud distant OVH unique portant control plane et runner minimal + runner Linux local sur le PC + home relay + OpenClaw upstream adapte + Codex CLI executor + GitHub pour le code + Project OS DB pour l'etat operateur + stockage local structure en V1 + 8 To local pour l'archive; la V2 extraira ensuite control plane, runner distant et stockage externe.`

## References

- `PROJECT_OS_MASTER_MACHINE.md`
- `docs/architecture/PROJECT_OS_MOTHER_CONTROL_PLANE_ARCHITECTURE.md`
- `docs/architecture/HOST_WINDOWS_VM_LINUX_MATRIX.md`
- `docs/architecture/MEMORY_STORAGE_AND_OPS_BLUEPRINT.md`
- `docs/systems/OPENCLAW_UPSTREAM_DOSSIER.md`
- `docs/roadmap/OPENCLAW_REINFORCEMENT_PLAN.md`
- `docs/roadmap/PROJECT_OS_PWA_VM_V0_1_PLAN.md`
- `docs/roadmap/PROJECT_OS_V1_BUDGET_OVH_PLAN.md`
