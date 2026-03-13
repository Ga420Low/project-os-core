# Memory, Storage and Ops Blueprint

Ce document fige la strategie de memoire locale, de stockage physique et d'observabilite de Project OS.

## Objectif

Eviter la memoire de mouche.
Construire une memoire locale durable, inspectable, portable et extensible.

## Principe

La memoire de l'agent doit vivre sur le poste.
OpenAI sert au raisonnement, pas au stockage durable du contexte.

## Pile retenue

- `OpenMemory`
  - role: moteur memoire primaire local-first
- `SQLite`
  - role: source de verite locale pour l'etat, la memoire indexee et les pointeurs d'artefacts
- `sqlite-vec`
  - role: recherche vectorielle embarquee et portable
- `fichiers locaux`
  - role: screenshots, preuves, rapports, journaux, archives
- `Letta`
  - role: backup de comparaison et reference de benchmark
- `Langfuse`
  - role: observabilite LLM, traces, datasets, evals
- `OpenTelemetry`
  - role: traces techniques, logs, metriques
- `Infisical`
  - role: secrets et configuration sensible

## Etat reel actuel

La couche secrets et ops locale est maintenant branchee de cette facon:

- `Infisical` est la source primaire reelle des secrets
- le repo est relie via `.infisical.json`
- le projet actif est `Project OS Core`
- `OPENAI_API_KEY` est stockee dans `Infisical`
- le mode runtime local est `infisical_required`
- `doctor --strict` confirme cette contrainte

Le fallback local hors repo reste disponible comme filet de developpement, mais il n'est plus la source attendue du systeme.

## Candidats surveilles

- `Mem0`
  - statut: candidat secondaire
  - raison: bonne couche memoire universelle, plus SDK que noyau
- `Zep`
  - statut: candidat secondaire
  - raison: memoire + knowledge graph
- `Qdrant`
  - statut: upgrade path
  - raison: moteur vectoriel plus costaud si l'echelle depasse `sqlite-vec`
- `LanceDB`
  - statut: upgrade path
  - raison: stockage multimodal et versionne
- `Temporal`
  - statut: upgrade path
  - raison: execution durable niveau entreprise

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

## Decision pour les 6 prochains mois

On construit:

- `OpenMemory + SQLite + sqlite-vec + fichiers locaux`
- `Langfuse + OpenTelemetry + Infisical`

On surveille:

- `Letta`
- `Mem0`
- `Zep`

On garde comme upgrade path:

- `Temporal`
- `Qdrant`
- `LanceDB`
