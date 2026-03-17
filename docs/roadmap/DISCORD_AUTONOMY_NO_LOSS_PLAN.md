# Discord Autonomy No-Loss Plan

Ce document cadre le lot suivant apres `Persona V2 + Context Integrity + Prompt Ops`.

Objectif:

- parler librement sur `Discord`
- absorber messages longs, vocaux, transcriptions et plans complets
- ne rien perdre de critique
- garder une UX lisible, calme et explicite
- rester `single voice`

## Ce qui existe deja

Le socle actuel est deja solide sur plusieurs points:

- `channel_events` persiste le message canonique et le `raw_payload`
- `gateway_dispatch_results` persiste la decision et la reponse
- `operator deliveries` existe deja avec retries
- `Discord` est deja coupe en `single voice`
- les reponses longues du bot sont maintenant chunkees cote adapter
- un echec de livraison Discord peut deja produire un message d'erreur visible

Fichiers d'ancrage:

- `src/project_os_core/gateway/service.py`
- `src/project_os_core/gateway/openclaw_adapter.py`
- `src/project_os_core/api_runs/service.py`
- `integrations/openclaw/project-os-gateway-adapter/index.js`
- `src/project_os_core/database.py`

## Gaps reels observes dans le code

### 1. Le brut entrant n'est pas encore traite comme un artefact de premier rang

Aujourd'hui:

- `channel_events` garde le `raw_payload`
- mais le pipeline n'a pas encore de `raw input artifact` canonique pour texte massif, transcription longue, ou piece jointe volumineuse
- `openclaw_adapter.py` remonte surtout `mediaPath` pour les pieces jointes, pas un contrat riche de contenu exploitable

Risque:

- on peut garder une trace technique, mais pas encore un flux operable et clair pour re-traiter proprement un long input

### 2. Le systeme peut encore degrader par backlog

Aujourd'hui:

- `api_runs/service.py` limite les deliveries en attente
- au dela du seuil, certaines deliveries `runs_live` sont `skipped`

Risque:

- bonne hygiene anti-bruit
- mais pas encore garantie de `no-loss` sur tous les evenements visibles

### 3. La reponse visible reste trop `string-first`

Aujourd'hui:

- `OperatorReply.summary` est une string
- les deliveries transportent surtout `text`

Risque:

- pas de separation nette entre:
  - resume Discord
  - contenu long complet
  - artefact source
  - etat de progression

### 4. Les longs traitements n'ont pas encore un vrai protocole UX

Aujourd'hui:

- on peut repondre
- on peut echouer visiblement

Mais il manque encore:

- `message recu`
- `input long detecte`
- `analyse en cours`
- `resume pret`
- `artefact complet disponible`

### 5. La reprise n'est pas encore pensee comme experience produit

Il existe deja:

- dedup ingress
- retries de delivery

Mais pas encore un contrat complet:

- reprise apres crash au milieu d'un traitement long
- replay d'un input massif sans doubler la reponse visible
- etat terminal clair si la publication finale n'arrive jamais

## Cible produit

La bonne cible n'est pas `supprimer les limites`.

La bonne cible est:

- les limites externes existent
- `Project OS` les absorbe
- l'operateur comprend toujours ce qui se passe
- rien d'important n'est perdu
- la surface `Discord` reste simple

En pratique:

- `Discord` = cockpit conversationnel
- `Project OS.exe` = future surface locale pilotable principale
- `Project OS` = verite canonique + pipeline long contexte + artefacts

Corollaire:

- ce plan ne doit pas etre lu comme une exclusivite `Discord-only`
- la future app locale devra relire les etats, deliveries et activites produits ici
- la no-loss policy Discord reste valable meme quand l'app locale devient la surface fondatrice

## Contraintes externes confirmees

Cette roadmap n'est plus seulement `repo-first`.
Elle est maintenant alignee avec:

- la doc officielle `Discord`
- la doc `OpenClaw`

Constats externes a prendre comme durs:

- `Discord` limite `content` a `2000` caracteres par message
- `Discord` impose des `rate limits` et peut retourner `429` avec `retry_after`
- `Discord` propose `nonce` + `enforce_nonce` pour deduper proprement certains retries
- `Discord` supporte `allowed_mentions` et `message_reference`
- `OpenClaw` documente:
  - `typing indicators`
  - `streaming/chunking`
  - `paragraph-first chunking`
  - `retry policy`
  - `history/debounce`
  - `thread bindings`
  - `context compaction`

Conclusion:

- on ne supprimera pas les limites de plateforme
- on doit construire une UX qui les absorbe sans perte silencieuse

## Parametres cibles recommandes

Ces parametres melangent:

- contraintes officielles
- ergonomie Discord
- robustesse d'operation

### Transport Discord

- `hard_content_limit = 2000`
- `safe_chunk_target = 1800-1900`
- `chunk_mode = paragraph_first -> newline -> whitespace`
- `max_lines_per_message = 15-17`
- `use_nonce = true`
- `enforce_nonce = true`
- `allowed_mentions.parse = []`
- `allowed_mentions.replied_user = false`
- `fail_if_not_exists = false` sur les replies
- `suppress_notifications = true` pour:
  - chunks `2..N`
  - messages de progression

### Retry direct-send

- `attempts = 3`
- `base_delay_ms = 500`
- `max_delay_ms = 30000`
- `jitter = 0.1`
- sur `429`, respecter `retry_after`
- sur erreur terminale, produire:
  - fallback visible Discord
  - puis dead-letter si necessaire

### Ingress humain

- `discord_text_debounce_ms = 1500` pour rafales de petits messages texte
- `attachments/audio bypass debounce = true`
- `first_visible_ack_slo = 1-2s`

### Long-input trigger

Basculer en mode async `artifact-first` si:

- pave texte massif
- transcription vocale
- document / piece jointe riche
- sortie estimee trop longue pour Discord

## Spec `Artifact-First`

## But

`Discord` doit rester la surface de conversation.
Le contenu long, reviewable, durable et re-jouable doit vivre dans des artefacts.

## Response manifest canonique

Ajouter une structure logique du type:

- `delivery_mode`
- `discord_summary`
- `discord_next_action`
- `full_artifact_id`
- `review_artifact_id`
- `segments_artifact_id`
- `decision_extract_artifact_id`
- `action_extract_artifact_id`
- `source_artifact_id`

## Modes de sortie

### 1. `inline_text`

Usage:

- chat simple
- question courte
- reponse courte

Sortie:

- un message Discord compact

### 2. `thread_chunked_text`

Usage:

- reponse moyenne
- encore lisible en quelques messages

Sortie:

- plusieurs messages Discord chunkes
- toujours lisibles sans ouvrir un artefact externe

### 3. `artifact_summary`

Usage:

- plan long
- audit
- synthese longue
- transcription
- review structuree

Sortie:

- resume Discord court
- document complet durable
- eventuellement un second artefact `decision/action extract`

### 4. `artifact_required`

Usage:

- quand Discord ne doit surtout pas porter le complet
- quand la relecture doit etre stable
- quand le contenu doit etre archivable

Sortie:

- message Discord
- document joint ou artefact reference
- pas de mur de texte

## Regle `texte vs PDF`

## Rester en texte Discord si

- la reponse est courte
- l'operateur a besoin d'une reponse immediate, pas d'un livrable
- le contenu n'a pas besoin de mise en page stable

## Chunker en texte si

- la reponse depasse un message
- mais reste conversationnelle
- et peut etre lue sans fatigue en `2-4` messages max

## Basculer en `PDF` si

- c'est un livrable de revue
- la structure doit etre stable
- il y a:
  - sections
  - decision points
  - tableau comparatif
  - checklist
  - plan detaille
- le contenu doit etre facile a verifier visuellement

## Basculer en `Markdown` si

- tu veux aussi pouvoir le retravailler facilement
- le contenu est surtout technique / versionnable
- la stabilite visuelle est moins importante qu'un format editable

## Regle pratique

- `plan / audit / synthese longue / compte-rendu vocal`:
  - `resume Discord + document complet`
- `conseil / arbitrage court / rappel de contraintes`:
  - `texte Discord`

## Messages Discord cibles

