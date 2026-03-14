from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from ..database import CanonicalDatabase
from ..models import ApprovalStatus, ApiRunStatus, MissionStatus, RunContractStatus, utc_now_iso

if TYPE_CHECKING:
    from ..api_runs.service import ApiRunService


APPROVE_PATTERNS = frozenset(
    {
        "go",
        "vas y",
        "envoie",
        "lance",
        "c est bon",
        "ouais",
        "ok",
        "oui",
        "allez",
        "fonce",
        "send",
        "let s go",
        "yep",
        "valide",
        "on lance",
        "fais le",
    }
)
REJECT_PATTERNS = frozenset(
    {
        "stop",
        "non",
        "bof",
        "pas maintenant",
        "annule",
        "cancel",
        "nah",
        "attend",
        "attends",
        "pas encore",
        "pas la",
        "laisse tomber",
    }
)
FORCE_PATTERNS = frozenset(
    {
        "force",
        "quand meme",
        "override",
        "je sais",
        "tant pis",
        "on s en fout",
        "yolo",
        "go quand meme",
    }
)
STATUS_PATTERNS = frozenset(
    {
        "status",
        "quoi de neuf",
        "ou on en est",
        "ca donne quoi",
        "resume",
        "point rapide",
    }
)


@dataclass(slots=True)
class SessionSnapshot:
    active_runs: list[dict[str, Any]] = field(default_factory=list)
    pending_clarifications: list[dict[str, Any]] = field(default_factory=list)
    pending_contracts: list[dict[str, Any]] = field(default_factory=list)
    pending_approvals: list[dict[str, Any]] = field(default_factory=list)
    pending_deliveries: int = 0
    daily_spend_eur: float = 0.0
    daily_budget_limit_eur: float = 0.0
    last_run_completed_at: str | None = None
    last_founder_message_at: str | None = None
    active_missions: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class ResolvedIntent:
    action: str
    target_id: str | None
    confidence: float
    raw_message: str
    metadata: dict[str, Any] = field(default_factory=dict)


