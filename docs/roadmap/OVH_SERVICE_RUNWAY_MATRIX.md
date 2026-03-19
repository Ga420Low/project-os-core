# OVH Service Runway Matrix

## Statut

ACTIVE - OVH-native service map for Project OS growth

## But

Documenter que `OVHcloud` ne sert pas seulement a heberger une VM, mais peut
porter une bonne partie de la trajectoire produit de `Project OS` sans changer de
provider a chaque nouvelle couche.

Ce document ne dit pas "prendre tout".

Il dit:

- ce que `OVHcloud` propose vraiment
- pourquoi c'est interessant pour `Project OS`
- a quel moment cela devient utile
- ce qui reste inutile ou premature

## Mantra de lecture

- catalogue riche ne veut pas dire bon choix immediat
- un service est utile quand il supprime un vrai goulot
- toute brique ajoutee doit reduire une dette, pas juste ajouter du bruit

## Vision generale

`OVHcloud` a effectivement une vraie profondeur de catalogue.

Pour `Project OS`, cela veut dire qu'on peut envisager, chez un meme provider:

1. compute always-on
2. stockage objet
3. archive froide
4. backup structure
5. recherche / analytics
6. IA serverless et endpoints
7. GPU si un jour le besoin de calcul localise augmente
8. meme du quantique si un jour il y a un cas d'usage reel

Cela ne veut pas dire que tout doit entrer dans la V1.

## Matrice des briques OVH

| Brique OVH | Existe reellement | Pertinence Project OS | Decision actuelle |
| --- | --- | --- | --- |
| `VPS` | oui | base du `core node` always-on | prendre maintenant |
| `Public Cloud Compute` | oui | utile si on veut sortir du simple VPS ou ajouter des workers | plus tard si besoin |
| `Object Storage` | oui | tres bon fit pour PDF, artefacts, captures, exports | premiere extension naturelle |
| `Cold Archive` | oui | excellent pour evidence froide et archives longues | plus tard |
| `Backup Agent` | oui | interessant si on veut une sauvegarde plus structuree hors simple dumps/snapshots | plus tard |
| `Managed OpenSearch` | oui | utile si la recherche documentaire et observabilite depassent le simple stack DB/index | plus tard, si justifie |
| `AI Endpoints` | oui | utile pour briques IA annexes sans infra GPU dediee | plus tard, selon cas d'usage |
| `Embeddings / code LLM / NLP endpoints` | oui | fort potentiel pour search, RAG, code helpers, classement | plus tard, quand le retrieval est valide |
| `Speech / audio endpoints` | oui via catalogue AI Endpoints | potentiellement utile pour voix, transcription, commandes vocales | pas en V1 |
| `AI Deploy / AI Training / GPU` | oui | utile si on veut des lanes GPU ou inference/deploiement plus lourds | pas avant vrai besoin |
| `Quantum Platform / QPU` | oui | reel, mais hors besoin actuel de `Project OS` | hors scope |

## Ce qu'on peut raisonnablement lire comme \"pepites\"

### 1. Object Storage

Pourquoi c'est une vraie pepite:

- compatible `S3`
- fit naturel pour:
  - PDF
  - captures
  - exports
  - artefacts
  - pieces jointes
- sort les fichiers vivants du noeud principal

Sources:

