from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import RoutingDecision, RunLifecycleEvent


@dataclass(frozen=True)
class VisibleCaseRule:
    case_id: str
    show: tuple[str, ...]
    hide: tuple[str, ...]
    confirm: tuple[str, ...]


class StandardReplyPolicy:
    """Canonical visibility rules for standard operator-facing replies."""

    _VISIBLE_CASES: tuple[VisibleCaseRule, ...] = (
        VisibleCaseRule(
            case_id="question_normale",
            show=("reponse utile", "presence utile", "reponse courte par defaut"),
            hide=("provider", "api", "routing", "pipeline", "taxonomie interne"),
            confirm=(),
        ),
        VisibleCaseRule(
            case_id="approval_reel",
            show=("objectif", "livrable attendu", "cout utile", "temps utile"),
            hide=("route_reason", "pipeline interne", "taxonomie inutile"),
            confirm=("go/stop",),
        ),
        VisibleCaseRule(
            case_id="changement_de_modele",
            show=("modele cible", "cout estime", "raison utile"),
            hide=("routing interne", "pipeline interne"),
            confirm=("confirmation explicite",),
        ),
        VisibleCaseRule(
            case_id="deep_research_explicite",
            show=("modes deep research", "cout estime", "temps estime"),
            hide=("pipeline interne non necessaire",),
            confirm=("confirmation explicite",),
        ),
        VisibleCaseRule(
            case_id="reponse_moyenne",
            show=("contenu lisible dans discord", "presence utile", "artefact si necessaire"),
            hide=("delivery internals", "metadata technique"),
            confirm=(),
        ),
        VisibleCaseRule(
            case_id="incident_delivery",
            show=("incident humain", "prochain pas", "etat de reprise"),
            hide=("trace brute adapter", "payload technique"),
            confirm=(),
        ),
    )

    @classmethod
    def visible_case_matrix(cls) -> tuple[VisibleCaseRule, ...]:
        return cls._VISIBLE_CASES

    @classmethod
    def decorate_inline_summary(cls, summary: str, decision: RoutingDecision) -> str:
        rendered = summary.strip()
        label = cls._local_inline_label(decision)
        if not label:
            return rendered
        if rendered.lower().startswith(label.lower()):
            return rendered
        return f"{label} {rendered}"

    @staticmethod
    def render_duplicate_ingress_reply() -> str:
        return "Message en double ignore. Rien n'est relance."

    @classmethod
    def render_standard_route_reply(
        cls,
        *,
        allowed: bool,
        worker_label: str | None = None,
        blocked_reason: str | None = None,
        research_note: str | None = None,
    ) -> str:
        if allowed:
            summary = f"Je lance sur {worker_label or 'le worker cible'}."
        else:
            summary = f"Je ne peux pas lancer pour l'instant: {blocked_reason or 'blocage inconnu'}."
        return cls._append_suffix(summary, research_note)

    @staticmethod
    def summarize_standard_runtime_approval(action_result: dict[str, Any]) -> str:
        objective = str(action_result.get("objective") or "cette operation")
        estimated_cost = float(action_result.get("estimated_cost_eur") or 0.0)
        if action_result.get("run_launched"):
            if estimated_cost > 0:
                return f"{objective}: validation prise en compte. Operation lancee (~{estimated_cost:.2f} EUR)."
            return f"{objective}: validation prise en compte. Operation lancee."
        error = str(action_result.get("error") or "").strip()
        if error:
            return f"{objective}: validation prise en compte, mais l'operation reste bloquee: {error}"
        return f"{objective}: validation prise en compte, mais l'operation reste bloquee."

    @staticmethod
    def summarize_standard_runtime_rejection(action_result: dict[str, Any]) -> str:
        objective = str(action_result.get("objective") or "cette operation")
        return f"{objective}: validation refusee. Rien n'est lance."

    @classmethod
    def summarize_standard_session_action(cls, *, action: str, action_result: dict[str, Any]) -> str:
        if action == "approve_contract":
            branch = str(action_result.get("branch_name") or "ce lot")
            if action_result.get("run_launched"):
                return f"{branch}: contrat valide. Je lance."
            return f"{branch}: contrat valide. Le lancement reste en attente."
        if action == "reject_contract":
            branch = str(action_result.get("branch_name") or "ce lot")
            return f"{branch}: contrat refuse. Rien n'est lance."
        if action == "answer_clarification":
            branch = str(action_result.get("branch_name") or "ce lot")
            return f"{branch}: clarification prise en compte. J'applique."
        if action == "reject_clarification":
            branch = str(action_result.get("branch_name") or "ce lot")
            return f"{branch}: clarification refusee. Je laisse le lot en pause."
        if action == "guardian_override":
            branch = str(action_result.get("branch_name") or "ce lot")
            return f"{branch}: validation forcee prise en compte. Je relance."
        if action == "status_request":
            snapshot = action_result.get("snapshot") or {}
            active_runs = len(snapshot.get("active_runs") or [])
            pending_clarifications = len(snapshot.get("pending_clarifications") or [])
            pending_contracts = len(snapshot.get("pending_contracts") or [])
            daily_spend = float(snapshot.get("daily_spend_eur") or 0.0)
            daily_limit = float(snapshot.get("daily_budget_limit_eur") or 0.0)
            return (
                "En ce moment: "
                f"{cls._count_label(active_runs, 'run actif', 'runs actifs')}, "
                f"{cls._count_label(pending_clarifications, 'clarification en attente', 'clarifications en attente')}, "
                f"{cls._count_label(pending_contracts, 'contrat en attente', 'contrats en attente')}. "
                f"Budget {daily_spend:.2f}/{daily_limit:.2f} EUR. "
                "Pour le detail operatoire, ouvre Project OS.exe > Home / Session / Runs / Discord."
            )
        status = str(action_result.get("status") or "").strip().lower()
        if status in {"missing_target", "unhandled", "blocked"}:
            return "Je ne peux pas aller plus loin pour l'instant."
        return "C'est pris en compte."

    @staticmethod
    def render_operator_delivery_text(event: RunLifecycleEvent) -> str:
        lines = [str(event.title or "Mise a jour Project OS").strip() or "Mise a jour Project OS"]
        summary = str(event.summary or "").strip()
        if summary and summary.lower() != lines[0].lower():
            lines.append(summary)
        branch_name = str(event.branch_name or "").strip()
        if branch_name:
            lines.append(f"Branche: {branch_name}")
        if event.blocking_question:
            lines.append(f"Question: {event.blocking_question}")
        if event.recommended_action:
            lines.append(f"Prochain pas: {event.recommended_action}")
        if event.requires_reapproval:
            lines.append("Confirmation requise avant relance.")
        return "\n".join(lines)

    @staticmethod
    def _local_inline_label(decision: RoutingDecision) -> str | None:
        if decision.model_route.provider != "local":
            return None
        if decision.route_reason == "s3_local_route":
            return "[Local S3 / Ollama]"
        if decision.route_reason == "operator_forced_local_route":
            return "[Local / Ollama]"
        return None

    @staticmethod
    def _append_suffix(summary: str, suffix: str | None) -> str:
        clean_summary = summary.strip()
        clean_suffix = str(suffix or "").strip()
        if not clean_suffix:
            return clean_summary
        return f"{clean_summary} {clean_suffix}".strip()

    @staticmethod
    def _count_label(count: int, singular: str, plural: str) -> str:
        label = singular if count == 1 else plural
        return f"{count} {label}"