## Ack immediat

Format:

- `Message recu.`
- `Input long detecte, je prepare un resume et un document complet.`

Quand:

- traitement long
- transcript
- document

## Progression

Format:

- `Analyse en cours.`
- `Resume pret. J'assemble le document complet.`

Regles:

- sobre
- pas de theatre
- pas de spam

## Resultat simple

Format:

- `Voici la reponse.`
- `Prochain pas recommande: ...`

## Resultat long `artifact-first`

Format:

- `Plan complet pret.`
- `Resume court: ...`
- `A verifier en priorite:`
  - point 1
  - point 2
  - point 3
- `Document complet joint / disponible en artefact.`

## Erreur visible

Format:

- `Le resultat est calcule, mais sa publication Discord a echoue.`
- `Le contenu complet reste stocke.`
- `Je peux rejouer la livraison.`

## Cas d'usage cibles

## Plans

Sortie attendue:

- `resume Discord`
- `PDF` si plan a relire / valider
- `Markdown` en plus si on veut le retravailler

Contenu complet:

- objectifs
- hypotheses
- ordre des packs
- risques
- criteres d'acceptation

## Audits

Sortie attendue:

- `resume Discord tres court`
- `document complet` quasi systematique

Contenu complet:

- findings
- severite
- preuves
- impacts
- correctifs recommandes

## Syntheses longues

Sortie attendue:

- resume Discord
- document complet si la synthese depasse la conversation confortable

## Comptes-rendus vocaux / transcriptions

Sortie attendue:

- ack immediat
- traitement async
- `resume Discord`
- `document complet`
- extracts:
  - decisions
  - actions
  - questions ouvertes
  - blocages

Si dispo:

- horodatage
- hints locuteurs

## No-loss garanti par conception

Pour viser `zero silent loss`, chaque long traitement doit avoir:

- `source artifact` brut
- `working artifact` segmente/normalise
- `review artifact` final
- `delivery record`
- `dead-letter record` si publication finale echoue

Et chaque etape doit etre:

- idempotente
- rejouable
- auditable

## Architecture executable par packs

## Architecture a ajouter

## 1. Lossless Ingress Journal

Tout input potentiellement lourd doit devenir un objet durable avant tout traitement profond.

Ajouter:

- `ingress artifact` canonique pour:
  - texte long
  - transcription
  - piece jointe
  - message multi-parties
- hash de contenu
- taille
- type de media
- provenance
- lien vers `channel_event_id`

Effet:

- on peut re-traiter
- on peut resumer sans perdre le brut
- on peut auditer ce qui a vraiment ete recu

## 2. Long Input Classifier

Avant de router, classifier:

- `court`
- `long`
- `tres long`
- `audio/transcription`
- `attachment-heavy`

Le routeur ne doit pas traiter pareil:

- un message chat simple
- une transcription de 30 minutes
- un dump de plan

Le classifieur doit produire:

- mode de traitement
- budget de contexte
- besoin de segmentation
- besoin d'artefact complet

## 3. Async Long-Context Pipeline

Pour les inputs longs, passer en pipeline et non en appel unique.

Phases:

1. reception et persistence du brut
2. extraction / normalisation
3. segmentation
4. resume hierarchique
5. extraction:
   - decisions
   - actions
   - questions ouvertes
   - risques
6. reponse finale utilisateur

Important:

- chaque phase doit etre relancable sans tout refaire
- chaque phase doit ecrire son etat

## 4. Artifact-First Output

Pour viser `no-loss`, la sortie ne doit plus etre seulement une string Discord.

Ajouter un `response manifest`:

- `discord_summary`
- `full_artifact_id`
- `segments_artifact_id`
- `decision_extract_artifact_id`
- `action_extract_artifact_id`
- `delivery_mode`

Principe:

- Discord recoit un message humain, lisible, compact
- le contenu long complet vit dans un artefact durable

Donc:

- pas de perte
- pas de mur de texte brutal
- meilleure lisibilite

## 5. Visible State Protocol

Un traitement long doit avoir un protocole UX canonique.

Etats minimaux:

- `recu`
- `input long detecte`
- `traitement en cours`
- `resume pret`
- `sortie complete disponible`
- `echec`

Message UX attendu:

- court
- comprehensible pour non-dev
- pas de jargon infra
- toujours avec prochain etat ou prochain pas

## 6. Delivery Guarantee Ladder

Tous les messages n'ont pas le meme niveau critique.

Ajouter une echelle:

- `best_effort`
- `important`
- `must_notify`
- `must_persist`

Exemples:

- petite reponse de chat: `best_effort`
- clarification requise: `must_notify`
- resultat d'analyse longue: `must_persist`

Effet:

- on arrete de traiter toutes les sorties comme de simples textes interchangeables

## 7. Dead-Letter + Recovery

Si une livraison finale echoue plusieurs fois:

- ne pas juste rester `pending` ou `failed`
- produire une `dead-letter record`
- la relier au thread
- rendre le probleme visible dans Discord et dans les audits

Ajouter:

- dead-letter queue logique
- commande de replay
- reprise idempotente
- message utilisateur du type:
  - `Le resultat complet est calcule et stocke, mais sa publication Discord a echoue.`

## 8. Backlog Without Loss

Aujourd'hui certaines deliveries peuvent etre `skipped` si backlog.

Pour l'autonomie integrale:

- ne jamais skipper silencieusement une sortie importante
- convertir les surplus en:
  - resume agrege
  - digest
  - artefact de lot

Il faut donc distinguer:

- bruit jetable
- information utile differable
- information a ne jamais perdre

## 9. Conversation Compaction

Pour parler librement longtemps sans casser le contexte:

- compaction du thread recent
- resume glissant
- preservation des contraintes dures
- preservation des decisions
- preservation des questions ouvertes

Le contexte injecte doit devenir:

- plus petit
- plus stable
- plus explicable

et pas juste plus gros.

## 10. Attachment and Transcript Specialization

Les vocaux transcrits et pieces jointes ne doivent pas etre traites comme du texte brut standard.

Ajouter:

- type `transcript`
- type `document`
- type `media`
- extracteurs specialises

Pour une transcription:

- horodatage si dispo
- speaker hints si dispo
- plan de synthese long-form
- extraction des TODO / decisions / blocages

## 11. Operator UX Rules

Une belle experience utilisateur demande des regles simples:

- jamais silence radio apres un message lourd
- jamais promesse d'action non executee
- jamais mur de texte si un resume suffit
- jamais perte silencieuse
- toujours une reponse visible meme en cas d'echec
- toujours un chemin vers le contenu complet

## 12. SLOs and Audits

Il faut mesurer l'autonomie, pas juste la ressentir.

Ajouter des indicateurs:

- taux de delivery visible
- taux de delivery avec fallback
- taux de messages trop longs
- taux de retries
- taux de dead-letter
- temps median vers premier ack
- temps median vers resultat final
- taux de pertes confirmees

Objectif:

- `zero silent loss`
- `zero confusing silence`

### Pack A - Lossless Input

- ingress artifacts
- classify long inputs
- stockage durable du brut
- tests message long / transcript long / piece jointe

Fichiers probables:

- `src/project_os_core/models.py`
- `src/project_os_core/database.py`
- `src/project_os_core/gateway/openclaw_adapter.py`
- `src/project_os_core/gateway/service.py`
- `src/project_os_core/gateway/promotion.py`
- `tests/unit/test_openclaw_live.py`
- `tests/unit/test_gateway_and_orchestration.py`

### Pack B - Long Context Workflow

- pipeline async par phases
- segmentation
- resume hierarchique
- extraction decisions/actions/questions

Etat implemente:

- workflow long-context persiste par `channel_event`
- phases explicites `receive -> normalize -> segment -> summarize -> extract -> ready`
- artefacts `long_context_workflow` et `long_context_segments`
- digest compact injecte dans le prompt inline a la place du brut massif
- extraction heuristique de `decisions / actions / questions`

Fichiers probables:

- `src/project_os_core/gateway/context_builder.py`
- `src/project_os_core/gateway/service.py`
- `src/project_os_core/api_runs/service.py`
- `src/project_os_core/memory/curator.py`
- `tests/unit/test_gateway_context_builder.py`