class PersistentSessionState:
    """Memoire continue du systeme, alimentee uniquement par SQLite."""

    def __init__(self, *, database: CanonicalDatabase, api_runs: ApiRunService) -> None:
        self.database = database
        self.api_runs = api_runs

    def load(self) -> SessionSnapshot:
        """Charge l'etat complet du systeme depuis SQLite sans appel API."""

        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        active_run_rows = self.database.fetchall(
            """
            SELECT
                r.run_id,
                q.mode,
                q.branch_name,
                COALESCE(r.created_at, q.created_at) AS started_at
            FROM api_run_results r
            JOIN api_run_requests q ON q.run_request_id = r.run_request_id
            WHERE r.status = ?
            ORDER BY started_at DESC
            """,
            (ApiRunStatus.RUNNING.value,),
        )
        clarification_rows = self.database.fetchall(
            """
            SELECT
                c.report_id,
                c.run_id,
                c.question_for_founder,
                c.created_at,
                c.metadata_json,
                q.branch_name,
                q.mode
            FROM clarification_reports c
            JOIN api_run_results r ON r.run_id = c.run_id
            JOIN api_run_requests q ON q.run_request_id = r.run_request_id
            WHERE r.status = ?
            ORDER BY c.created_at DESC
            """,
            (ApiRunStatus.CLARIFICATION_REQUIRED.value,),
        )
        contract_rows = self.database.fetchall(
            """
            SELECT contract_id, objective, estimated_cost_eur, created_at, branch_name, mode, metadata_json
            FROM api_run_contracts
            WHERE status = ?
            ORDER BY created_at DESC
            """,
            (RunContractStatus.PREPARED.value,),
        )
        approval_rows = self.database.fetchall(
            """
            SELECT approval_id, reason, risk_tier, payload_json, created_at
            FROM approval_records
            WHERE status = ?
            ORDER BY created_at DESC
            """,
            (ApprovalStatus.PENDING.value,),
        )
        delivery_row = self.database.fetchone(
            """
            SELECT COUNT(*) AS pending_deliveries
            FROM api_run_operator_deliveries
            WHERE status = ?
            """,
            ("pending",),
        )
        spend_row = self.database.fetchone(
            """
            SELECT COALESCE(SUM(estimated_cost_eur), 0.0) AS daily_spend
            FROM api_run_results
            WHERE created_at >= ?
              AND status != ?
            """,
            (today_start, ApiRunStatus.FAILED.value),
        )
        completed_row = self.database.fetchone(
            """
            SELECT MAX(updated_at) AS last_run_completed_at
            FROM api_run_results
            WHERE status IN (?, ?)
            """,
            (ApiRunStatus.COMPLETED.value, ApiRunStatus.REVIEWED.value),
        )
        founder_row = self.database.fetchone(
            """
            SELECT MAX(created_at) AS last_founder_message_at
            FROM channel_events
            """,
        )
        active_mission_rows = self.database.fetchall(
            """
            SELECT mission_run_id, objective, status, created_at
            FROM mission_runs
            WHERE status IN (?, ?, ?, ?)
            ORDER BY created_at DESC
            """,
            (
                MissionStatus.QUEUED.value,
                MissionStatus.RUNNING.value,
                MissionStatus.PAUSED.value,
                MissionStatus.WAITING_APPROVAL.value,
            ),
        )

        pending_clarifications: list[dict[str, Any]] = []
        for row in clarification_rows:
            metadata = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
            if metadata.get("resolved_at"):
                continue
            pending_clarifications.append(
                {
                    "report_id": str(row["report_id"]),
                    "run_id": str(row["run_id"]),
                    "question": str(row["question_for_founder"]),
                    "created_at": str(row["created_at"]),
                    "branch_name": str(row["branch_name"]),
                    "mode": str(row["mode"]),
                    "metadata": metadata,
                }
            )

        snapshot = SessionSnapshot(
            active_runs=[
                {
                    "run_id": str(row["run_id"]),
                    "mode": str(row["mode"]),
                    "branch_name": str(row["branch_name"]),
                    "started_at": str(row["started_at"]),
                }
                for row in active_run_rows
            ],
            pending_clarifications=pending_clarifications,
            pending_contracts=[
                {
                    "contract_id": str(row["contract_id"]),
                    "objective": str(row["objective"]),
                    "estimated_cost": float(row["estimated_cost_eur"]),
                    "created_at": str(row["created_at"]),
                    "branch_name": str(row["branch_name"]),
                    "mode": str(row["mode"]),
                    "metadata": json.loads(row["metadata_json"]) if row["metadata_json"] else {},
                }
                for row in contract_rows
            ],
            pending_approvals=[
                {
                    "approval_id": str(row["approval_id"]),
                    "action_name": str((json.loads(row["payload_json"]) if row["payload_json"] else {}).get("action_name") or row["reason"]),
                    "risk_class": str(row["risk_tier"]),
                    "created_at": str(row["created_at"]),
                }
                for row in approval_rows
            ],
            pending_deliveries=int(delivery_row["pending_deliveries"]) if delivery_row else 0,
            daily_spend_eur=float(spend_row["daily_spend"]) if spend_row else 0.0,
            daily_budget_limit_eur=float(getattr(self.api_runs.execution_policy, "daily_budget_limit_eur", 5.0)),
            last_run_completed_at=str(completed_row["last_run_completed_at"]) if completed_row and completed_row["last_run_completed_at"] else None,
            last_founder_message_at=str(founder_row["last_founder_message_at"]) if founder_row and founder_row["last_founder_message_at"] else None,
            active_missions=[
                {
                    "mission_run_id": str(row["mission_run_id"]),
                    "objective": str(row["objective"]),
                    "status": str(row["status"]),
                    "created_at": str(row["created_at"]),
                }
                for row in active_mission_rows
            ],
        )
        self.api_runs.logger.log(
            "INFO",
            "session_snapshot_loaded",
            active_runs=len(snapshot.active_runs),
            pending_clarifications=len(snapshot.pending_clarifications),
            pending_contracts=len(snapshot.pending_contracts),
            pending_approvals=len(snapshot.pending_approvals),
            pending_deliveries=snapshot.pending_deliveries,
            daily_spend_eur=snapshot.daily_spend_eur,
            daily_budget_limit_eur=snapshot.daily_budget_limit_eur,
        )
        return snapshot

    def resolve_intent(self, message_text: str, *, snapshot: SessionSnapshot | None = None) -> ResolvedIntent | None:
        """Resout une intention simple par pattern matching et contexte, sans appel API."""

        normalized_text = self._normalize_text(message_text)
        snapshot = snapshot or self.load()
        matches_force = self._matches_force(normalized_text)
        matches_status = self._matches_status(normalized_text)
        matches_approve = self._matches_approve(normalized_text)
        matches_reject = self._matches_reject(normalized_text)

        total_pending = len(snapshot.pending_contracts) + len(snapshot.pending_clarifications)
        is_simple_message = (matches_approve or matches_reject) and not matches_force and not matches_status
        if is_simple_message and total_pending > 1:
            self.api_runs.logger.log(
                "INFO",
                "session_intent_ambiguous",
                message_text=message_text,
                pending_contracts=len(snapshot.pending_contracts),
                pending_clarifications=len(snapshot.pending_clarifications),
                reason="multiple_pending_items_with_simple_message",
            )
            return None

        resolved: ResolvedIntent | None = None
        if len(snapshot.pending_clarifications) == 1 and matches_approve:
            clarification = snapshot.pending_clarifications[0]
            resolved = ResolvedIntent(
                action="answer_clarification",
                target_id=str(clarification["report_id"]),
                confidence=0.95,
                raw_message=message_text,
                metadata={"answer": "approved"},
            )
        elif len(snapshot.pending_contracts) == 1 and matches_approve:
            contract = snapshot.pending_contracts[0]
            resolved = ResolvedIntent(
                action="approve_contract",
                target_id=str(contract["contract_id"]),
                confidence=0.95,
                raw_message=message_text,
                metadata={},
            )
        else:
            guardian_clarification = next(
                (
                    item
                    for item in snapshot.pending_clarifications
                    if bool(item.get("metadata", {}).get("guardian_blocking_reason"))
                ),
                None,
            )
            if guardian_clarification is not None and matches_force:
                resolved = ResolvedIntent(
                    action="guardian_override",
                    target_id=str(guardian_clarification["report_id"]),
                    confidence=0.90,
                    raw_message=message_text,
                    metadata={"override": True},
                )
            elif matches_status:
                resolved = ResolvedIntent(
                    action="status_request",
                    target_id=None,
                    confidence=0.95,
                    raw_message=message_text,
                    metadata={},
                )
            elif matches_reject:
                if len(snapshot.pending_contracts) == 1 and len(snapshot.pending_clarifications) == 0:
                    contract = snapshot.pending_contracts[0]
                    resolved = ResolvedIntent(
                        action="reject_contract",
                        target_id=str(contract["contract_id"]),
                        confidence=0.90,
                        raw_message=message_text,
                        metadata={},
                    )
                elif len(snapshot.pending_clarifications) == 1 and len(snapshot.pending_contracts) == 0:
                    clarification = snapshot.pending_clarifications[0]
                    resolved = ResolvedIntent(
                        action="reject_clarification",
                        target_id=str(clarification["report_id"]),
                        confidence=0.90,
                        raw_message=message_text,
                        metadata={"answer": "rejected"},
                    )

        if resolved is None or resolved.confidence < 0.70:
            self.api_runs.logger.log(
                "INFO",
                "session_intent_escalated",
                message_text=message_text,
                normalized_text=normalized_text,
                pending_contracts=len(snapshot.pending_contracts),
                pending_clarifications=len(snapshot.pending_clarifications),
                pending_approvals=len(snapshot.pending_approvals),
            )
            return None

        self.api_runs.logger.log(
            "INFO",
            "session_intent_resolved",
            action=resolved.action,
            target_id=resolved.target_id,
            confidence=resolved.confidence,
            message_text=message_text,
        )
        return resolved

    def build_context_brief(self, *, snapshot: SessionSnapshot | None = None) -> str:
        """Construit un brief compact du contexte de session pour une eventuelle escalade."""

        snapshot = snapshot or self.load()
        lines = [
            "Persistent Session State",
            f"Active runs: {len(snapshot.active_runs)}",
        ]
        for item in snapshot.active_runs[:3]:
            lines.append(f"- {item['mode']} on {item['branch_name']} since {item['started_at']}")
        lines.append(f"Pending clarifications: {len(snapshot.pending_clarifications)}")
        for item in snapshot.pending_clarifications[:3]:
            lines.append(f"- {item['branch_name']}: {item['question']}")
        lines.append(f"Pending contracts: {len(snapshot.pending_contracts)}")
        for item in snapshot.pending_contracts[:3]:
            lines.append(f"- {item['branch_name']}: {item['objective']} ({item['estimated_cost']:.2f} EUR)")
        lines.append(f"Pending approvals: {len(snapshot.pending_approvals)}")
        lines.append(f"Pending deliveries: {snapshot.pending_deliveries}")
        lines.append(f"Daily budget: {snapshot.daily_spend_eur:.2f} / {snapshot.daily_budget_limit_eur:.2f} EUR")
        lines.append(f"Last run completed at: {snapshot.last_run_completed_at or 'none'}")
        lines.append(f"Last founder message at: {snapshot.last_founder_message_at or 'none'}")
        lines.append(f"Active missions: {len(snapshot.active_missions)}")
        for item in snapshot.active_missions[:3]:
            lines.append(f"- {item['objective']} [{item['status']}]")
        return "\n".join(lines)

    @staticmethod
    def _normalize_text(text: str) -> str:
        lowered = text.strip().lower().replace("'", " ").replace("’", " ")
        normalized = unicodedata.normalize("NFKD", lowered)
        ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
        cleaned = re.sub(r"[^a-z0-9\s]", " ", ascii_text)
        return re.sub(r"\s+", " ", cleaned).strip()

    def _matches_approve(self, text: str) -> bool:
        return self._matches_any(text, APPROVE_PATTERNS)

    def _matches_reject(self, text: str) -> bool:
        return self._matches_any(text, REJECT_PATTERNS)

    def _matches_force(self, text: str) -> bool:
        return self._matches_any(text, FORCE_PATTERNS)

    def _matches_status(self, text: str) -> bool:
        return self._matches_any(text, STATUS_PATTERNS)

    @staticmethod
    def _matches_any(text: str, patterns: frozenset[str]) -> bool:
        if not text:
            return False
        for pattern in patterns:
            if " " in pattern and pattern in text:
                return True
            if re.search(rf"(?<![a-z0-9]){re.escape(pattern)}(?![a-z0-9])", text):
                return True
        return False
