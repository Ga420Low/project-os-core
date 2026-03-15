# Sanctuary Security Layer

## Decision

`Project OS` doit evoluer vers une couche `sanctuaire` explicite.

Cette couche n'est pas un simple hardening diffus.
Elle devient une couche produit a part entiere, au-dessus des briques deja posees:

- runtime truth
- memory
- router
- gateway
- workers
- OpenClaw facade

Objectif:

- limiter la casse si le poste est compromis
- bloquer les actions dangereuses meme apres une intrusion partielle
- empecher les sorties de donnees compromettantes ou personnelles
- rendre les chemins a risque inspectables, traçables et refusables

`DECISION CONFIRMED`

## Pourquoi une nouvelle couche

Le socle actuel couvre deja une partie importante:

- secrets hors snapshot runtime
- allowlist plugin
- `S3` local only sans fallback cloud
- loopback local pour les surfaces OpenClaw critiques
- zones interdites
- approvals et evidence
- watchdog/self-heal du gateway

Mais ce niveau reste celui d'un systeme durci.
Ce n'est pas encore un `sanctuaire`.

Un sanctuaire exige en plus:

- verite d'approval impossible a spoof par simple metadata
- frontieres destructives plus strictes
- surfaces critiques minimales et explicites
- blast radius reduit si un compte, un agent ou un adaptateur est compromis
- defense degradee mais encore sure en cas de panne partielle

## Modele de menace retenu

La couche sanctuaire vise d'abord les cas realistes suivants:

1. compromission partielle du poste utilisateur
2. plugin/adaptateur qui tente un chemin de sortie ou de destruction
3. payload operateur ou Discord qui essaie de contourner approvals ou routing
4. fuite de secret, de donnees personnelles ou d'elements compromettants
5. crash/restart/panne qui remettrait le systeme dans un etat permissif

Elle ne pretend pas annuler seule une compromission totale admin + kernel.
Elle vise a durcir fortement le niveau userland / runtime / policy.

## Principes sanctuaire

1. `default deny` pour les actions dangereuses
2. aucune verite sensible ne doit dependre d'une metadata mutable fournie par l'entree
3. `S3` ne doit jamais fallback vers le cloud
4. les surfaces reseau critiques restent locales et bornees
5. les chemins destructifs exigent approvals persistants et verifiables
6. les zones interdites restent techniquement et logiquement hors de portee
7. tout mode degrade doit rester `safe by block`, pas `safe by hope`

## Chantiers v1

### 1. Approval Truth Hardening

But:

- sortir la verite d'approval des `intent.metadata`
- utiliser uniquement les approvals persistants et leur etat reel

Travaux:

- router lit l'approval depuis le store runtime
- expiration appliquee au listing et a la resolution
- merge metadata au lieu d'ecrasement

### 2. Destructive Boundary Hardening

But:

- rendre les chemins destructifs plus durs a atteindre meme apres compromis partiel

Travaux:

- policy stricte `destructive` / `exceptional`
- allowlist worker plus dure
- garde explicite pour fichiers, suppression, ecriture systeme, shell a haut risque

### 3. Data Egress Guard

But:

- ne pas parler de toi, ne pas sortir de donnees perso, ne pas repeter d'elements compromettants

Travaux:

- redaction plus forte en sortie operateur
- garde perso/secret avant delivery Discord/WebChat
- audit clair des sorties bloquees

### 4. Local Surfaces And Token Hygiene

But:

- minimiser les surfaces exploitables si quelqu'un rentre sur la machine

Travaux:

- loopback seulement quand possible
- tokens locaux scopes au minimum
- rotation et revocation plus faciles
- verification periodique des listeners actifs

### 5. Recovery Without Unsafe Degrade

But:

- si un composant tombe, il doit soit se reparer, soit se bloquer proprement

Travaux:

- watchdog/self-heal deja pose pour OpenClaw
- etendre plus tard aux autres surfaces critiques
- incidents visibles sans remettre le systeme en mode permissif

## Etat au 2026-03-15

Deja en place:

- gateway OpenClaw loopback + token
- plugin allowlist explicite
- voie locale `Ollama` prete
- `S3` sans fallback cloud
- zone `E:\\DO_NOT_TOUCH`
- watchdog OpenClaw local

Gaps prioritaires encore ouverts:

- verite d'approval encore trop dependante de `intent.metadata`
- expiration/merge des approvals runtime encore incomplets

## Verdict

La couche sanctuaire devient un vrai chantier de roadmap.

Priorite pratique:

1. `Approval Truth Hardening`
2. `Destructive Boundary Hardening`
3. `Data Egress Guard`

Tant que ces lots ne sont pas clos, la securite est `durcie`, mais pas encore `sanctuaire`.
