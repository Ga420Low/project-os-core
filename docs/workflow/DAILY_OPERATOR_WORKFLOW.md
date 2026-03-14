# Daily Operator Workflow

Ce document decrit le workflow quotidien du fondateur avec Project OS.

## Principe fondamental

Le fondateur ne s'adapte pas au systeme. Le systeme s'adapte au fondateur.

- le fondateur parle comme il veut, dans ses mots, a son rythme
- le systeme comprend l'intention, pas les mots-cles
- "ouais vas-y", "go", "envoie", "c'est bon", "lance" = meme intention
- "bof", "non", "stop", "attends", "pas maintenant" = meme intention
- le fondateur ne doit rien sentir : pas de format a respecter, pas de commande a retenir
- tout est autonome, le systeme gere seul et ne derange que quand c'est necessaire
- avec le temps, le systeme apprend les habitudes et le style du fondateur via OpenMemory
- premiere semaine : le systeme pose plus de questions pour confirmer
- apres un mois : il connait les preferences et agit avec moins de friction

Le fondateur ne code jamais. Il ne lit jamais de code brut.
Il parle en humain, il decide, et le systeme execute sous contrat.

## Surface principale: Discord partout

Le fondateur utilise Discord comme surface principale, sur PC comme sur mobile.
Il n'y a pas de planning rigide (matin/soir). Le fondateur interagit au feeling, quand il veut, ou il veut.

Discord fonctionne partout:

- sur PC (app desktop ou navigateur)
- sur mobile (app Discord)

Le fondateur est libre de bouger. Le systeme s'adapte, pas l'inverse.

## Surfaces disponibles

### Discord (PC + mobile) - surface principale

- recevoir les notifications (runs, clarifications, budget)
- approuver ou rejeter des contrats
- repondre aux clarifications
- donner une direction
- tout est comprehensible et actionable sans contexte technique

### Terminal CLI + Dashboard (PC uniquement, optionnel)

Pour les moments ou le fondateur veut aller plus loin:

- `pos monitor` pour voir l'etat complet
- `pos api-run --mode patch_plan --objective "..."` pour lancer un objectif
- `pos approve-contract --id xxx` pour approuver via terminal
- dashboard navigateur pour la supervision visuelle live des runs longs
- review detaillee d'un resultat

Le terminal et le dashboard ne sont pas obligatoires pour le workflow courant.
Discord suffit pour le quotidien.

## Interactions type

### Lancer un objectif

Via Discord:

```
Fondateur: "lance un audit du module memory"
Systeme:   "Nouveau lot propose - Audit complet du module memory.
            Cout estime: 0.35EUR. Dis 'go' pour lancer."
Fondateur: "go"
```

Ou via terminal:

```
pos api-run --mode audit --objective "Audit complet du module memory"
pos approve-contract --id xxx
```

### Recevoir un resultat

```
Systeme:   "project-os/audit-memory termine - 3 issues trouvees, aucune critique.
            0.28EUR. Review dispo quand tu veux."
```

### Repondre a une clarification

```
Systeme:   "Question sur project-os/refactor-memory -
            Deux modules se bloquent. A) Separer (recommande) B) Fusionner
            Pas urgent, j'ai 4h. Si tu reponds pas je fais A."
Fondateur: "A"
```

### Donner une direction

```
Fondateur: "concentre-toi sur le guardian cette semaine"
Systeme:   "Compris. Je priorise le guardian pre-spend pour les prochains lots."
```

## Ce que le fondateur ne fait jamais

- coder
- lire du code brut
- ouvrir des fichiers JSON
- debugger un run en cours
- comprendre le pipeline technique en detail

Le fondateur donne la vision, prend les decisions, et le systeme fait le reste.

## Regles de notification

Le systeme ne spamme pas. Claude API filtre les signaux avant envoi:

- `run_started`: jamais envoye (bruit pur)
- `run_completed`: toujours envoye (resume court)
- `clarification_required`: toujours envoye (besoin de decision)
- `run_failed` + auto-retry: pas envoye (attendre le resultat du retry)
- `run_failed` + no retry: envoye (raison simple, pas de panique)
- `budget_alert < 70%`: pas envoye
- `budget_alert >= 80%`: envoye
- `contract_proposed`: toujours envoye (besoin d'approbation)

Profils de sortie Discord:

- `notification_card` pour `contract_proposed`, `run_completed`, `run_failed`, `clarification_required`, `budget_alert` et les cartes `#runs-live`
- `meeting_thread` pour les deliberations multi-angles visibles
- `founder_synthesis` pour la synthese humaine finale republiquee dans `#pilotage`

Regles dures:

- `notification_card`: maximum 3 lignes. Jamais de code. Jamais de chemin de fichier.
- `meeting_thread`: format structure autorise, pas de limite fixe en lignes, rester lisible et oriente decision.
- `founder_synthesis`: concise mais non bornee a 3 lignes si la situation demande une synthese plus riche.

## Supervision locale - hors pipeline

La supervision locale via terminal + dashboard reste disponible si le fondateur en a besoin.

Ce qui est utile en local:

- comprendre un resultat en detail
- suivre un incident ou un blocage sans bruit Discord
- les automations locales en sandbox peuvent servir d'audit supplementaire

Ce que le systeme fait mieux en local:

- les automations locales sont reproductibles via `execute_run()` avec le pipeline complet (contrats, guardian, memoire, learning)
- les automations locales passent par les memes garde-fous que les gros runs
- elles sont auditables, budgetisees et tracees

Regle: le systeme ne depend jamais d'une app locale separee pour fonctionner. Si une supervision locale est utile, elle reste optionnelle.

## References

- `docs/workflow/ROLE_MAP.md`
- `docs/workflow/LANGUAGE_LEVELS.md`
- `docs/workflow/DISCORD_MESSAGE_TEMPLATES.md`
- `docs/decisions/0013-dual-model-operating-model.md`