- [OVH Object Storage](https://www.ovhcloud.com/fr/public-cloud/object-storage/)

Decision:

- pas obligatoire en `V1`
- premiere extension OVH recommandee apres le noyau

### 2. Cold Archive

Pourquoi c'est interessant:

- bon fit pour la memoire froide, les preuves anciennes, les gros exports figes
- permet de garder l'historique sans engraisser le stockage chaud

Sources:

- [OVH Cold Archive](https://www.ovhcloud.com/fr/public-cloud/cold-archive/)

Decision:

- clairement utile plus tard
- pas une brique de debut

### 3. Managed OpenSearch

Pourquoi c'est prometteur:

- peut devenir utile pour:
  - recherche documentaire large
  - analytics
  - logs
  - timeline et evidence search a grande echelle

Sources:

- [OVH Managed OpenSearch](https://www.ovhcloud.com/fr/public-cloud/opensearch/)

Decision:

- ne pas le prendre avant d'avoir prouve les limites de:
  - `Postgres`
  - retrieval actuel
  - index metadata simple

### 4. AI Endpoints

Pourquoi c'est plus qu'un gadget:

- OVH reference reellement des `LLM`, des `code LLM`, des `embeddings` et d'autres
  categories d'usage dans sa page `Public Cloud prices`
- cela peut devenir une brique utile pour:
  - retrieval
  - classement
  - summarisation
  - fonctions annexes dans la maison mere

Sources:

- [OVH Public Cloud prices](https://www.ovhcloud.com/fr/public-cloud/prices/)

Exemples visibles sur la page prix:

- `DeepSeek-R1-Distill-Llama-70B`
- `Qwen2.5-Coder-32B-Instruct`
- `Qwen3-Coder-30B-A3B-Instruct`
- categories `Embeddings`

Decision:

- tres interessant pour la suite
- pas necessaire pour le coeur V1 si `Codex CLI` et le runner couvrent deja le besoin

### 5. Speech / audio

Il y a bien une presence audio dans le catalogue `AI Endpoints`, par exemple des
pages catalogue `Whisper` cote OVH.

Sources:

- [Whisper large v3 - Speech to Text](https://www.ovhcloud.com/en/public-cloud/ai-endpoints/catalog/whisper-large-v3/)

Decision:

- oui, cela ouvre une vraie piste `voice layer` pour `Project OS`
- mais apres stabilisation du control plane, pas avant

### 6. GPU / AI Deploy / AI Training

Pourquoi c'est interessant:

- si `Project OS` veut un jour:
  - inference plus lourde
  - workers GPU
  - entrainement
  - deployment d'un modele specialise

Sources:

- [OVH AI & Machine Learning](https://www.ovhcloud.com/fr/public-cloud/ai-machine-learning/)
- [OVH Public Cloud prices](https://www.ovhcloud.com/fr/public-cloud/prices/)

Decision:

- vraie runway
- pas un besoin fondateur de la V1

### 7. Quantum / QPU

Oui, OVH a une vraie offre quantique.

Sources:

- [OVH Quantum Computing](https://www.ovhcloud.com/fr/public-cloud/quantum-computing/)

Decision:

- reel
- impressionnant
- hors besoin de `Project OS` aujourd'hui

## Lecture strategique pour Project OS

La vraie bonne nouvelle n'est pas "OVH a plein de trucs".

La vraie bonne nouvelle est:

- on peut prendre `OVH VPS-3` maintenant
- puis ajouter plus tard, sans changer de maison:
  - `Object Storage`
  - `Cold Archive`
  - `OpenSearch`
  - `AI Endpoints`
  - `Speech`
  - `GPU`

Autrement dit:

- `OVHcloud` peut servir de simple hebergeur en `V1`
- puis de vraie plateforme d'extension en `V2+`

## Decision produit actuelle

### Prendre maintenant

1. `OVH VPS-3`
2. `Cloudflare Tunnel`
3. `Tailscale`
4. `GitHub`

### Ajouter en premier plus tard

1. `OVH Object Storage`

### Ajouter ensuite si les signaux le justifient

1. `Cold Archive`
2. `Managed OpenSearch`
3. `AI Endpoints`
4. `Speech`
5. `Backup Agent`

### Hors scope actuel

1. `Quantum`
2. GPU lourds sans besoin reel mesure

## Phrase de reference

`OVHcloud n'est pas juste un VPS moins cher: c'est une runway plausible pour faire grandir Project OS sans changer de provider a chaque couche. La bonne discipline est donc de partir petit, mais de garder en tete que le meme provider peut ensuite absorber object storage, archive, recherche, IA et audio si ces briques resolvent un vrai goulot.`

