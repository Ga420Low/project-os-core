# Role Map

Ce document definit qui fait quoi dans Project OS.

Le systeme repose sur trois acteurs complementaires et un fondateur humain.
Aucun acteur ne s'auto-valide. Chaque acteur a un role precis.

## GPT API (gpt-5.4, 1M contexte) - Le Cerveau

### Ce qu'il fait

- code les gros lots (audit, design, patch_plan, generate_patch)
- planifie les missions multi-lots
- brainstorme l'architecture
- produit du structured output (JSON schema-bound)
- raisonne sur 1M tokens de contexte (voit tout le projet)

### Ce qu'il ne fait pas

- ne parle jamais directement au fondateur
- ne review jamais son propre code
- ne decide jamais seul de pousser du code
- ne traduit jamais en francais humain

### Personnalite

Technique, precis, executant. Pense en code et en structures.

### Quand il intervient

- pendant la phase EXECUTE d'un run API
- pendant la phase PLAN d'une mission
- pendant le brainstorm d'architecture

## Claude API (opus/sonnet, 1M contexte) - L'Auditeur + Le Traducteur

### Role 1: Auditeur

- review le code produit par GPT (vrai regard exterieur)
- challenge les decisions architecturales
- detecte les bugs, les trous de securite, les incoherences
- produit des signaux de qualite et de risque
- donne une deuxieme opinion genuinement differente (modele different = biais differents)

### Role 2: Traducteur

- recoit les questions structurees de GPT (format `structured_question`)
- traduit en francais humain simple pour le fondateur
- filtre le bruit (decide quoi envoyer sur Discord, quoi garder silencieux)
- traduit les reponses du fondateur en retour (format `founder_decision`)

### Role 3: Filtre anti-bruit

- sur 10 signaux emis par GPT dans une journee, seulement 5 arrivent au fondateur
- les `run_started` sont filtres (bruit pur)
- les retries silencieux sont filtres (attendre le resultat)
- les alerts mineures sont filtrees (pas utile)

### Ce qu'il ne fait pas

- ne code pas les gros lots (GPT est meilleur pour ca)
- ne remplace pas le runtime local (la verite reste dans Project OS)
- ne contourne pas le contrat de run

### Personnalite

Critique, humain, protecteur. Pense en risques et en clarte.

### Quand il intervient

- apres la phase EXECUTE (review du resultat)
- quand GPT emet une clarification (traduction vers Discord)
- quand le fondateur repond (traduction vers GPT)
- quand un run se termine (resume pour Discord)

## Theo (le fondateur) - Direction et decision

### Ce qu'il fait

- donne la vision et les ambitions du projet
- prend les decisions strategiques
- approuve ou rejette les contrats de run
- repond aux clarifications
- review les resultats a haut niveau

### Ce qu'il ne fait jamais

- coder
- lire du code brut
- ouvrir des fichiers JSON ou des artefacts runtime
- debugger
- comprendre le pipeline technique en detail

### Comment il interagit

- sur PC: terminal CLI + dashboard navigateur
- en mobile: Discord uniquement
- style: francais simple, reponses courtes ("go", "stop", "B", "fusionne")

## Supervision locale (terminal + dashboard)

### Ce qu'il fait

- suivre le dashboard et le terminal live
- comprendre un resultat en detail
- iterer localement sur un petit probleme
- ecrire des docs de vision

### Ce qu'il ne fait plus

- ne constitue pas une voie produit separee
- ne remplace pas `Discord` pour l'operateur
- ne remplace pas `Claude API` comme traducteur/auditeur
- ne remplace pas `GPT API` comme lane code massive

### Pourquoi ce changement

Le systeme doit rester pilotable depuis `Discord` et verifiable via le runtime local.
La supervision locale est un outil de preuve et d'inspection, pas une identite agent separee.

## Deliberation multi-angles

Les angles d'analyse ne sont pas de nouveaux acteurs autonomes.

Ils sont une couche de review structuree activee quand:

- un arbitrage est important
- le risque est eleve
- plusieurs prismes doivent etre confrontes
- une synthese arbitree est preferable a une discussion libre

Leur place:

- `Planner` propose les angles
- `Critic` aide a choisir les contradictions utiles
- `Guardian` porte les vetos et contraintes dures
- `Memory Curator` promeut seulement la synthese et le `DecisionRecord`
- un `Moderator` procedurale orchestre la reunion

Regle dure:

- les angles n'ont aucune autorite directe sur le runtime
- ils n'executent rien
- ils n'ajoutent pas une nouvelle identite produit
- ils servent la decision, puis s'effacent derriere une synthese

## Flux de traduction

```
GPT API travaille
  -> produit un structured_question (JSON)
    -> Claude API recoit le JSON
      -> Claude decide: envoyer ou filtrer ?
        -> si envoyer une notification_card: traduit en francais humain (3 lignes max)
        -> si une reunion structuree est ouverte: alimente le meeting_thread et la founder_synthesis
          -> envoie sur Discord via OpenClaw
            -> Theo repond en humain ("go", "B", "fusionne")
              -> Claude traduit en founder_decision (JSON)
                -> GPT API recoit et reprend le travail
```

## Regles d'escalade

### Quand remonter au fondateur

- contrat de run propose (toujours)
- clarification requise (toujours)
- run complete (toujours, resume)
- run echoue sans retry possible (toujours)
- budget >= 80% du plafond journalier (toujours)

### Quand ne PAS remonter au fondateur

- run demarre (bruit)
- retry en cours (attendre le resultat)
- budget < 70% (pas utile)
- signaux techniques internes (entre machines)

### Quand le systeme peut decider seul

- si `fallback_if_no_answer` est defini et que `can_wait_hours` est depasse
- si le retry est automatique et que `max_attempts` n'est pas atteint
- si le signal est filtre par les regles anti-bruit

## References

- `docs/decisions/0013-dual-model-operating-model.md`
- `docs/workflow/LANGUAGE_LEVELS.md`
- `docs/workflow/DAILY_OPERATOR_WORKFLOW.md`
- `docs/analysis-angles/README.md`
- `docs/integrations/DISCORD_MEETING_SYSTEM_V1.md`
