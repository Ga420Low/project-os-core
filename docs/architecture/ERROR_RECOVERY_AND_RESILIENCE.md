# Error Recovery and Resilience

Ce document definit les strategies de recuperation d'erreur et de resilience de Project OS.

## Principe

Le systeme doit:

1. detecter les erreurs rapidement
2. recuperer automatiquement quand c'est possible
3. escalader a l'humain quand c'est necessaire
4. ne jamais corrompre l'etat canonique

## Categories d'erreurs

### Erreurs API (OpenAI, Claude)

| Erreur | Strategie |
|--------|-----------|
| Rate limit (429) | Backoff exponentiel: 2s, 4s, 8s, 16s, max 3 retries |
| Timeout | Retry avec le meme prompt, max 2 retries |
| Quota depasse | Notifier le fondateur sur Discord, pause les runs non urgents |
| Reponse malformee | Retry 1 fois, puis marquer `failed` avec raison |
| Modele indisponible | Attendre 5 min, retry, puis notifier si persistant |

Regle: jamais plus de 3 retries sur la meme requete. Apres 3 echecs, le run passe en `failed`.

### Erreurs de parsing (structured output)

| Erreur | Strategie |
|--------|-----------|
| JSON invalide | Tenter extraction partielle, sinon retry avec prompt de correction |
| Champs manquants | Accepter si non-critique, sinon retry avec schema rappele |
| Valeurs hors domaine | Valider et rejeter, retry avec contraintes explicites |

### Erreurs SQLite

| Erreur | Strategie |
|--------|-----------|
| Database locked | Retry apres 100ms, max 5 retries |
| Corruption detectee | Alerter immediatement, basculer sur backup, ne pas ecrire |
| Disk full | Alerter le fondateur, purger le cache, pause les runs |
| Transaction echouee | Rollback complet, jamais d'etat partiel |

Regle: toute ecriture multi-row utilise une transaction explicite.
En cas d'echec, rollback complet — jamais d'etat a moitie ecrit.

### Erreurs reseau (Discord, webhooks)

| Erreur | Strategie |
|--------|-----------|
| Discord down | Queue locale, envoyer au retour |
| Webhook timeout | Retry 2 fois, puis queue pour envoi differe |
| Message trop long | Tronquer intelligemment, garder l'essentiel |

### Erreurs workers (Windows, Browser)

| Erreur | Strategie |
|--------|-----------|
| Worker crash | Capture l'etat, restart le worker, retry l'action |
| UI element introuvable | Screenshot + OmniParser fallback, puis escalade |
| Timeout d'action | Annuler l'action, capturer l'etat, escalader |

## Pattern de retry

```python
# Backoff exponentiel avec jitter
import random, time

def retry_with_backoff(fn, max_retries=3, base_delay=2.0):
    for attempt in range(max_retries):
        try:
            return fn()
        except RetryableError as e:
            if attempt == max_retries - 1:
                raise
            delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
            time.sleep(delay)
```

Regle: seules les erreurs `RetryableError` sont retentees.
Les erreurs de logique, de validation ou de securite ne sont jamais retentees.

## Etats de run et transitions d'erreur

```
pending -> executing -> completed
                    \-> failed (+ retry possible)
                    \-> clarification_required (attend reponse)
                    \-> blocked (erreur non recuperable)
```

### Clarification required

Le run detecte une ambiguite ou contradiction:

1. passe en `clarification_required`
2. produit un rapport structure
3. envoie une question au fondateur via Claude traducteur
4. attend la reponse (avec `can_wait_hours` et `fallback_if_no_answer`)
5. reprend sur le contrat amende

### Failed avec auto-retry

1. le run echoue pour une raison retryable
2. le systeme attend le delai de backoff
3. retry automatique (max 3 fois)
4. pendant les retries: ne pas notifier le fondateur (bruit)
5. si tous les retries echouent: notifier avec raison simple

### Blocked

Erreur non recuperable automatiquement:

1. capturer l'etat complet (context pack, prompt, erreur)
2. notifier le fondateur avec raison simple
3. proposer des options (retry manuel, abandon, modification)
4. ne pas tenter de recuperer automatiquement

## Self-healing

### Detection de boucle

Si le meme run (meme branche, meme mode) echoue 3+ fois en 2h:

1. marquer la branche comme `loop_detected`
2. notifier le fondateur
3. ne pas relancer automatiquement
4. attendre une decision humaine ou un changement de strategie

### Health check

Le systeme verifie periodiquement:

| Check | Frequence | Action si echec |
|-------|-----------|-----------------|
| SQLite accessible | Chaque operation | Alerter immediatement |
| Disk space >1 Go | Toutes les heures | Purger cache + alerter |
| API keys valides | Au demarrage | Bloquer les runs, alerter |
| Budget restant | Avant chaque run | Guardian bloque si depasse |

### Recovery automatique

| Situation | Action |
|-----------|--------|
| Process crash | Le monitor relance au prochain cycle |
| DB WAL trop gros | Checkpoint automatique |
| Cache expire | Reconstruction paresseuse a la demande |
| Session orpheline | Nettoyage apres timeout (1h) |

## Escalade

### Quand escalader a l'humain

- apres 3 retries echoues sur la meme erreur
- boucle detectee (3+ echecs en 2h)
- budget depasse a 80%+
- erreur de securite (P0)
- corruption de donnees detectee

### Quand ne PAS escalader

- retry en cours (attendre le resultat)
- erreur temporaire resolue automatiquement
- budget <70% (pas actionable)
- run demarre normalement (bruit)

## Principe de non-corruption

Regles absolues:

1. jamais d'ecriture partielle dans la DB
2. jamais de suppression de donnees sans backup
3. jamais de modification d'un run `completed` (immutable)
4. jamais de retry sur une erreur de logique
5. en cas de doute, preferer l'arret propre a la tentative de reparation

## References

- `docs/architecture/QUALITY_STANDARDS.md`
- `docs/integrations/API_LEAD_AGENT_V1.md`
- `docs/decisions/0013-dual-model-operating-model.md`
- `docs/workflow/LANGUAGE_LEVELS.md` (regles de filtrage Discord)
