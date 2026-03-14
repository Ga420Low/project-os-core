# Discord Message Templates

Ce document definit les formats exacts des messages que le systeme envoie au fondateur sur Discord.

Tous les messages sont produits par Claude API (le traducteur) a partir des signaux structures de GPT API.
Le fondateur ne recoit jamais de JSON, de code ou de chemin de fichier.

## Regles generales

- maximum 3 lignes par message
- francais simple, pas de jargon technique
- jamais de code, jamais de chemin de fichier, jamais de JSON
- chaque message doit etre comprehensible sans contexte technique
- chaque message doit etre actionable (le fondateur sait quoi faire)
- les emojis sont utilises comme marqueurs visuels rapides

## Templates par type de signal

### Run complete

```
[branche] termine — [decision en 1 phrase].
[nb fichiers] fichiers, [cout]EUR. Review dispo au retour.
```

Exemple:

```
codex/refactor-memory termine — Memory separe en bridge, store et curator.
5 fichiers, 0.28EUR. Review dispo au retour.
```

### Clarification requise

```
Question sur [branche] —
[question en francais simple].
A) [option A] B) [option B]
[urgence]. Si tu reponds pas je fais [fallback].
```

Exemple:

```
Question sur codex/refactor-memory —
Deux modules se bloquent mutuellement.
A) Separer proprement (recommande) B) Fusionner
Pas urgent, j'ai 4h. Si tu reponds pas je fais A.
```

### Run echoue (sans retry)

```
[branche] echoue — [raison simple].
[action requise ou "Aucune action requise"].
```

Exemple:

```
codex/add-guardian echoue — erreur de connexion a l'API OpenAI.
Je reessaie dans 30 min, aucune action requise.
```

### Contrat propose

```
Nouveau lot propose — [objectif en 1 phrase].
Cout estime: [montant]EUR. Dis "go" pour lancer.
```

Exemple:

```
Nouveau lot propose — Ajouter le guardian pre-spend avec detection de boucle.
Cout estime: 0.45EUR. Dis "go" pour lancer.
```

### Budget alert

```
Budget jour a [pourcentage]% — [depense]EUR sur [limite]EUR.
[consequence simple].
```

Exemple:

```
Budget jour a 82% — 2.87EUR sur 3.50EUR.
Les runs non urgents attendront demain.
```

### Review terminee (resume)

```
Review de [branche] — [verdict en 1 phrase].
[detail principal si pertinent].
[prochaine action].
```

Exemple accepte:

```
Review de codex/refactor-memory — Code propre, tout est bon.
Pret a merger. Dis "merge" pour valider.
```

Exemple avec reserves:

```
Review de codex/refactor-memory — 1 probleme a corriger.
Fuite de connexion detectee, GPT va corriger automatiquement.
```

### Mission avancee (futur lot 5)

```
Mission [nom] — etape [n]/[total] terminee.
[resume etape]. Prochaine etape: [description].
```

## Reponses du fondateur

Le fondateur parle comme il veut. Le systeme ne lui impose aucun format.

### Principe

Le fondateur ne doit rien retenir, rien apprendre, rien formater.
Il parle dans ses mots et le systeme comprend l'intention.

Le systeme maintient un state persistant (SQLite) qui sait en permanence:

- quel contrat attend une approbation
- quelle question attend une reponse
- quels runs sont actifs
- quel budget reste

Ce state permet de comprendre le contexte de chaque message sans appel API.

### Exemples d'interpretation

Intention "approuver":

- "go", "vas-y", "envoie", "lance", "c'est bon", "ouais", "ok", "fais-le"
- Le systeme sait qu'un contrat est en attente → il approuve sans rien demander

Intention "refuser":

- "stop", "non", "bof", "pas maintenant", "annule", "laisse tomber"
- Le systeme sait quel contrat est concerne → il rejette

Intention "choisir une option":

- "le premier", "A", "fais la separation", "comme tu recommandes"
- Le systeme sait quelle question est en attente → il identifie l'option

Intention "donner une direction":

- "concentre-toi sur le guardian", "fais le memory d'abord", "on change de priorite"
- Le systeme escalade a Claude API pour interpreter et agir

### Apprentissage progressif

Le systeme apprend les habitudes du fondateur via OpenMemory:

- premiere semaine: le systeme confirme plus souvent ("Tu veux dire approuver le lot memory ?")
- apres un mois: il connait les expressions du fondateur et agit directement
- les preferences stables sont promues en memoire durable

### Quand le systeme ne comprend pas

Si le message est vraiment ambigu par rapport au contexte:

```
J'ai pas compris — tu parles du lot memory ou du guardian ?
```

Regle: le systeme ne devine pas. Il demande. Mais il demande rarement car le state persistant lui donne presque toujours le contexte necessaire.

## Anti-patterns

Ce que le systeme ne doit jamais envoyer sur Discord:

- un message de plus de 3 lignes
- du code ou du pseudo-code
- un chemin de fichier (`src/project_os_core/...`)
- un JSON brut
- un message sans action claire
- un message technique que seul un developpeur comprendrait
- un message de panique ("ERREUR CRITIQUE!!!")
- un message redondant (meme information deja envoyee)

## References

- `docs/workflow/LANGUAGE_LEVELS.md`
- `docs/architecture/FRENCH_OPERATOR_OUTPUT_POLICY.md`
- `docs/integrations/DISCORD_CHANNEL_TOPOLOGY.md`
- `docs/decisions/0013-dual-model-operating-model.md`
