# Project OS Autopilot Pack Plan

## Statut

ACTIVE - Detailed execution roadmap after architecture lock

## Date de cadrage

Document consolide le `2026-03-19`.

Les choix fournisseur et prix ci-dessous ont ete verifies sur sources officielles a
cette date.

## But

Transformer `Project OS` en systeme vraiment operable a distance, sans transformer
Windows en bombe ni construire une infra trop lourde trop tot.

Cette roadmap detaille:

- la V1 canonique sous budget
- les packs a implementer
- l'ordre exact
- les verifications a passer apres chaque pack
- les gates qui disent "on continue" ou "on s'arrete"
- ce qui reste explicitement reporte en V2

## Mantra

- centraliser la verite
- isoler le risque
- rendre chaque action rejouable
- garder Windows ennuyeux et stable
- ne jamais confondre prototype qui marche et systeme tenable

## Override canonique V1

La topologie logique long terme reste:

1. `control plane distant always-on`
2. `runner distant minimal always-on`
3. `runner local Linux sur le PC`
4. `home relay always-on`

Mais la `V1` canonique n'est pas encore un split physique distant.

La `V1` retenue est:

1. `un noeud distant unique OVH`
2. `control plane + runner distant minimal` sur ce meme noeud
3. `Cloudflare Tunnel`
4. `Tailscale`
5. `GitHub private`
6. `home relay`
7. `runner local Linux`

La `V2` robuste reste reportee:

- split `control plane`
- split `remote runner`
- `object storage` externe
- durcissement plus fort du data plane

## Choix fournisseur retenu pour la V1

### Recommandation nette

Le meilleur stack de depart sous contrainte budget pour `Project OS V1` est:

1. `OVHcloud` pour le noeud distant unique
2. `Cloudflare Tunnel` pour l'exposition publique
3. `Tailscale` pour l'admin privee et le home mesh
4. `GitHub` pour le code canonique
5. `stockage local structure + backup OVH` en V1

### Pourquoi OVH gagne en V1

Pourquoi retenu:

- ticket d'entree compatible avec un plafond `<= 30 EUR/mo HT`
- `backup` quotidien inclus
- console `KVM` integree
- anti-DDoS inclus
- assez muscule pour un mono-noeud distant propre

Reference officielle utile:

- [OVHcloud VPS](https://www.ovhcloud.com/en/vps/)

### Plan OVH retenu

V1 canonique:

- `OVH VPS-3`
- `8 vCores`
- `24 GB RAM`
- `200 GB SSD NVMe`
- `backup automatise 1 jour`
- `1.5 Gbit/s` bande passante publique

Lecture produit:

- assez de marge pour `web + api + postgres + redis + runner-remote`
- encore sous le seuil budget fixe
- meilleure V1 testable que deux petits noeuds mal dimensionnes

### Pourquoi on ne reste pas sur le plan Hetzner robuste en V1

Le plan `Hetzner` split etait propre, mais trop cher pour une V1 de validation.

Le bon arbitrage n'est pas de tordre le budget pour forcer la topologie finale.
Le bon arbitrage est:

- V1 budget propre et extractible
- V2 robuste plus tard

## Stack retenu par couche en V1

| Couche | Service retenu | Pourquoi |
| --- | --- | --- |
| Noeud distant unique | `OVH VPS-3` | heberge `web + api + postgres + redis + runner-remote` sur une meme machine, mais en services separes |
| Public exposure | `Cloudflare Tunnel` | pas d'inbound ouvert |
| Admin privee | `Tailscale Personal` | suffisant au debut |
| Code canonique | `GitHub private repo` | branches / PR / reviews |
| Artefacts phase 1 | `local volume + backup OVH` | rapidite de bootstrap sans ajouter un service payant tout de suite |
| Home relay | `mini machine locale always-on` | wake/restart/reprise du poste |
| Runner local | `VM Linux locale` | puissance locale isolee |

## Budget cible V1

### V1 canonique budget

- `OVH VPS-3` = `16.99 EUR/mo HT`
- `Cloudflare Tunnel` = `0`
- `Tailscale Personal` = `0`
- `object storage` externe = reporte

Total cible de base:

- `16.99 EUR/mo HT` hors domaine

### Marge budget restante

Avec un plafond `30 EUR/mo HT`, la marge restante peut servir plus tard a:

- ajouter un volume si besoin
- monter de gamme OVH si la charge le justifie
- ajouter un service annexe avant la V2

### V2 robuste suspendue

La V2 robuste vise ensuite:

- `control plane` separe
- `remote runner` separe
- `object storage` externe

Cette V2 est reportee, pas annulee.

## Naming canonique

### Machines V1

- `projectos-core-01`
- `projectos-relay-home-01`
- `projectos-local-runner-01`

### Machines V2 reportees

- `projectos-control-01`
- `projectos-runner-01`

### Hostnames publics / prives

- `app.projectos.<domain>`
- `api.projectos.<domain>`
- `core.projectos.home`
- `relay.projectos.home`
- `runner.projectos.home`

## Regle dure de compatibilite V1 -> V2

La V1 ne doit jamais etre codee comme un bloc inseparable.

Meme sur un seul noeud, les frontieres suivantes restent obligatoires:

1. `project-os-web`
2. `project-os-api`
3. `postgres`
4. `redis`
5. `project-os-runner-remote`

Ces services cohabitent physiquement en V1, mais doivent rester extractibles.

## Packs d'execution V1

### Pack 0 - Contracts Freeze

#### But

Fermer les contrats avant l'infra.

#### A produire

- `control plane contract`
- `remote runner contract`
- `local runner contract`
- `home relay contract`
- `canonical data model`
- `git workflow agentique`
- `fallback + incident recovery contract`

Reference immediate:

- `docs/architecture/PROJECT_OS_CANONICAL_DATA_MODEL_CONTRACT.md`
- `docs/architecture/PROJECT_OS_CONTROL_PLANE_CONTRACT.md`
- `docs/architecture/PROJECT_OS_REMOTE_RUNNER_CONTRACT.md`
- `docs/architecture/PROJECT_OS_LOCAL_RUNNER_CONTRACT.md`
- `docs/architecture/PROJECT_OS_HOME_RELAY_CONTRACT.md`
- `docs/workflow/PROJECT_OS_AGENTIC_GIT_WORKFLOW_CONTRACT.md`
- `docs/architecture/PROJECT_OS_FALLBACK_AND_INCIDENT_RECOVERY_CONTRACT.md`
- `docs/architecture/PROJECT_OS_STORAGE_AND_ROUTING_MATRIX.md`

#### Verification

- chaque contrat a:
  - inputs
  - outputs
  - droits
  - limites
  - failure modes
  - acceptance checks
- `OpenClaw`, `Codex CLI` et `Project OS` reutilisent les memes noms de contrat pour les objets centraux

#### Gate

- si un contrat cle reste flou, on ne provisionne rien

#### Sortie attendue

Le `Pack 0` est considere ferme cote documentation quand les fichiers suivants sont
ecrits et alignes:

1. `docs/architecture/PROJECT_OS_CANONICAL_DATA_MODEL_CONTRACT.md`
2. `docs/architecture/PROJECT_OS_CONTROL_PLANE_CONTRACT.md`
3. `docs/architecture/PROJECT_OS_REMOTE_RUNNER_CONTRACT.md`
4. `docs/architecture/PROJECT_OS_LOCAL_RUNNER_CONTRACT.md`
5. `docs/architecture/PROJECT_OS_HOME_RELAY_CONTRACT.md`
6. `docs/workflow/PROJECT_OS_AGENTIC_GIT_WORKFLOW_CONTRACT.md`
7. `docs/architecture/PROJECT_OS_FALLBACK_AND_INCIDENT_RECOVERY_CONTRACT.md`
8. `docs/architecture/PROJECT_OS_STORAGE_AND_ROUTING_MATRIX.md`

### Pack 1 - Accounts And Provider Baseline

#### But

Preparer le terrain sans coder profond.

#### Build

- compte OVHcloud
- compte Cloudflare
- compte Tailscale
- domaine
- repository GitHub prive
- naming, tags, secrets inventory

#### Verification

- acces console valide
- domaine sous controle
- tailnet sain
- naming stable ecrit en doc

#### Gate

- si le domaine ou l'auth provider sont encore bricoles, on bloque le pack suivant

### Pack 2 - OVH Core Node

#### But

Sortir la maison mere du PC dans une V1 sous budget.

#### Build

Sur `projectos-core-01`:

- Ubuntu LTS
- Docker Compose
- `project-os-web`
- `project-os-api`
- `postgres`
- `redis`
- terminal fallback
- volumes persistants structures
- metrics/logs de base

#### Verification

1. web app accessible
2. login applicatif OK
3. DB persiste
4. Redis OK
5. redemarrage machine sans perte de service
6. PC eteint -> UI toujours accessible

#### Gate

- si la maison mere ne survit pas a un reboot propre du noeud, on ne continue pas

### Pack 3 - Cloudflare Tunnel And Private Admin

#### But

Exposer proprement sans ouvrir l'origine.

#### Build

- tunnel Cloudflare nomme
- routes `app` / `api`
- Tailscale admin
- SSH cle seulement

#### Verification

1. URL publique via tunnel nomme
2. SSE fonctionne
3. admin seulement via Tailscale
4. aucun port d'app ouvert publiquement sur l'origine

#### Gate

- si le systeme repose encore sur un quick tunnel ou un port entrant, on bloque

### Pack 4 - Remote Runner Minimal On Core Node

#### But

Faire en sorte que `Project OS` reste utile PC eteint.

#### Build

Sur `projectos-core-01`:

- `Codex CLI`
- Git
- workspace manager
- shell de run
- logs de run
- retour branche / PR / patch
- heartbeat vers control plane

#### Verification

1. PC eteint -> chat utile continue a marcher
2. run simple code/shell fonctionne
3. PR/patch revient proprement
4. timeout et annulation fonctionnent

#### Gate

- si PC eteint = chat mort, le pack est rate

### Pack 5 - Home Relay

#### But

Recuperer la puissance locale sans en faire une dependance unique.

#### Build

Sur `projectos-relay-home-01`:

- Tailscale
- wake-on-lan
- ping/healthcheck PC
- ping/healthcheck Hyper-V / VM locale
- commandes bornees:
  - wake
  - status
  - restart VM
  - restart service local

#### Verification

1. le relay remonte `PC awake / asleep / unreachable`
2. wake-on-lan reussi
3. restart VM locale depuis workflow borne
4. aucune fonction de verite ou de chat principal dans le relay

#### Gate

- si le relay devient une mini maison mere, on corrige avant d'aller plus loin

### Pack 6 - Local Runner Safe

#### But

Mettre la puissance du PC au service du systeme, pas l'inverse.

#### Build

Sur `projectos-local-runner-01`:

- VM Linux locale
- `OpenClaw`
- `Codex CLI`
- workspaces jetables
- mount policy du `8 To`
- upload des artefacts vers control plane
- kill switch

#### Verification

1. aucun shell agent direct sur Windows
2. mounts `8 To` scopes et audites
3. artefacts remontent dans la maison mere
4. un run local casse un workspace, pas Windows

#### Gate

- si un agent a RW global sur Windows ou sur le `8 To`, le pack est rate

### Pack 7 - Routing And Failover

#### But

Choisir le bon moteur sans faire penser l'operateur comme un scheduler.

#### Build

- router de runs
- policy:
  - `standard -> distant`
  - `heavy/data-local -> local`
  - `local down -> distant si possible`
  - `besoin local absolu -> degrade clair`

#### Verification

1. 80% des runs standards partent sans choix manuel
2. le systeme explique pourquoi il a choisi une cible
3. fallback runner local -> distant observable

#### Gate

- si le routage reste opaque ou menteur, on bloque

### Pack 8 - Mother Ship Product Layer V1

#### But

Faire de la web app le centre reel dans le cadre V1.

#### Build

- docs notion-like
- PDF explorer
- timeline
- run inspector
- preview workspace / preview URL ou preuve equivalente avant push
- approvals
- decision log
- founder preference registry
- recherche transversale

#### Verification

1. l'operateur suit un run sans shell
2. l'operateur retrouve un doc/PDF/decision depuis l'app
3. une preference confirmee s'applique et reste visible
4. un changement UI peut etre vu avant push GitHub

#### Gate

- si l'operateur doit encore fouiller des fichiers bruts, le pack n'est pas fini

## Packs explicitement reportes en V2

### Pack 9 - Split Remote Topology

#### But

Extraire le mono-noeud V1 en topologie distante plus robuste.

#### Build

- `projectos-control-01`
- `projectos-runner-01`
- migration du runner hors du noeud coeur unique
- revalidation du routage et des heartbeats

#### Verification

1. le split n'oblige pas a changer les contrats applicatifs
2. le runner est extractible sans rearchitecture produit
3. la maison mere reste disponible pendant la migration

#### Gate

- si le split force un gros refacto applicatif, la V1 a ete mal faite

### Pack 10 - External Object Storage And Data Hardening

#### But

Sortir les artefacts vivants du noeud unique et durcir la persistance.

#### Build

- `object storage` externe
- migration PDF/artefacts
- restore drills
- retention policy
- backup DB plus propre

#### Verification

1. upload/download d'artefacts
2. un PDF reste visible sans toucher le PC
3. restore testee
4. metadata intactes apres migration

#### Gate

- si la restoration n'est pas testee, le pack n'est pas ferme

### Pack 11 - Learning And Safety Loop

#### But

Rendre le systeme presque autopilote, sans le rendre fou.

#### Build

- memory learning
- policy learning
- execution learning
- evals
- scoreboard de strategies
- self-improvement via `PR + tests + review + confirmation`

#### Verification

1. une lecon apprise est tracee, visible, reversible
2. pas d'auto-merge critique
3. un patch d'auto-amelioration reste soumis a confirmation finale

#### Gate

- si `autolearning` reste un blob de logs, le pack est rate

## Politique de passage entre packs

On ne passe jamais au pack suivant si:

- la verification du pack courant n'est pas faite
- le rollback n'est pas connu
- le failure mode principal n'est pas documente

## SPOFs explicites a traiter

En V1, les vrais SPOFs sont:

1. `projectos-core-01`
2. `DNS / Cloudflare account`
3. `GitHub`

Le `home relay` n'est pas un SPOF de maison mere.
Le `runner local` n'est pas un SPOF de maison mere.

## Definition de `presque autopilote`

`Project OS` sera considere `presque autopilote` quand:

1. il reste utile PC eteint
2. il bascule proprement entre runner distant et local
3. il sait relire son historique et reprendre
4. il sait relancer la partie locale via relay quand c'est possible
5. il garde toujours la validation finale humaine sur les changements critiques

## Phrase de reference

`La V1 canonique de Project OS est un mono-noeud distant OVH propre, complete par un home relay et un runner local; la V2 robuste separera ensuite control plane, runner distant et stockage externe sans casser les contrats du systeme.`

## Sources officielles

- [OVHcloud VPS](https://www.ovhcloud.com/en/vps/)
- [Cloudflare Tunnel overview](https://developers.cloudflare.com/tunnel/)
- [Cloudflare Tunnel setup](https://developers.cloudflare.com/tunnel/setup/)
- [Tailscale pricing](https://tailscale.com/pricing)
- [Scaleway virtual instances pricing](https://www.scaleway.com/en/pricing/virtual-instances/)
- [DigitalOcean Droplets pricing](https://www.digitalocean.com/pricing/droplets)
