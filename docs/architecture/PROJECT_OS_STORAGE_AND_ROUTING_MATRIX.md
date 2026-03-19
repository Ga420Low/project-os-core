# Project OS Storage And Routing Matrix

## Statut

ACTIVE - Pack 0 clarity contract for storage and routing

## But

Fixer sans ambiguite:

- ou vit chaque type de donnee
- qui peut la lire
- qui peut la modifier
- quand `Project OS` route vers `OVH`
- quand `Project OS` appelle le `PC local`

Ce document sert a repondre proprement aux questions operateur du type:

- "mes docs projet sont ou ?"
- "le chat parle a quoi ?"
- "quand on appelle mon PC ?"
- "quand le remote runner suffit ?"

## Regle racine

Le systeme ne doit pas appeler le `PC local` par reflexe.

Le systeme appelle:

- `OVH` par defaut
- le `PC local` seulement quand il apporte une vraie valeur

La valeur typique du `PC local` est:

- puissance
- donnees locales
- lanes specialisees
- reprise locale

## Matrice de stockage canonique

| Type de donnee | Verite canonique | Copies tolerées | Ecriture autorisee | Lecture autorisee |
| --- | --- | --- | --- | --- |
| Code source | `GitHub private repo` | clone humain PC, workspaces runners | humain, runner via branche/PR/patch | humain, runners, control plane via refs |
| Docs source versionnees du projet | `GitHub private repo` | clone humain PC, workspaces runners | humain, runner via proposition Git | humain, runners, control plane via refs |
| Tasks / issues internes | `Project OS DB` sur OVH | caches UI | control plane | UI, control plane, OpenClaw via contrats |
| Decisions | `Project OS DB` sur OVH | caches UI | control plane apres confirmation humaine | UI, control plane, runners via retrieval borne |
| Preferences fondateur | `Project OS DB` sur OVH | caches UI | control plane apres confirmation humaine | UI, OpenClaw, Codex context, runners |
| Timeline / runs / approvals / incidents | `Project OS DB` sur OVH | caches UI, logs derives | control plane | UI, terminal fallback, analytics |
| Docs operateur metadata | `Project OS DB` sur OVH | caches UI | control plane | UI, retrieval, OpenClaw |
| PDF / captures / exports / artefacts vivants V1 | volume structure OVH + metadata DB | copies locales temporaires runner, miroir 8 To | control plane ou runner via upload | UI, control plane, runners si autorises |
| PDFs / artefacts vivants V2 | object storage OVH + metadata DB | caches runner, miroir 8 To | control plane ou runner via upload | UI, control plane, runners si autorises |
| Workspace runner distant | disque du runner distant | aucune copie canonique | remote runner | remote runner, control plane via evidence |
| Workspace runner local | disque VM locale | aucune copie canonique | local runner | local runner, control plane via evidence |
| Datasets locaux | `8 To` ou autre stockage local | montages RO scopes dans local runner | humain, processus locaux autorises | local runner selon policy |
| Archive froide / miroir | `8 To` | aucune verite centrale remplacee | humain, jobs d'archivage bornes | humain, local runner si monte explicitement |

## Regles simples

### GitHub

`GitHub` garde:

- le code
- les docs source du repo
- les branches
- les PR

Il ne garde pas:

- la timeline operateur
- les preferences fondateur
- l'etat des runs

### OVH DB

La `DB Project OS` garde:

- la verite operateur
- la memoire projet utile
- les metadata d'artefacts et de docs
- l'etat des runners
- les approvals et incidents

### OVH storage vivant

Le stockage vivant OVH garde:

- PDF
- captures
- exports
- bundles de preuve
- artefacts de run

En `V1`, cela peut etre un volume structure.
En `V2`, cela doit tendre vers `Object Storage`.

### PC local

Le `PC local` garde:

- le clone humain
- la VM locale
- les outils locaux
- les datasets locaux
- l'archive froide

Il ne garde pas la verite globale de la maison mere.

## Matrice de routage canonique

