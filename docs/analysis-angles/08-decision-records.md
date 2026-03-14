# Decision Records

## But

Capturer le noyau utile d'une reunion sans polluer la memoire avec le transcript complet.

## Ce qui est promu

Promouvoir seulement:

- decision finale
- conditions
- points bloques
- prochaines actions
- angles actives
- hypotheses cle si elles restent operantes
- metriques a surveiller si elles comptent apres la reunion

Ne pas promouvoir par defaut:

- chaque message
- chaque detail de contradiction
- les differences de style
- les risques dupliques

## Schema canonique

Champs requis:

- `record_id`
- `topic`
- `meeting_type`
- `date`
- `angles_activated`
- `decision`
- `conditions`
- `next_actions`
- `promote_to_memory`

Champs recommandes:

- `blocking_issues`
- `assumptions_kept`
- `metrics_to_watch`
- `related_runtime_artifacts`
- `founder_decision`

## Politique de promotion

Promouvoir quand:

- la reunion change la roadmap
- la reunion change l'architecture
- la reunion introduit ou durcit des garde-fous
- la reunion resserre les frontieres d'autonomie
- la reunion cree une politique reutilisable

Ne pas promouvoir quand:

- la reunion etait exploratoire puis abandonnee
- la reunion a fini en simple collecte d'information
- la sortie duplique une memoire existante

## Attentes de localisation

Le runtime doit garder:

- transcript
- sorties structurees d'angles
- synthese
- decision record

La memoire doit garder:

- decision record promu seulement s'il est durable

Discord doit garder:

- la version humaine compacte

## Forme visible par le fondateur

Le fondateur doit voir:

- sujet
- decision
- conditions
- prochaine action

Aucun schema brut ne doit etre necessaire pour comprendre.