### Pack C - Artifact-First Output

- response manifest
- artefacts longs
- resume Discord + lien logique vers complet
- chunking conserve comme filet final

Etat implemente:

- `OperatorReply` embarque maintenant un `response_manifest` canonique
- les longues reponses inline basculent en `artifact_summary`
- le gateway persiste un `response_manifest` JSON, un `response_review_markdown` et des extracts `decisions/actions`
- Discord recoit un resume compact et le document complet est joignable comme piece `markdown`
- le chunking texte reste le filet final quand le resume depasse un seul message
- l'adapter Discord sait joindre un artefact local a la livraison immediate et au polling des operator deliveries

Fichiers probables:

- `src/project_os_core/models.py`
- `src/project_os_core/gateway/service.py`
- `integrations/openclaw/project-os-gateway-adapter/index.js`
- `scripts/` de rendu doc si PDF retenu
- `tests/unit/test_gateway_prompt_ops.py`
- `tests/unit/test_openclaw_live.py`

### Pack D - Delivery Guarantees

- criticalite des sorties
- dead-letter
- replay
- backlog sans perte pour sorties importantes

Etat implemente:

- `delivery_guarantee` explicite: `best_effort / important / must_notify / must_persist`
- plus de `skip` silencieux quand le backlog depasse la limite douce
- dead-letter JSON durable sur echec terminal de delivery
- replay manuel via `project-os api-runs requeue-operator-delivery --delivery-id ...`
- poll adapter Discord qui laisse un delivery en `pending` si la target est absente au lieu de le perdre

Fichiers probables:

- `src/project_os_core/models.py`
- `src/project_os_core/config.py`
- `src/project_os_core/api_runs/service.py`
- `integrations/openclaw/project-os-gateway-adapter/index.js`
- `tests/unit/test_scheduler_service.py`
- `tests/unit/test_openclaw_live.py`

### Pack E - UX and Observability

- etats visibles
- dashboard de santé des deliveries
- audits `no-loss`
- golden tests UX Discord

Etat implemente:

- le monitor snapshot expose maintenant `operator_delivery_health` et `no_loss_audit`
- chaque run visible porte un etat `operator_delivery_no_loss_state`
- le dashboard rend l'audit `no-loss`, la sante delivery et les replies Discord recentes avec leur `delivery_mode`
- les replays OpenClaw remontent aussi `response_delivery_mode`, presence du manifest et nombre de pieces jointes
- la doc operateur Discord/OpenClaw est posee dans `docs/integrations/OPENCLAW_DISCORD_OPERATIONS_UX.md`

Fichiers probables:

- `src/project_os_core/api_runs/dashboard.py`
- `src/project_os_core/gateway/openclaw_live.py`
- `docs/integrations/OPENCLAW_DISCORD_OPERATIONS_UX.md`
- `integrations/openclaw/project-os-gateway-adapter/README.md`

## Definition of done

On peut parler d'autonomie operationnelle quand:

- un pave texte massif ne casse pas le flux
- une transcription longue est recue, stockee, analysee et resumee
- le contenu complet reste retrouvable
- Discord ne laisse jamais l'operateur dans le vide
- les echecs sont visibles et actionnables
- les gros plans et audits basculent automatiquement en mode `artifact-first`
- le format `PDF` est choisi quand une revue stable est meilleure qu'un mur de texte Discord
- le backlog degrade en digest, pas en perte silencieuse
- les replays sont idempotents
- les audits peuvent prouver `ce qui a ete recu`, `ce qui a ete compris`, `ce qui a ete publie`

## Regle de verite

La cible n'est pas:

- `pas de limite`

La cible est:

- `pas de perte silencieuse`
- `pas d'etat incomprehensible`
- `pas de rupture de confiance`

## Sources externes retenues

- `Discord Message Resource`
- `Discord Rate Limits`
- `OpenClaw Discord docs`
- `OpenClaw Messages`
- `OpenClaw Streaming and Chunking`
- `OpenClaw Retry Policy`
- `OpenClaw Plugins / context engine`
- `OpenClaw Typing Indicators`
