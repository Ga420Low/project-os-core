# Project OS PWA + VM V0.1 Plan

## Statut

ACTIVE - Canonical roadmap V0.1

## Decision actuelle

1. meilleure cible absolue long terme: `Proxmox VE bare metal + Ubuntu Server LTS`
2. meilleure base executable maintenant: `Windows host + Hyper-V + Ubuntu Server 24.04 LTS`
3. `Hyper-V` est un socle transitoire propre, pas la destination finale
4. la portabilite vise le systeme logique, pas le fichier brut de la VM
5. le control plane `Project OS` doit finir hors du PC si l'on veut une vraie maison mere distante
6. la puissance du PC doit etre consommee via des runners Linux isoles, pas via l'OS Windows host
7. la V0.1 n'est pas la cible autopilote finale: il faudra ajouter un runner distant minimal always-on et un home relay

Les arbitrages complets "meilleure option par branche" sont consolides dans:

- `docs/architecture/PROJECT_OS_ARCHITECTURE_DECISION_MATRIX.md`
- `docs/roadmap/PROJECT_OS_AUTOPILOT_ROADMAP.md`
- `docs/roadmap/PROJECT_OS_V1_BUDGET_OVH_PLAN.md`

## But

Livrer une V0.1 propre de `Project OS`:

- PWA privee installable PC/mobile
- runtime principal dans une VM Linux server
- architecture simple, lisible, testable, migrable
- base saine pour un control plane toujours on et une maison mere multi-device

## Point de depart reel

- assainissement host deja largement execute
- tentative `VMware + Ubuntu Desktop` jugee non canonique pour le runtime
- `C:` et `D:` vivent sur le meme NVMe 2 To
- `E:` reste le tier froid disponible
- `Proxmox bare metal` est donc differe sur cette machine tant que Windows doit rester en place

## Actifs existants reutilisables

Le projet ne repart pas de zero.

Actifs deja presents et reutilisables:

- bootstrap coeur, `doctor`, `health snapshot`
- `Memory OS` local (`SQLite`, `sqlite-vec`, `OpenMemory`, tiers `hot/warm/cold`)
- `RuntimeState`, `SessionState`, `ApprovalRecord`, `ActionEvidence`, journal local
- `Mission Router` policy-aware, budget, approvals, blocages
- `Infisical` et support `Universal Auth`
- subsysteme `api_runs`, review loop et observabilite locale
- adaptateur `OpenClaw -> Project OS` disponible mais hors chemin critique V0.1

Regle:

- on reutilise ces briques quand elles servent la V0.1
- on ne reimporte pas leur ancienne doctrine de surface

## Base produit retenue

La base la plus propre a construire est:

- `OpenClaw` comme substrate d'autonomie et d'orchestration
- `Codex CLI` comme moteur officiel d'execution
- `Project OS` comme couche produit, memoire, docs et PWA operateur

Regle V0.1:

- `OpenClaw` reste surtout upstream et adapte
- `Codex CLI` reste l'executor canonique des runs
- `Project OS` absorbe progressivement les couches proprietaires utiles

Ce qu'on ne fait pas:

- gros merge sale immediate
- fork massif d'`OpenClaw` sans mesure
- fine-tuning precoce avant un vrai socle `RAG + memory + evals`

## Couches canoniques

### 1. Jetable

Ce qui peut changer sans remettre en cause le systeme:

- hyperviseur courant (`Hyper-V` aujourd'hui)
- format disque VM (`.vhdx`, demain autre chose)
- integration locale Windows
- raccourcis et conforts operateur

### 2. Portable

Ce qui doit survivre au changement d'hyperviseur:

- `Ubuntu Server LTS`
- `/srv/projectos`
- services `systemd`
- base de donnees
- code
- config
- scripts d'installation et d'exploitation

### 3. Reconstructible

Ce qui doit permettre de tout remonter ailleurs:

- procedure de bootstrap
- backups
- exports
- inventaire des dependances
- checklist de validation

## Regles d'architecture

1. une seule surface primaire operateur: PWA privee
2. un seul runtime principal: `Ubuntu Server LTS`
3. aucune dependance canonique a un desktop Linux
4. `Project OS` garde etat, memoire, preuves et decisions
5. `Codex CLI` execute
6. `OpenClaw` reste optionnel, non primaire
7. zero migration brute du legacy
8. code, data, config et services doivent rester separables
9. le host Windows n'est jamais la sandbox autonome canonique
10. la maison mere doit finir sur un control plane toujours on

## Regles donnees et fichiers

1. le disque de la VM est un detail d'implementation, pas le contrat de portabilite
2. supprimer le dossier ou le disque virtuel detruit la VM; il doit donc rester hors repo Git
3. les livrables utilisateur ne doivent pas rester enfermes dans le disque VM par design
4. tout export lisible humain (`pdf`, images, rapports, archives) doit sortir via un chemin explicite
5. le chemin de sortie canonique de bootstrap est:
   - host Windows: `D:/ProjectOS/exports`
   - VM Linux: `/srv/projectos/exports`
6. le transport de bootstrap doit passer par un mecanisme portable:
   - `ssh/scp/rsync`
   - ou un partage explicite documente
7. a terme produit, la sortie canonique doit passer par telechargement depuis la PWA/backend
8. `hot` / `warm` restent sur disque Linux natif dans la VM
9. `cold/archive` reste sur `E:/ProjectOSArchive`
10. `sqlite` live, `indexes`, `sessions` et `cache` ne doivent pas vivre sur un partage hyperviseur

## Regles d'operabilite VM

1. un boot GUI n'est pas un prerequis canonique
2. les preuves minimales d'operabilite sont:
   - boot OK
   - SSH OK
   - ecriture fichier test OK
   - services backend OK
3. les checkpoints doivent rester courts et lisibles
4. pas de snapshot avec etat memoire lourd comme pratique canonique
5. toute modif hyperviseur doit etre minimale, documentee, reversible
6. aucun media d'installation ne doit rester attache apres validation

## Contrat d'automatisation fichiers

- `Codex CLI` doit pouvoir operer la VM par `SSH`
- `Codex CLI` peut deposer ou recuperer des livrables via le chemin d'exports explicite
- les fichiers internes runtime restent dans la VM
- les fichiers destines a l'operateur doivent sortir soit dans `D:/ProjectOS/exports`, soit via telechargement HTTP depuis la PWA
- aucun flux ne doit dependre d'une manipulation manuelle opaque dans l'UI d'un hyperviseur

## Exception securite temporaire

Statut:

- ACTIVE TEMPORAIREMENT pendant le bootstrap du socle `Hyper-V + Ubuntu Server`

Ouvertures de securite temporaires acceptees:

1. `Hyper-V` et les composants Windows necessaires seront re-actives sur le host
2. `openssh-server` sera actif dans la VM, joignable uniquement depuis le host ou le perimetre prive choisi
3. un `sudo NOPASSWD` peut etre tolere temporairement pour le bootstrap automatise
4. un pont d'exports host/VM peut etre ouvert temporairement si documente

Regle canonique:

- cette ouverture n'est pas l'etat final cible
- elle sert uniquement a accelerer la creation de la base propre et le merge de la V0.1
- elle doit etre revue puis refermee apres merge complet et validation bout-en-bout

Fermeture obligatoire apres merge valide:

1. supprimer le `NOPASSWD` temporaire
2. durcir l'acces SSH selon le mode retenu (`key-only`, bind restreint, puis Tailscale-only si conserve)
3. re-evaluer le mecanisme d'exports (`scp`, partage explicite, telechargement PWA)
4. re-evaluer les protections host Windows compatibles avec le socle retenu

## Pourquoi cet ordre

1. assainir d'abord pour eviter de migrer un etat sale
2. poser un socle transitoire propre avant de coder
3. construire backend avant UI pour stabilite des interfaces
4. brancher PWA puis Tailscale pour fermer proprement la boucle d'acces
5. polisher seulement apres fonctionnel valide

## Phases V0.1

### Phase 1 - Assainissement final

Objectif:

- confirmer l'absence d'auto-runs inconnus

Tests:

- reboot
- observation 10 min
- aucun process fantome

### Phase 2 - Socle transitoire propre

Objectif:

- etablir `Hyper-V + Ubuntu Server 24.04 LTS` comme base executable et portable

Actions:

- re-activer `Hyper-V`
- creer une VM `Ubuntu Server`
- activer `SSH`
- poser `Cockpit`
- poser la structure `/srv/projectos`
- definir un chemin d'exports explicite host <-> VM

Tests:

- boot propre
- reboot propre
- SSH host -> VM
- fichier test VM -> host
- aucun besoin d'un desktop Linux pour operer

### Phase 3 - Backend minimal

Objectif:

- exposer les interfaces minimales de pilotage
- brancher le moteur de chat sur `Codex CLI` (et non sur Discord/Electron)

Interfaces minimales:

- `POST /auth/login`
- `GET /api/status`
- `GET /api/session`
- `GET /api/activity/recent`
- `POST /api/chat/messages`
- `GET /api/chat/stream`

Tests:

- appels API manuels
- message aller/retour
- stream temps reel depuis `Codex CLI` vers `GET /api/chat/stream`

## Contrat chat V0.1 (moteur Codex CLI)

### Moteur unique

- le moteur de reponse canonique est `Codex CLI`
- le backend ne depend pas d'une surface Discord/Electron pour repondre
- `OpenClaw` reste substrate d'autonomie disponible, mais pas surface primaire V0.1

### Bridge backend -> Codex CLI

- commande canonique Windows: `C:/Users/theod/AppData/Roaming/npm/codex.cmd exec --json`
- commande canonique Linux VM: `codex exec --json`
- le backend lance un process par message (ou par run), capture `stdout/stderr`, et traduit les events JSONL en etats UI
- si `codex.ps1` est bloque par execution policy, le systeme doit utiliser `codex.cmd` ou `codex.exe`

### Flux produit

1. `POST /auth/login` ouvre une session applicative locale
2. `POST /api/chat/messages` enregistre le message operateur et demarre un run `Codex CLI`
3. `GET /api/chat/stream` diffuse les transitions `idle -> thinking -> responding -> done|error`
4. `GET /api/activity/recent` expose les runs recents et les erreurs exploitables
5. `GET /api/status` et `GET /api/session` exposent la sante et le contexte operateur

### Contraintes de robustesse

- timeout explicite par run
- annulation explicite possible
- logs horodates pour chaque run
- retour d'erreur lisible operateur en cas d'echec process

### Phase 4 - Front minimal

Objectif:

- rendre l'etat operateur lisible

Scope:

- layout 70/30
- chat principal
- input `Saisir un message`
- pills `Mode / API / Reasoning`
- panneau droit `system/session/activity`
- etats `idle/thinking/responding/error`

Tests:

- responsive de base
- envoi/reception
- transitions d'etat

### Phase 5 - PWA

Objectif:

- installer la meme app sur PC et mobile

Scope:

- manifest
- icones
- mode standalone

Tests:

- install desktop
- install mobile

### Phase 6 - Acces prive

Objectif:

- fermer l'acces au perimetre prive

Scope:

- Tailscale
- login app

Tests:

- acces via tailnet uniquement
- login requis

### Phase 7 - Polish V0.1

Objectif:

- stabiliser l'experience sans suringenierie

Scope:

- lisibilite
- micro-interactions legeres
- robustesse session

Tests:

- session longue
- refresh/reconnexion
- non-regression

## Dependencies baseline

### Host Windows

- `Hyper-V`
- Windows Terminal / OpenSSH client
- Tailscale client
- Git for Windows
- Chromium/Edge

### VM Ubuntu Server 24.04 LTS

- `git`, `curl`, `ca-certificates`, `build-essential`
- Python 3 + `venv`
- `uv` ou `pip`
- Node.js LTS + `npm` (ou `pnpm`)
- `sqlite3`
- `tmux`, `openssh-server`
- `cockpit`

### Stack V0.1

- FastAPI + Uvicorn
- Next.js + React + Tailwind
- PWA manifest + service worker
- auth simple locale derriere Tailscale

## Criteres d'acceptation

### Doc coherente

- aucune doc active contradictoire
- docs contradictoires marquees `SUPERSEDED`
- docs audit + drift passes

### V0.1 done

- app installable PC/mobile
- login fonctionnel
- message aller/retour fiable
- etats simples fiables
- panneau droit fonctionnel
- acces prive valide
- pas de dependance Discord/Electron
- pas de dependance a un desktop Linux pour operer

## References

- `docs/architecture/PROJECT_OS_ARCHITECTURE_DECISION_MATRIX.md`
- `docs/roadmap/PROJECT_OS_AUTOPILOT_ROADMAP.md`
- `docs/architecture/PROJECT_OS_MOTHER_CONTROL_PLANE_ARCHITECTURE.md`

- `README.md`
- `AGENTS.md`
- `PROJECT_OS_MASTER_MACHINE.md`
- `docs/architecture/FOUNDER_SURFACE_MODEL.md`
- `docs/roadmap/BUILD_STATUS_CHECKLIST.md`
- `docs/roadmap/PROJECT_OS_FRONTEND_V1_PLAN.md`
- `docs/roadmap/PROXMOX_BARE_METAL_PIVOT.md`
