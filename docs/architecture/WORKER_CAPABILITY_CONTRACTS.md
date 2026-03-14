# Worker Capability Contracts

Ce document definit les contrats de capacite de chaque worker de Project OS.

## Principe

Chaque worker est un executeur specialise. Il recoit une requete structuree et retourne un resultat structure.
Aucun worker ne contourne le Mission Router. Aucun worker ne prend de decision business.

## Architecture commune

```
Mission Router -> Worker Selection -> Worker Execution -> Result
                                                       -> Evidence capture
```

Chaque worker expose:

```python
class WorkerContract:
    worker_kind: str              # identifiant unique
    capabilities: list[str]       # liste de capacites
    required_secrets: list[str]   # secrets necessaires

    def execute(self, request: WorkerRequest) -> WorkerResult
    def health_check(self) -> bool
    def capture_state(self) -> dict  # pour recovery
```

## Worker: Windows (Desktop)

### Identite

- `worker_kind`: `"windows"`
- Status: **Lot 6 — pas encore implemente**
- Stack: UFO (reference), pywinauto (actions structurees), OmniParser (perception visuelle)

### Capacites

| Capacite | Description |
|----------|-------------|
| `desktop_windows` | Interaction avec les fenetres Windows (clic, saisie, navigation) |
| `editor_control` | Controle d'editeurs (UEFN, VS Code, etc.) |
| `screenshot_validation` | Capture et validation visuelle de l'etat ecran |

### Entrees

```python
WorkerRequest(
    task_id: str,
    action: str,           # "click", "type", "screenshot", "find_element", "sequence"
    target: str,           # selecteur UIA, coordonnees, ou description naturelle
    parameters: dict,      # parametres specifiques a l'action
    timeout_seconds: int,  # max 60s par action
)
```

### Sorties

```python
WorkerResult(
    success: bool,
    action_taken: str,
    screenshot_path: str | None,    # capture apres action
    elements_found: list[dict],     # elements UIA detectes
    error: str | None,
)
```

### Erreurs specifiques

| Erreur | Strategie |
|--------|-----------|
| Element introuvable | OmniParser fallback → screenshot + detection visuelle |
| Fenetre pas au premier plan | Focus automatique + retry |
| Application crashee | Capturer l'etat, notifier, ne pas retry |
| Timeout d'action | Annuler, capturer screenshot, escalader |

### Securite

- jamais d'execution de commandes shell via le worker
- jamais d'acces aux secrets via l'interface desktop
- toutes les actions sont loguees avec screenshot

## Worker: Browser

### Identite

- `worker_kind`: `"browser"`
- Status: **Lot 7 — pas encore implemente**
- Stack: Stagehand (execution web fiable)

### Capacites

| Capacite | Description |
|----------|-------------|
| `web_navigation` | Navigation entre pages, URLs, onglets |
| `form_fill` | Remplissage de formulaires web |
| `dom_actions` | Interactions avec le DOM (clic, scroll, selection) |

### Entrees

```python
WorkerRequest(
    task_id: str,
    action: str,           # "navigate", "click", "fill", "screenshot", "extract"
    target: str,           # URL, selecteur CSS/XPath, ou description naturelle
    parameters: dict,      # headers, cookies, form_data, etc.
    timeout_seconds: int,  # max 30s par action
)
```

### Sorties

```python
WorkerResult(
    success: bool,
    action_taken: str,
    page_url: str,
    page_title: str,
    screenshot_path: str | None,
    extracted_data: dict | None,    # donnees extraites
    error: str | None,
)
```

### Erreurs specifiques

| Erreur | Strategie |
|--------|-----------|
| Page non chargee | Retry avec timeout augmente |
| Element introuvable | Attendre + retry, puis screenshot fallback |
| CAPTCHA | Escalader au fondateur |
| SSL/certificat | Bloquer, ne jamais ignorer |

### Securite

- jamais de navigation vers des URLs non autorisees
- pas de telechargement automatique de fichiers
- pas de soumission de formulaires contenant des secrets
- toutes les navigations loguees

## Worker: Media

### Identite

- `worker_kind`: `"media"`
- Status: **pas encore dans le roadmap**
- Stack: a definir

### Capacites prevues

| Capacite | Description |
|----------|-------------|
| `image_generation` | Generation d'images via API |
| `image_analysis` | Analyse d'images (OCR, classification) |
| `video_processing` | Traitement video basique (a definir) |

### Notes

Ce worker n'a aucun code, aucune config, aucune reference dans le codebase actuel.
Il devra etre specifie quand le besoin media sera clarifie.

## Worker: Deterministic

### Identite

- `worker_kind`: `"deterministic"`
- Status: **actif** (utilise pour les operations sans API)

### Capacites

| Capacite | Description |
|----------|-------------|
| `file_operations` | Lecture/ecriture de fichiers locaux |
| `json_transform` | Transformation de structures JSON |
| `db_query` | Requetes SQLite en lecture |

### Entrees/Sorties

Standard `WorkerRequest` / `WorkerResult`.

## Profil: UEFN

### Identite

- `profile_name`: `"uefn"`
- Status: **Lot 9 — pas encore implemente**

### Configuration

```python
ProfileCapability(
    profile_name="uefn",
    capability_names=["desktop_windows", "editor_control", "screenshot_validation"],
    allowed_workers=["windows", "browser", "deterministic"],
    required_secrets=["OPENAI_API_KEY"],
)
```

### Workflow specifique

1. Ouvrir UEFN via le worker Windows
2. Naviguer dans l'editeur via desktop_windows
3. Executer des actions UEFN via editor_control
4. Valider visuellement via screenshot_validation
5. Documenter le resultat dans la base runtime

### Dependances

- Worker Windows fonctionnel
- OmniParser pour la perception de l'interface UEFN
- Modeles de reference pour les elements UI de UEFN

## Selection de worker

Le Mission Router selectionne le worker via `_choose_worker()`:

```python
# Mots-cles → worker
"browser", "web", "mail", "site", "form"  → browser
"windows", "desktop", "app", "uefn"       → windows
autres                                     → deterministic (defaut)
```

Le profil actif peut restreindre les workers autorises.

## Regles communes

1. chaque worker capture une preuve (screenshot, log, resultat)
2. chaque worker respecte un timeout strict
3. aucun worker ne modifie la DB canonique directement
4. le Mission Router est le seul point d'entree
5. les erreurs sont structurees et classifiees (retryable ou non)

## References

- `src/project_os_core/models.py` (WorkerRequest, WorkerResult, ProfileCapability)
- `src/project_os_core/router/policy.py` (profils et workers autorises)
- `src/project_os_core/router/service.py` (_choose_worker)
- `docs/knowledge/EXTERNAL_STACK_REFERENCE.md`
- `docs/roadmap/BUILD_STATUS_CHECKLIST.md`
