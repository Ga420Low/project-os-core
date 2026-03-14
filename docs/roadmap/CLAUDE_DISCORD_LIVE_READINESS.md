# Claude + Discord Live Readiness

## But

Ce document fixe le prochain lot concret:

- brancher `Claude API` pour la review et la traduction humaine
- brancher `Discord` en vrai via `OpenClaw`
- prouver la boucle complete avec un message reel

Ce document n'est pas une policy generale.
C'est un plan d'execution pour le premier vrai smoke test live.

## Etat reel au 14 mars 2026

### Claude

Etat prouve localement:

- `OPENAI_API_KEY` est resolu depuis `Infisical`
- `ANTHROPIC_API_KEY` est resolu depuis `Infisical`
- le package `anthropic` est installe dans l'environnement Python actif
- `claude-haiku-4-5-20251001` repond reellement
- `claude-sonnet-4-20250514` repond reellement

Conclusion:

- reviewer Claude: pret
- translator Claude: pret

### Doctor / readiness gate

Etat reel:

- `doctor --strict` passe
- mais il reste faux-vert pour `Claude`

Cause:

- `doctor --strict` ne verifie pas encore:
  - `ANTHROPIC_API_KEY`
  - l'import du package `anthropic`
  - le chemin reviewer / translator

Conclusion:

- le runtime Claude marche
- le readiness gate n'est pas encore complet

Ce n'est pas un blocage pour le premier smoke test live.
C'est un hardening a faire juste apres preuve du live.

### Discord / OpenClaw

Etat reel:

- les policies, templates et le pipeline sont poses dans le repo
- `OpenClaw` replay et doctor existent
- la validation live reste fail-closed tant qu'aucun vrai message entrant n'a ete prouve
- la boucle sortante `Project OS -> OpenClaw -> Discord` depend encore de la config plugin `discordAccountId` + `operatorTargets`
- le manifest `openclaw.plugin.json` n'expose pas encore ces champs, donc la config live complete reste a finir

Il manque encore la preuve du canal reel:

- bot Discord de test
- token
- serveur de test
- vrai message entrant
- vrai message sortant

## Secrets et config minimums

### Secrets runtime `Project OS`

- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`

### Credentials et config `Discord / OpenClaw`

Pour la partie Discord, le point d'integration reel est `OpenClaw`.

Donc:

- `Project OS` ne consomme pas directement un `DISCORD_BOT_TOKEN` aujourd'hui
- le token / compte Discord vit cote `OpenClaw`
- la boucle sortante utilise un `discordAccountId` configure dans `OpenClaw`

Regle:

- ne jamais stocker un login humain Discord
- utiliser un bot Discord cree via le Developer Portal
- raccorder ce bot a un compte/canal configure dans `OpenClaw`

### Config non sensible

A garder hors secrets:

- `discord application id`
- `guild / server id`
- `channel ids`
- flags de polling
- config runtime `OpenClaw`
- `discordAccountId`
- `operatorTargets`
- `operatorPollingIntervalMs`
- `enablePolling`

## Setup Discord retenu

Pour le premier test live, rester minimal:

- creer une application Discord
- ajouter un bot
- inviter ce bot dans un serveur de test uniquement
- relier ce bot a un compte Discord exploitable par `OpenClaw`
- permissions minimales au depart:
  - voir les salons
  - lire l'historique
  - envoyer des messages
  - utiliser les embeds si necessaire

Le but n'est pas d'ouvrir toute la surface Discord.
Le but est de prouver la boucle canonique.

## Ordre d'execution retenu

### 1. Poser le bot Discord de test

- creer l'application et le bot
- recuperer `DISCORD_BOT_TOKEN`
- stocker le token hors repo
- inviter le bot sur le serveur de test

### 2. Configurer `OpenClaw` pour le canal reel

- verifier le runtime `OpenClaw`
- verifier le plugin `project-os-gateway-adapter`
- verifier les ids et cibles de canal necessaires:
  - `discordAccountId`
  - `operatorTargets`
  - `operatorPollingIntervalMs`
  - `enablePolling`
- ne rien brancher qui contourne `Project OS`
- verifier que le manifest plugin expose bien ces champs avant de declarer la boucle sortante "prete"

### 3. Rejouer les gardes-fous locaux

Avant live:

- `py D:/ProjectOS/project-os-core/scripts/project_os_entry.py openclaw doctor`
- `py D:/ProjectOS/project-os-core/scripts/project_os_entry.py openclaw replay --all`

Le replay reste obligatoire meme si `Claude` est deja pret.

### 4. Prouver un vrai message entrant

Objectif:

- envoyer un vrai message Discord
- prouver `Discord -> OpenClaw -> Gateway -> Mission Router`

Tant que ce point n'est pas prouve, le lot live n'est pas considere termine.

### 5. Prouver un vrai run avec review et traduction

Objectif:

- lancer un vrai run
- faire passer le run par `GPT`
- faire reviewer le resultat par `Claude Sonnet`
- faire traduire le signal humain par `Claude Haiku`
- faire revenir le message sur Discord

La preuve attendue est:

- un input reel
- une decision runtime canonique
- une sortie Discord reelle

## Definition of done

Le lot est considere `ready` seulement si les points suivants sont vrais:

- `ANTHROPIC_API_KEY` est lisible par le runtime
- les deux modeles Claude repondent reellement
- le bot Discord de test recoit un vrai message
- le pipeline `OpenClaw -> Gateway -> Mission Router` est prouve sur ce message
- la boucle sortante `Project OS -> OpenClaw -> Discord` est configuree avec `discordAccountId` et `operatorTargets`
- un vrai run passe par `reviewer` puis `translator`
- un vrai message retour est visible sur Discord
- aucune etape ne contourne la verite canonique locale

## Non-negociables

- pas de bricolage
- pas de bypass du `Mission Router`
- pas de message Discord considere comme preuve sans trace runtime
- pas de declaration `live` sans vrai message entrant et sortant
- pas de confusion entre readiness reel et `doctor` faux-vert

## Patch a faire juste apres le premier smoke test

Une fois la preuve live faite, durcir immediatement:

1. `doctor --strict` doit verifier `ANTHROPIC_API_KEY`
2. `doctor --strict` doit verifier l'import `anthropic`
3. `doctor --strict` doit verifier que le pipeline reviewer / translator est branchable
4. le manifest `openclaw.plugin.json` doit exposer les champs runtime necessaires a la boucle sortante Discord
5. la readiness live doit distinguer clairement:
   - `OpenAI seulement`
   - `OpenAI + Claude`
   - `OpenAI + Claude + Discord`

## Suite logique apres ce lot

Quand ce lot est prouve, l'ordre recommande reste:

1. fermer la boucle `review -> revision -> review`
2. exploiter les vraies `GitHub Issues` fermees comme memoire de fiabilite
3. ajouter un `Mission Planner` en mode suggestion
4. repousser le scheduler proactif a plus tard

Voir aussi:

- `docs/roadmap/MINI_ROADMAP_PATCH_2026-03-14.md`
- `docs/integrations/OPENCLAW_GATEWAY_ADAPTER.md`
- `docs/integrations/DISCORD_OPERATING_MODEL.md`
