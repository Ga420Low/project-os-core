# Memory, Storage and Ops Blueprint

Ce document fige la memoire locale actuelle de `Project OS`: ce qui fait foi, ce qui sert au retrieval, ce qui est seulement inspiration, et ce qui reste un upgrade path.

## Objectif

Eviter la memoire de mouche.
Construire une memoire locale durable, inspectable, traçable, portable et extensible sans deplacer la verite hors du repo ou hors de la machine.

## Principe

La memoire de l'agent doit vivre sur le poste.
Les APIs servent au raisonnement et a la consolidation, pas au stockage durable du contexte.

## Architecture actuelle

Le systeme memoire livre est maintenant compose de ces couches:

- `SQLite`
  - role: verite canonique locale
  - porte: `memory_records`, `decision_records`, `learning_signals`, `channel_events`, `gateway_dispatch_results`, `api_run_*`
- `OpenMemory`
  - role: sidecar retrieval local-first compatible
  - statut: moteur secondaire utile, pas verite canonique
- `sqlite-vec`
  - role: retrieval vectoriel embarque pour les `memory_records`
- `Retrieval Sidecar`
  - role: query expansion, session recall, temporal decay, MMR
- `Memory OS substrate`
  - role: couche d'exploitation memoire au-dessus du canonique
  - objets: `MemCube`, `MemoryBlock`, `ThoughtMemory`, `RecallPlan`, `SupersessionRecord`
- `Shared Memory Blocks`
  - role: blocs partages type Letta pour `guardian`, `discord`, `curator`, `UEFN`
- `Sleeptime Curator`
  - role: consolidation asynchrone et generation de memoire de conclusions
- `Temporal Graph Sidecar`
  - role: reasoning temporel local
  - backend courant: `sqlite shadow`
  - backend cible: `kuzu embedded`
- `fichiers locaux`
  - role: preuves, captures, rapports, revisions de blocs, artefacts, archives
- `Infisical`
  - role: secrets et configuration sensible
- `OpenTelemetry hooks`
  - role: point d'extension de tracing; la persistance locale des traces est deja active

## Ce qui fait foi

La verite memoire reste repartie ainsi:

- `memory_records` = episodes/promotions compatibles avec l'existant
- `decision_records` = decisions confirmees ou changees
- `learning_signals` = signaux d'apprentissage
- `channel_events` et `gateway_dispatch_results` = historique operateur
- `api_run_*` = historique des runs
- `MemCube` et `ThoughtMemory` = couche d'exploitation memoire, pas seconde verite metier
- `MemoryBlock` = blocs partages et consolidations durables

## Etat reel actuel

Ce qui est effectivement livre dans le repo:

- `Memory OS` local branche
- `MemCube`, `MemoryBlock`, `ThoughtMemory`, `RecallPlan`, `SupersessionRecord` poses
- blocs partages versionnes localement dans le runtime
- recall enrichi par `thought memories`
- profils dual-layer:
  - `founder_stable_profile`
  - `recent_operating_context`
- `Sleeptime Curator` async avec fallback deterministe
- supersession tracee et non destructive
- temporal graph sidecar local avec fallback `sqlite shadow`
- traces memoire locales persistantes
- commandes CLI memoire dediees

La couche secrets et ops locale est maintenant branchee de cette facon:

- `Infisical` est la source primaire reelle des secrets
- le repo est relie via `.infisical.json`
- le projet actif est `Project OS Core`
- `OPENAI_API_KEY` est stockee dans `Infisical`
- le mode runtime local est `infisical_required`
- `doctor --strict` confirme cette contrainte

## Inspirations retenues

Ce qui a ete explicitement vole comme pattern, sans deplacer la souverainete:

- `Letta`
  - shared blocks
  - sleeptime curator
- `TiM`
  - memoire de conclusions plutot que logs bruts
- `Supermemory`
  - supersession non destructive
- `HippoRAG / retrieval papers`
  - rerank, diversification, recall contextuel
- `Graphiti`
  - direction pour la lane temporelle, sans migration prematuree

## Candidats surveilles

- `MemOS`
  - statut: reference architecturale, pas composant a integrer tel quel
- `Graphiti`
  - statut: candidat fort pour une lane graph plus riche si la douleur devient reelle