| Type de demande | Route par defaut | Pourquoi | Fallback |
| --- | --- | --- | --- |
| discussion simple | `control plane + remote runner` si LLM necessaire | pas besoin du PC | degrade chat si remote down |
| lecture doc / notes / PDF | `control plane` | la maison mere doit suffire | aucun appel PC par defaut |
| tasking / planning / decisions | `control plane` | verite operateur centrale | aucun appel PC par defaut |
| petit run code standard | `remote runner` | utile PC eteint | local runner si remote KO et local dispo |
| preview frontend standard | `remote runner` par defaut | pas besoin du PC pour la plupart des previews | local runner si besoin environnement local |
| build/test lourd | `local runner` | puissance locale utile | distant si acceptable et local indisponible |
| run qui depend d'un dataset local | `local runner` | donnees non centralisees | aucun si dataset non disponible a distance |
| lane media/GPU locale | `local runner` | hardware local specifique | aucun ou service dedie plus tard |
| wake/restart/reprise poste | `home relay` | reprise locale borne | manuel si relay KO |
| urgence quand le chat casse | `terminal fallback` sur control plane | toujours-on | acces d'urgence hors app |

## Quand on appelle le PC

Le `PC local` est appele seulement dans ces cas:

1. un run demande explicitement:
   - plus de CPU/RAM
   - gros build
   - gros test
   - traitement media
   - GPU plus tard

2. un run depend de donnees locales:
   - dataset sur `8 To`
   - archive non promue
   - export local non synchronise

3. une reprise locale est necessaire:
   - wake-on-lan
   - restart VM
   - restart service local borne

Le `PC local` n'est pas appele pour:

- lire des docs de la maison mere
- lire la timeline
- discuter normalement avec le systeme
- voir les decisions et preferences
- lire les PDFs deja promus

## Chat flow canonique

Quand l'operateur parle au chat:

1. le message entre dans le `control plane`
2. le `control plane` decide s'il faut:
   - juste repondre
   - ouvrir un preview
   - lancer un run distant
   - lancer un run local
3. le `control plane` garde l'historique et la decision de routage

Donc:

- le chat ne parle pas directement au `PC`
- le chat ne parle pas directement a `GitHub`
- le chat parle a la maison mere

## Preview and branch flow

Pour un changement de bouton ou une modif visible:

1. `try in preview`
2. workspace runner
3. preview URL ou preuve equivalente
4. validation humaine
5. `save branch` si souhaite
6. `open PR`
7. `merge`

Le preview ne doit pas exiger de push `GitHub`.

## Mount policy du 8 To

Le `8 To` ne doit jamais etre traite comme un disque libre-service pour les agents.

Zones recommandees:

```text
8TB/
|-- memory-code/   (RO)
|-- datasets/      (RO)
|-- archives/      (RO)
|-- exports/       (promotion explicite)
|-- workspace/     (RW runner local uniquement)
`-- artifacts/     (RW runner local uniquement)
```

## Failure and degradation rules

### Si le PC est eteint

Le systeme doit encore garder:

- chat utile a distance
- docs / PDF / timeline / tasks / decisions / preferences
- runs standards sur `remote runner`

Le systeme perd:

- jobs lourds locaux
- lanes data-local
- lanes GPU/media locales

### Si OVH est down

Le systeme perd la maison mere.

Le `PC local` ne devient pas automatiquement la nouvelle verite.

Il peut seulement aider a:

- garder des copies locales
- relancer plus tard
- restaurer

## Acceptance checks

Le systeme respecte cette matrice quand:

1. un doc du repo vit dans `GitHub` et pas seulement sur le PC
2. une decision operateur vit dans la `DB Project OS`
3. un PDF promu est lisible depuis la maison mere sans monter le `PC`
4. un run standard part sur `OVH` sans toucher le `PC`
5. un run data-local part sur le `local runner`
6. la route choisie est visible et justifiable dans l'app

## Phrase de reference

`OVH porte la maison mere et les runs standards; le PC local est appele seulement pour la puissance, les donnees locales et la reprise; GitHub garde le code; la DB Project OS garde la verite operateur; le 8 To reste un miroir et une archive, pas la source unique.`

## References

- `docs/architecture/MEMORY_STORAGE_AND_OPS_BLUEPRINT.md`
- `docs/architecture/PROJECT_OS_CANONICAL_DATA_MODEL_CONTRACT.md`
- `docs/architecture/PROJECT_OS_CHAT_TO_PREVIEW_AND_GIT_CONTRACT.md`
- `docs/architecture/PROJECT_OS_LOCAL_RUNNER_CONTRACT.md`
- `docs/architecture/PROJECT_OS_REMOTE_RUNNER_CONTRACT.md`
- `docs/roadmap/PROJECT_OS_AUTOPILOT_PACK_PLAN.md`

