from __future__ import annotations

import json
from typing import Any

from ..artifacts import validate_artifact_pointer, write_json_artifact
from ..database import CanonicalDatabase, dump_json
from ..models import (
    ActionEvidence,
    ApprovalRecord,
    ApprovalStatus,
    MemoryTier,
    RuntimeState,
    RuntimeVerdict,
    SessionState,
    new_id,
    to_jsonable,
)
from ..paths import PathPolicy, ProjectPaths
from .journal import LocalJournal


class RuntimeStore:
    def __init__(
        self,
        database: CanonicalDatabase,
        paths: ProjectPaths,
        path_policy: PathPolicy,
        journal: LocalJournal,
    ):
        self.database = database
        self.paths = paths
        self.path_policy = path_policy
        self.journal = journal

    def open_session(
        self,
        *,
        profile_name: str,
        owner: str,
        status: str = "ready",
        metadata: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> SessionState:
        session = SessionState(
            session_id=session_id or new_id("session"),
            profile_name=profile_name,
            owner=owner,
            status=status,
            metadata=metadata or {},
        )
        self.database.upsert(
            "session_states",
            {
                "session_id": session.session_id,
                "profile_name": session.profile_name,
                "owner": session.owner,
                "status": session.status,
                "payload_json": dump_json(session.metadata),
                "created_at": session.created_at,
                "updated_at": session.updated_at,
            },
            conflict_columns="session_id",
            immutable_columns=["created_at"],
        )
        self.journal.append(
            "session_opened",
            "runtime",
            {"session_id": session.session_id, "profile_name": profile_name},
        )
        return session

    def get_session(self, session_id: str) -> SessionState:
        row = self.database.fetchone("SELECT * FROM session_states WHERE session_id = ?", (session_id,))
        if row is None:
            raise KeyError(f"Unknown session_id: {session_id}")
        return SessionState(
            session_id=str(row["session_id"]),
            profile_name=str(row["profile_name"]),
            owner=str(row["owner"]),
            status=str(row["status"]),
            metadata=json.loads(row["payload_json"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def record_runtime_state(self, state: RuntimeState) -> RuntimeState:
        self.get_session(state.session_id)
        self.database.execute(
            """
            INSERT INTO runtime_states(
                runtime_state_id, session_id, verdict, active_profile, mission_run_id,
                status_summary, blockers_json, metadata_json, captured_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                state.runtime_state_id,
                state.session_id,
                state.verdict.value,
                state.active_profile,
                state.mission_run_id,
                state.status_summary,
                dump_json(state.blockers),
                dump_json(state.metadata),
                state.captured_at,
            ),
        )
        self.journal.append(
            "runtime_state_recorded",
            "runtime",
            {
                "session_id": state.session_id,
                "runtime_state_id": state.runtime_state_id,
                "verdict": state.verdict.value,
            },
        )
        return state

    def latest_runtime_state(self) -> RuntimeState | None:
        row = self.database.fetchone(
            """
            SELECT * FROM runtime_states
            ORDER BY captured_at DESC
            LIMIT 1
            """
        )
        if row is None:
            return None
        return RuntimeState(
            runtime_state_id=str(row["runtime_state_id"]),
            session_id=str(row["session_id"]),
            verdict=RuntimeVerdict(str(row["verdict"])),
            active_profile=row["active_profile"],
            mission_run_id=row["mission_run_id"],
            status_summary=row["status_summary"],
            blockers=json.loads(row["blockers_json"]),
            metadata=json.loads(row["metadata_json"]),
            captured_at=str(row["captured_at"]),
        )

    def create_approval(
        self,
        *,
        requested_by: str,
        risk_tier: str,
        reason: str,
        mission_run_id: str | None = None,
        expires_at: str | None = None,
        metadata: dict[str, Any] | None = None,
        approval_id: str | None = None,
    ) -> ApprovalRecord:
        approval = ApprovalRecord(
            approval_id=approval_id or new_id("approval"),
            requested_by=requested_by,
            risk_tier=risk_tier,
            reason=reason,
            mission_run_id=mission_run_id,
            expires_at=expires_at,
            metadata=metadata or {},
        )
        self.database.upsert(
            "approval_records",
            {
                "approval_id": approval.approval_id,
                "mission_run_id": approval.mission_run_id,
                "requested_by": approval.requested_by,
                "risk_tier": approval.risk_tier,
                "reason": approval.reason,
                "status": approval.status.value,
                "expires_at": approval.expires_at,
                "payload_json": dump_json(approval.metadata),
                "created_at": approval.created_at,
                "updated_at": approval.updated_at,
            },
            conflict_columns="approval_id",
            immutable_columns=["created_at"],
        )
        self.journal.append(
            "approval_created",
            "runtime",
            {
                "approval_id": approval.approval_id,
                "risk_tier": approval.risk_tier,
                "requested_by": approval.requested_by,
            },
        )
        return approval

    def list_pending_approvals(self, mission_run_id: str | None = None) -> list[ApprovalRecord]:
        if mission_run_id:
            rows = self.database.fetchall(
                """
                SELECT * FROM approval_records
                WHERE status = ? AND mission_run_id = ?
                ORDER BY created_at DESC
                """,
                (ApprovalStatus.PENDING.value, mission_run_id),
            )
        else:
            rows = self.database.fetchall(
                """
                SELECT * FROM approval_records
                WHERE status = ?
                ORDER BY created_at DESC
                """,
                (ApprovalStatus.PENDING.value,),
            )
        return [
            ApprovalRecord(
                approval_id=str(row["approval_id"]),
                requested_by=str(row["requested_by"]),
                risk_tier=str(row["risk_tier"]),
                reason=str(row["reason"]),
                status=ApprovalStatus(str(row["status"])),
                mission_run_id=row["mission_run_id"],
                expires_at=row["expires_at"],
                metadata=json.loads(row["payload_json"]),
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
            )
            for row in rows
        ]

    def resolve_approval(
        self,
        approval_id: str,
        status: ApprovalStatus,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.database.execute(
            """
            UPDATE approval_records
            SET status = ?, payload_json = ?, updated_at = CURRENT_TIMESTAMP
            WHERE approval_id = ?
            """,
            (
                status.value,
                dump_json(metadata or {}),
                approval_id,
            ),
        )
        self.journal.append(
            "approval_resolved",
            "runtime",
            {"approval_id": approval_id, "status": status.value},
        )

    def record_action_evidence(
        self,
        *,
        session_id: str,
        action_name: str,
        success: bool,
        summary: str | None = None,
        result_code: str | None = None,
        failure_reason: str | None = None,
        policy_verdict: str | None = None,
        pre_state: dict[str, Any] | None = None,
        post_state: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ActionEvidence:
        self.get_session(session_id)
        evidence = ActionEvidence(
            evidence_id=new_id("evidence"),
            session_id=session_id,
            action_name=action_name,
            success=success,
            summary=summary,
            result_code=result_code,
            failure_reason=failure_reason,
            policy_verdict=policy_verdict,
            pre_state=pre_state or {},
            post_state=post_state or {},
            metadata=metadata or {},
        )
        artifact = write_json_artifact(
            paths=self.paths,
            path_policy=self.path_policy,
            owner_id=evidence.evidence_id,
            artifact_kind="evidence",
            storage_tier=MemoryTier.HOT,
            payload=to_jsonable(evidence),
        )
        evidence.artifacts.append(artifact)
        evidence.artifact_count = len(evidence.artifacts)
        validate_artifact_pointer(artifact, self.path_policy)
        self.database.execute(
            """
            INSERT INTO action_evidences(
                evidence_id, session_id, action_name, success, summary, result_code, failure_reason,
                policy_verdict, artifact_count,
                pre_state_json, post_state_json, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evidence.evidence_id,
                evidence.session_id,
                evidence.action_name,
                1 if evidence.success else 0,
                evidence.summary,
                evidence.result_code,
                evidence.failure_reason,
                evidence.policy_verdict,
                evidence.artifact_count,
                dump_json(evidence.pre_state),
                dump_json(evidence.post_state),
                dump_json(evidence.metadata),
                evidence.created_at,
            ),
        )
        self.database.execute(
            """
            INSERT INTO artifact_pointers(
                artifact_id, owner_type, owner_id, artifact_kind, storage_tier, path,
                checksum_sha256, size_bytes, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact.artifact_id,
                "action_evidence",
                evidence.evidence_id,
                artifact.artifact_kind,
                artifact.storage_tier.value,
                artifact.path,
                artifact.checksum_sha256,
                artifact.size_bytes,
                artifact.created_at,
            ),
        )
        self.journal.append(
            "action_evidence_recorded",
            "runtime",
            {
                "evidence_id": evidence.evidence_id,
                "session_id": session_id,
                "action_name": action_name,
                "success": success,
            },
        )
        return evidence