- `A-MEM`
  - statut: candidat pour enrichissement bidirectionnel des memories
- `Mem0`
  - statut: candidat secondaire
- `Zep`
  - statut: candidat secondaire
- `Qdrant`
  - statut: upgrade path si `sqlite-vec` devient trop court
- `LanceDB`
  - statut: upgrade path pour stockage multimodal/versionne
- `Temporal`
  - statut: upgrade path pour orchestration durable niveau entreprise

## Niveaux de memoire

### Hot

Doit rester sur SSD rapide.

Contient:

- etat runtime courant
- file d'execution
- checkpoints de session
- index de retrieval utiles immediatement
- dernieres preuves et derniers artefacts

### Warm

Reste preferentiellement sur SSD, avec eventuelle descente progressive.

Contient:

- memoire recente consolidee
- resumes de mission
- episodes importants
- embeddings recents
- rapports utiles a court/moyen terme

### Cold

Peut vivre sur disque lent dedie.

Contient:

- historique long terme
- bundles de preuve complets
- screenshots anciens
- captures lourdes
- logs bruts
- rapports archives
- snapshots de projets

## Repartition physique recommandee

Contrainte actuelle:

- `C:` = 500 Go, souvent rempli
- `D:` = 1.5 To sur SSD 990 Pro
- disque lent 8 To = disponible pour memoire archive

Decision:

- ne pas construire le coeur actif sur `C:`
- utiliser `D:` pour le hot path et le warm principal
- utiliser le disque lent 8 To pour le cold archive

## Chemins cibles

Avant branchement du disque archive, utiliser un placeholder de lettre.

### SSD `D:`

- `D:\\ProjectOS\\runtime`
- `D:\\ProjectOS\\memory_hot`
- `D:\\ProjectOS\\memory_warm`
- `D:\\ProjectOS\\indexes`
- `D:\\ProjectOS\\sessions`
- `D:\\ProjectOS\\cache`

### Disque archive `ARCHIVE_DRIVE`

- `<ARCHIVE_DRIVE>:\\ProjectOSArchive\\episodes`
- `<ARCHIVE_DRIVE>:\\ProjectOSArchive\\evidence`
- `<ARCHIVE_DRIVE>:\\ProjectOSArchive\\screens`
- `<ARCHIVE_DRIVE>:\\ProjectOSArchive\\reports`
- `<ARCHIVE_DRIVE>:\\ProjectOSArchive\\logs`
- `<ARCHIVE_DRIVE>:\\ProjectOSArchive\\snapshots`

## Contrats de conception

- tout ce qui est critique au temps de reponse reste hors disque lent
- toute memoire doit etre rejouable ou resumable
- toute preuve doit avoir un pointeur stable
- aucune donnee critique ne doit dependre d'un service cloud externe pour exister
- la migration `SQLite -> Qdrant/LanceDB` doit rester possible

## Politique memoire proactive

La memoire ne sert pas seulement a stocker.
Elle sert a compenser l'oubli, a limiter les repetitions steriles et a maintenir la qualite du systeme.

Le systeme doit donc:

- promouvoir regulierement les decisions confirmees
- promouvoir regulierement les decisions changees
- retenir les erreurs recurrentes et leurs corrections
- retenir les indices de derive, de boucle et de baisse de capacite
- soutenir des mecanismes de `refresh` quand le raisonnement se deconnecte de l'historique utile

Cette politique est proactive:

- l'humain n'a pas besoin de rappeler constamment ce qu'il faut memoriser
- le systeme doit anticiper ce qui merite d'etre retenu
- le systeme doit chercher ce qui manque quand il sent qu'il s'appauvrit

## Decision pour les prochains lots

La direction retenue est:

- garder `Project OS` proprietaire de la memoire canonique
- garder `OpenClaw` en surface/transport
- continuer a enrichir `Memory OS` local
- ne pas introduire de seconde verite memoire parallele

Les prochains gains memoire les plus probables sont:

- richer temporal graph si `sqlite shadow` plafonne
- meilleurs thoughts merges / forget lifecycle
- instrumentation `OpenTelemetry` plus riche
- injections de lessons learned plus directes dans les gros runs
