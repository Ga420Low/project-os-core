# Branch Governance and Build Order

Ce document fixe la maniere de construire Project OS sans perdre la coherence ni l'ambition.

## Principe

Le vrai danger n'est pas le manque d'ambition.
Le vrai danger est le spaghetti entre des briques puissantes.

Project OS doit donc etre construit comme un systeme de branches maitrisees.
Chaque branche a:

- un role clair
- une limite claire
- une metrique de reussite
- un contrat avec les autres branches

## Les 9 branches majeures

### 1. Gateway / Operator

But:

- parler avec l'operateur via Discord et les futures surfaces

Risque:

- devenir le cerveau du systeme par erreur

Regle:

- c'est une interface, pas la verite machine

Succes:

- toute commande operateur passe par une enveloppe claire, tracee et policy-aware

### 2. Orchestration

But:

- planifier
- router
- reprendre
- attendre
- escalader

Risque:

- concentrer trop de logique metier dans le planner

Regle:

- orchestre, ne remplace ni la memoire ni les workers

Succes:

- une mission peut etre suspendue, reprise et replanifiee proprement

### 3. Memory

But:

- retenir ce qui compte sur le long terme

Risque:

- tout stocker sans hierarchie
- ou ne rien consolider

Regle:

- memoire `hot / warm / cold`, locale, inspectable, migrable

Succes:

- l'agent reprend une mission ou une relation operateur sans repartir de zero

### 4. Runtime State

But:

- tenir la verite machine en temps reel

Risque:

- verite fragmente entre scripts, OCR, UIA, logs et captures

Regle:

- une seule source de verite canonique

Succes:

- n'importe quelle action lit le meme etat courant et produit la meme preuve

### 5. Workers

But:

- agir reellement sur Windows, le web, les medias et les apps metier

Risque:

- workers trop intelligents, opaques, ou non auditables

Regle:

- workers deterministes, observables et specialises

Succes:

- chaque worker expose des contrats stables d'entree, d'execution et de sortie

### 6. Perception

But:

- comprendre ecran, UIA, DOM, etats applicatifs et artefacts visuels

Risque:

- dependre uniquement de la vision brute

Regle:

- privilegier `API / DOM / UIA`, garder la vision en fallback

Succes:

- l'agent choisit la lane de perception la plus fiable selon le contexte

### 7. Evaluation

But:

- prouver objectivement que l'agent s'ameliore

Risque:

- croire qu'il progresse parce qu'il impressionne ponctuellement

Regle:

- benchmarks, scenarios, taux de reprise, taux d'echec, cout, latence

Succes:

- chaque progression importante se mesure sur un cadre stable

### 8. Ops / Observability

But:

- voir ce qui se passe, pourquoi cela casse, et combien cela coute

Risque:

- construire un agent aveugle impossible a ameliorer

Regle:

- traces, logs, couts, latence, datasets, incidents

Succes:

- chaque run important est analysable et rejouable

### 9. Security / Policy

But:

- garder le systeme puissant mais controlable

Risque:

- permissions trop larges
- secrets mal geres
- actions risquee silencieuses

Regle:

- approvals, allowlists, secrets, zones interdites, preuves

Succes:

- l'autonomie reste supervisable et reversible
- `doctor --strict` doit pouvoir prouver que la policy secrets/runtime est respectee

## Les 5 regles de coherence

### 1. Une constitution

Le fichier [PROJECT_OS_MASTER_MACHINE.md](D:/ProjectOS/project-os-core/PROJECT_OS_MASTER_MACHINE.md) sert de constitution.
Chaque changement important doit rester compatible avec lui ou bien le mettre a jour explicitement.

### 2. Un decision log

A chaque choix important:

- on ecrit ce qu'on prend
- on ecrit ce qu'on refuse
- on ecrit pourquoi

### 3. Des contrats entre branches

Exemples:

- `gateway` ne parle pas directement aux scripts opaques
- `workers` n'ecrivent pas librement dans la memoire
- `memory` ne planifie pas
- `runtime_state` ne decide pas de strategie produit

### 4. Des stage gates

On ne passe pas a la phase suivante si la precedente n'est pas propre.

Exemples:

- pas d'autonomie avancee sans runtime stable
- pas de longue mission sans memoire locale
- pas de remote control fort sans policy, approvals et evidence

### 5. Une ambition mesuree

On garde l'ambition maximale, mais on sequence.
Le cap n'est pas de faire petit.
Le cap est de faire grand sans casser la structure.

## Les 6 capacites obligatoires du super agent

Le systeme final doit etre fort dans:

- raisonner
- se souvenir
- agir
- se corriger
- se faire superviser
- s'ameliorer

S'il manque une seule de ces capacites, le systeme n'est pas encore un super agent.

## Ordre de construction retenu

L'ordre de travail officiel est:

1. definir le cadre et les contrats
2. ecrire le nouveau coeur propre, script par script et module par module
3. seulement ensuite auditer l'ancien systeme
4. classer chaque morceau ancien en `keep`, `migrate`, `rewrite` ou `delete`
5. migrer uniquement ce qui renforce la nouvelle architecture

## Politique vis-a-vis de l'ancien repo

Le nouveau coeur ne doit pas etre aspire par les cochonneries de l'ancien repo.

Donc:

- on ne construit pas dans l'ancien repo
- on ne copie pas des hacks sans contrat
- on n'importe une vieille logique que si elle a passe l'audit

## Mode d'audit de l'ancien systeme

Quand l'audit commencera, chaque element ancien sera range dans une seule categorie:

- `keep`
  - deja propre et compatible avec l'architecture cible
- `migrate`
  - utile mais a deplacer dans la nouvelle structure
- `rewrite`
  - utile en idee, mauvais en implementation
- `delete`
  - ne doit plus influencer le coeur

## Regle operative

Quand on hesite entre vitesse et coherence, on privilegie la coherence si le choix devient structurel.
Quand on hesite entre ambition et prudence, on garde l'ambition mais on la passe par des etapes propres.
