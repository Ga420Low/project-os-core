# ADR 0009 - Discord Selective Sync Memory Policy

## Decision

`Discord` est la surface humaine prioritaire et obligatoire, mais sa memoire est en mode `Selective Sync`.

Tout message entrant est:

1. trace comme evenement operateur
2. classe (`chat`, `tasking`, `idea`, `decision`, `note`, `artifact_ref`)
3. decide par `Memory Curator`
4. soit promu vers la memoire canonique
5. soit garde uniquement comme evenement tracable

## Promote

On promeut en priorite:

- decisions explicites
- preferences stables
- missions et tasking utiles
- incidents
- references d'artefacts
- resumes valides

## Skip

On ne promeut pas automatiquement:

- small talk
- hesitations
- duplications
- bruit conversationnel

## Consequences

- Discord reste un espace de travail prive humain/IA
- la memoire canonique reste sobre, inspectable et utile
- le gateway doit toujours produire une decision de promotion explicite
