# External Stack Reference

Ce document classe les repos externes selon leur vrai role dans la stack finale de Project OS.

## Core

Ces briques sont au coeur de la version finale.

- `OpenClaw`
  - role: shell operateur, Discord, inbox, acces distant, skills
  - decision: coeur de la couche operateur
- `LangGraph`
  - role: orchestration durable, reprise, human-in-the-loop, graphes d'agents
  - decision: coeur de l'orchestration
- `SQLite`
  - role: verite locale canonique
  - decision: coeur du stockage local
- `sqlite-vec`
  - role: recherche vectorielle embarquee et portable
  - decision: coeur du retrieval local
- `OpenMemory`
  - role: sidecar retrieval local-first compatible
  - decision: brique coeur utile, mais la verite memoire reste dans `SQLite + Memory OS`
- `GPT API` (`OpenAI`)
  - role: cerveau generaliste et arbitrage
  - decision: coeur du raisonnement
- `UFO`
  - role: reference forte pour le worker Windows et les patterns Desktop AgentOS
  - decision: coeur de la couche Windows
- `Stagehand`
  - role: execution web fiable
  - decision: coeur de la couche browser
- `pywinauto`
  - role: perception et actions Windows/UIA structurees
  - decision: coeur du fast path Windows
- `OmniParser`
  - role: fallback vision quand UIA ne suffit pas
  - decision: coeur de la voie de secours visuelle
- `Langfuse`
  - role: traces LLM, datasets, evals
  - decision: coeur de l'observabilite agent
- `OpenTelemetry`
  - role: logs, traces et metriques
  - decision: coeur de l'observabilite technique
- `Infisical`
  - role: secrets et configuration sensible
  - decision: coeur de la securite operatoire

## Support

Ces briques renforcent le systeme sans devenir le centre de gravite.

- `gstack`
  - role: inspiration process, roles, discipline de review, modes de travail
  - decision: support methodologique, pas runtime
- `pywinauto-mcp`
  - role: patterns de desktop state, refs UI, OCR, exposition MCP
  - decision: support et acceleration de conception
- `Accessibility Insights for Windows`
  - role: inspection UIA et cartographie des apps Windows
  - decision: outil d'inspection obligatoire, pas runtime
- `GroundCUA`
  - role: grounding, dataset, supervision, idees d'eval
  - decision: support recherche et evaluation
- `Letta`
  - role: reference forte pour shared blocks et sleeptime curator
  - decision: source de patterns, pas noyau memoire proprietaire
- `WorldGUI`
  - role: benchmark desktop GUI
  - decision: support evaluation
- `WindowsAgentArena`
  - role: benchmark Windows agent
  - decision: support evaluation
- `OSWorld`
  - role: benchmark generaliste d'agents computer use
  - decision: support evaluation

## Research Only

Ces repos sont utiles pour apprendre, comparer et piquer des idees, mais pas pour devenir notre noyau.

- `gui-agent`
  - role: grounding, ranking, planning, recherche
  - decision: lecture utile, pas prod
- `Open Agent Studio`
  - role: inspiration produit, automation semantique, UX agentique
  - decision: inspiration seulement
- `Open Computer Use`
  - role: inspiration plateforme, safety, auditabilite
  - decision: interessant, mais pas coeur Windows local
- `Agent-S / Agent S2`
  - role: composition generaliste vs specialise, patterns d'agents
  - decision: source d'idees et de comparaison
- `Mem0`
  - role: couche memoire SDK universelle
  - decision: interessant, mais pas encore coeur
- `Zep`
  - role: memoire + knowledge graph
  - decision: interessant en etude, pas coeur
- `Temporal`
  - role: execution durable niveau entreprise
  - decision: upgrade path, pas besoin au demarrage
- `Qdrant`
  - role: moteur vectoriel local/serveur plus costaud
  - decision: upgrade path si `sqlite-vec` devient trop limite
- `LanceDB`
  - role: base vectorielle et multimodale locale
  - decision: upgrade path si les besoins multimodaux grossissent

## Rejected / Not Core

Ces briques peuvent etre brillantes, mais ne doivent pas structurer Project OS.

- `Astron RPA`
  - role: suite RPA enterprise lourde
  - decision: trop lourde et trop loin du cap local-first
- `OpenAdapt`
  - role: generative process automation generaliste
  - decision: trop gros et trop eloigne du noyau vise

## Regle d'usage

Un repo externe ne devient pas `core` parce qu'il est impressionnant.
Il devient `core` seulement s'il remplit trois conditions:

1. il renforce directement la version finale retenue
2. il s'integre sans avaler notre coeur proprietaire
3. il ameliore robustesse, memoire, execution ou evaluation de facon mesurable
