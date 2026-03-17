from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..database import CanonicalDatabase, dump_json
from ..models import (
    EvalCase,
    EvalCaseStatus,
    EvalRun,
    EvalRunStatus,
    EvalRunnerKind,
    TraceEntityKind,
    TraceRelationKind,
    new_id,
    to_jsonable,
)
from ..paths import PathPolicy, ProjectPaths
from ..runtime.journal import LocalJournal


class EvalService:
    def __init__(
        self,
        *,
        database: CanonicalDatabase,
        journal: LocalJournal,
        paths: ProjectPaths,
        path_policy: PathPolicy,
        repo_root: Path,
    ) -> None:
        self.database = database
        self.journal = journal
        self.paths = paths
        self.path_policy = path_policy
        self.repo_root = repo_root

    @staticmethod
    def _enum_value(value: Any) -> Any:
        return value.value if hasattr(value, "value") else value

    def seed_cases_from_candidates(
        self,
        *,
        suite_id: str,
        limit: int = 25,
        target_system: str | None = None,
    ) -> dict[str, Any]:
        clauses: list[str] = []
        params: list[Any] = []
        if target_system:
            clauses.append("target_system = ?")
            params.append(target_system)
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.database.fetchall(
            f"""
            SELECT *
            FROM eval_candidates
            {where_sql}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (*params, max(1, int(limit))),
        )
        created: list[dict[str, Any]] = []
        for row in rows:
            candidate_metadata = self._loads(row["metadata_json"], {})
            runner_kind = self._resolve_runner_kind(candidate_metadata)
            candidate_id = str(row["eval_candidate_id"])
            existing = self._fetch_case_by_idempotency_key(f"eval_candidate:{candidate_id}")
            if existing is not None:
                created.append(self._case_row_to_payload(existing))
                continue
            case = EvalCase(
                eval_case_id=new_id("eval_case"),
                suite_id=suite_id,
                scenario=str(row["scenario"]),
                target_system=str(row["target_system"]),
                expected_behavior=str(row["expected_behavior"]),
                runner_kind=runner_kind,
                status=EvalCaseStatus.ACTIVE,
                idempotency_key=f"eval_candidate:{candidate_id}",
                source_ids=self._loads(row["source_ids_json"], []),
                metadata={**candidate_metadata, "source_eval_candidate_id": candidate_id},
                provenance={
                    **self._provenance_payload(),
                    "source_eval_candidate_id": candidate_id,
                    "source_eval_candidate_created_at": str(row["created_at"]),
                },
            )
            self._persist_case(case)
            created.append(self.get_case(case.eval_case_id))
        return {"count": len(created), "suite_id": suite_id, "items": created}

    def create_case(
        self,
        *,
        suite_id: str,
        scenario: str,
        target_system: str,
        expected_behavior: str,
        runner_kind: EvalRunnerKind | str,
        idempotency_key: str | None = None,
        source_ids: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if idempotency_key:
            existing = self._fetch_case_by_idempotency_key(idempotency_key)
            if existing is not None:
                return self._case_row_to_payload(existing)
        case = EvalCase(
            eval_case_id=new_id("eval_case"),
            suite_id=suite_id,
            scenario=scenario,
            target_system=target_system,
            expected_behavior=expected_behavior,
            runner_kind=self._normalize_runner_kind(runner_kind),
            status=EvalCaseStatus.ACTIVE,
            idempotency_key=idempotency_key,
            source_ids=list(source_ids or []),
            metadata=dict(metadata or {}),
            provenance={**self._provenance_payload(), **dict(provenance or {})},
        )
        self._persist_case(case)
        return self.get_case(case.eval_case_id)

    def list_cases(
        self,
        *,
        suite_id: str | None = None,
        status: EvalCaseStatus | str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        clauses: list[str] = []
        params: list[Any] = []
        if suite_id:
            clauses.append("suite_id = ?")
            params.append(suite_id)
        if status:
            clauses.append("status = ?")
            params.append(str(status.value if isinstance(status, EvalCaseStatus) else status))
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.database.fetchall(
            f"""
            SELECT *
            FROM eval_cases
            {where_sql}
            ORDER BY updated_at DESC, created_at DESC
            LIMIT ?
            """,
            (*params, max(1, int(limit))),
        )
        items = [self._case_row_to_payload(row) for row in rows]
        return {"count": len(items), "items": items, "suite_id": suite_id, "status": str(status) if status else None}

    def get_case(self, eval_case_id: str) -> dict[str, Any]:
        row = self.database.fetchone(
            "SELECT * FROM eval_cases WHERE eval_case_id = ?",
            (eval_case_id,),
        )
        if row is None:
            raise KeyError(f"Unknown eval case: {eval_case_id}")
        return self._case_row_to_payload(row)

    def run_suite(
        self,
        *,
        suite_id: str,
        case_ids: list[str] | None = None,
        target_system: str | None = None,
        trigger_kind: str = "manual",
    ) -> dict[str, Any]:
        clauses = ["suite_id = ?", "status = ?"]
        params: list[Any] = [suite_id, EvalCaseStatus.ACTIVE.value]
        if target_system:
            clauses.append("target_system = ?")
            params.append(target_system)
        if case_ids:
            placeholders = ", ".join("?" for _ in case_ids)
            clauses.append(f"eval_case_id IN ({placeholders})")
            params.extend(case_ids)
        rows = self.database.fetchall(
            f"""
            SELECT *
            FROM eval_cases
            WHERE {' AND '.join(clauses)}
            ORDER BY created_at ASC
            """,
            tuple(params),
        )
        eval_run = EvalRun(
            eval_run_id=new_id("eval_run"),
            suite_id=suite_id,
            status=EvalRunStatus.RUNNING,
            trigger_kind=trigger_kind,
            case_ids=[str(row["eval_case_id"]) for row in rows],
            provenance=self._provenance_payload(),
        )
        self._persist_run(eval_run)
        results: list[dict[str, Any]] = []
        passed = 0
        failed = 0
        skipped = 0
        for row in rows:
            case_payload = self._case_row_to_payload(row)
            result = self._run_case(case_payload)
            results.append(result)
            verdict = str(result["verdict"])
            if verdict == "passed":
                passed += 1
            elif verdict == "failed":
                failed += 1
            else:
                skipped += 1
            self.database.record_trace_edge(
                parent_id=str(row["eval_case_id"]),
                parent_kind=TraceEntityKind.EVAL_CASE.value,
                child_id=eval_run.eval_run_id,
                child_kind=TraceEntityKind.EVAL_RUN.value,
                relation=TraceRelationKind.PRODUCED.value,
                metadata={"verdict": verdict},
            )
        if failed == 0 and passed > 0:
            final_status = EvalRunStatus.PASSED
        elif failed > 0 and passed == 0:
            final_status = EvalRunStatus.FAILED
        else:
            final_status = EvalRunStatus.MIXED
        updated_at = datetime.now(timezone.utc).isoformat()
        payload = {
            "eval_run_id": eval_run.eval_run_id,
            "suite_id": suite_id,
            "status": final_status.value,
            "trigger_kind": trigger_kind,
            "case_ids": eval_run.case_ids,
            "results": results,
            "passed_count": passed,
            "failed_count": failed,
            "skipped_count": skipped,
            "metadata": {"target_system": target_system},
            "provenance": eval_run.provenance,
            "created_at": eval_run.created_at,
            "updated_at": updated_at,
        }
        self._write_run_artifact(payload)
        self.database.execute(
            """
            UPDATE eval_runs
            SET status = ?, results_json = ?, passed_count = ?, failed_count = ?, skipped_count = ?,
                metadata_json = ?, provenance_json = ?, updated_at = ?
            WHERE eval_run_id = ?
            """,
            (
                final_status.value,
                dump_json(results),
                passed,
                failed,
                skipped,
                dump_json(payload["metadata"]),
                dump_json(payload["provenance"]),
                updated_at,
                eval_run.eval_run_id,
            ),
        )
        self.journal.append(
            "eval_suite_completed",
            "evals",
            {
                "eval_run_id": eval_run.eval_run_id,
                "suite_id": suite_id,
                "status": final_status.value,
                "passed_count": passed,
                "failed_count": failed,
                "skipped_count": skipped,
            },
        )
        return payload

    def _run_case(self, case: dict[str, Any]) -> dict[str, Any]:
        runner_kind = str(case["runner_kind"])
        metadata = dict(case.get("metadata") or {})
        if runner_kind == EvalRunnerKind.TRACE_REPORT.value:
            return self._run_trace_report_case(case, metadata)
        if runner_kind == EvalRunnerKind.DEAD_LETTER_STATUS.value:
            return self._run_dead_letter_case(case, metadata)
        if runner_kind == EvalRunnerKind.INCIDENT_STATUS.value:
            return self._run_incident_case(case, metadata)
        return {
            "eval_case_id": case["eval_case_id"],
            "scenario": case["scenario"],
            "runner_kind": runner_kind,
            "verdict": "skipped",
            "message": "manual review required",
            "evidence": {},
        }

    def _run_trace_report_case(self, case: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
        correlation_id = str(metadata.get("correlation_id") or "").strip()
        if not correlation_id:
            return {
                "eval_case_id": case["eval_case_id"],
                "scenario": case["scenario"],
                "runner_kind": EvalRunnerKind.TRACE_REPORT.value,
                "verdict": "failed",
                "message": "missing correlation_id",
                "evidence": {},
            }
        report = self.database.fetch_trace_report(correlation_id)
        counts = dict(report.get("summary", {}).get("counts") or {})
        expectations = dict(metadata.get("expectations") or {})
        failures: list[str] = []
        if bool(expectations.get("expect_found", True)) and not report.get("found"):
            failures.append("trace report not found")
        for field in (
            "channel_events",
            "gateway_dispatches",
            "mission_intents",
            "routing_decisions",
            "routing_traces",
            "mission_runs",
            "debug_replays",
            "dead_letters",
        ):
            min_key = f"min_{field}"
            if min_key in expectations and int(counts.get(field, 0)) < int(expectations[min_key]):
                failures.append(f"{field} < {expectations[min_key]}")
            max_key = f"max_{field}"
            if max_key in expectations and int(counts.get(field, 0)) > int(expectations[max_key]):
                failures.append(f"{field} > {expectations[max_key]}")
        return {
            "eval_case_id": case["eval_case_id"],
            "scenario": case["scenario"],
            "runner_kind": EvalRunnerKind.TRACE_REPORT.value,
            "verdict": "passed" if not failures else "failed",
            "message": "trace_report ok" if not failures else "; ".join(failures),
            "evidence": {"correlation_id": correlation_id, "counts": counts},
        }

    def _run_dead_letter_case(self, case: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
        row = None
        dead_letter_id = str(metadata.get("dead_letter_id") or "").strip()
        if dead_letter_id:
            row = self.database.fetchone(
                "SELECT * FROM dead_letter_records WHERE dead_letter_id = ?",
                (dead_letter_id,),
            )
        else:
            source_entity_kind = str(metadata.get("source_entity_kind") or "").strip()
            source_entity_id = str(metadata.get("source_entity_id") or "").strip()
            if source_entity_kind and source_entity_id:
                row = self.database.fetchone(
                    """
                    SELECT *
                    FROM dead_letter_records
                    WHERE source_entity_kind = ?
                      AND source_entity_id = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (source_entity_kind, source_entity_id),
                )
        if row is None:
            return {
                "eval_case_id": case["eval_case_id"],
                "scenario": case["scenario"],
                "runner_kind": EvalRunnerKind.DEAD_LETTER_STATUS.value,
                "verdict": "failed",
                "message": "dead letter not found",
                "evidence": {},
            }
        failures: list[str] = []
        expected_status = str(metadata.get("expected_status") or "").strip()
        if expected_status and str(row["status"]) != expected_status:
            failures.append(f"status != {expected_status}")
        if "expected_replayable" in metadata and bool(row["replayable"]) != bool(metadata.get("expected_replayable")):
            failures.append("replayable mismatch")
        return {
            "eval_case_id": case["eval_case_id"],
            "scenario": case["scenario"],
            "runner_kind": EvalRunnerKind.DEAD_LETTER_STATUS.value,
            "verdict": "passed" if not failures else "failed",
            "message": "dead_letter ok" if not failures else "; ".join(failures),
            "evidence": {
                "dead_letter_id": str(row["dead_letter_id"]),
                "status": str(row["status"]),
                "replayable": bool(row["replayable"]),
            },
        }

    def _run_incident_case(self, case: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
        incident_id = str(metadata.get("incident_id") or "").strip()
        if not incident_id:
            return {
                "eval_case_id": case["eval_case_id"],
                "scenario": case["scenario"],
                "runner_kind": EvalRunnerKind.INCIDENT_STATUS.value,
                "verdict": "failed",
                "message": "missing incident_id",
                "evidence": {},
            }
        row = self.database.fetchone(
            "SELECT * FROM incident_records WHERE incident_id = ?",
            (incident_id,),
        )
        if row is None:
            return {
                "eval_case_id": case["eval_case_id"],
                "scenario": case["scenario"],
                "runner_kind": EvalRunnerKind.INCIDENT_STATUS.value,
                "verdict": "failed",
                "message": "incident not found",
                "evidence": {},
            }
        failures: list[str] = []
        expected_status = str(metadata.get("expected_status") or "").strip()
        if expected_status and str(row["status"]) != expected_status:
            failures.append(f"status != {expected_status}")
        min_verification_refs = metadata.get("min_verification_refs")
        verification_refs = self._loads(row["verification_refs_json"], [])
        if min_verification_refs is not None and len(verification_refs) < int(min_verification_refs):
            failures.append(f"verification_refs < {int(min_verification_refs)}")
        return {
            "eval_case_id": case["eval_case_id"],
            "scenario": case["scenario"],
            "runner_kind": EvalRunnerKind.INCIDENT_STATUS.value,
            "verdict": "passed" if not failures else "failed",
            "message": "incident ok" if not failures else "; ".join(failures),
            "evidence": {"incident_id": incident_id, "status": str(row["status"]), "verification_refs": verification_refs},
        }

    def _persist_case(self, case: EvalCase) -> None:
        self.database.upsert(
            "eval_cases",
            {
                "eval_case_id": case.eval_case_id,
                "suite_id": case.suite_id,
                "scenario": case.scenario,
                "target_system": case.target_system,
                "expected_behavior": case.expected_behavior,
                "runner_kind": str(self._enum_value(case.runner_kind)),
                "status": str(self._enum_value(case.status)),
                "idempotency_key": case.idempotency_key,
                "source_ids_json": dump_json(case.source_ids),
                "metadata_json": dump_json(case.metadata),
                "provenance_json": dump_json(case.provenance),
                "created_at": case.created_at,
                "updated_at": case.updated_at,
            },
            conflict_columns="eval_case_id",
            immutable_columns=["created_at"],
        )
        self._write_case_artifact(to_jsonable(case))

    def _persist_run(self, run: EvalRun) -> None:
        self.database.upsert(
            "eval_runs",
            {
                "eval_run_id": run.eval_run_id,
                "suite_id": run.suite_id,
                "status": str(self._enum_value(run.status)),
                "trigger_kind": run.trigger_kind,
                "case_ids_json": dump_json(run.case_ids),
                "results_json": dump_json(run.results),
                "passed_count": run.passed_count,
                "failed_count": run.failed_count,
                "skipped_count": run.skipped_count,
                "metadata_json": dump_json(run.metadata),
                "provenance_json": dump_json(run.provenance),
                "created_at": run.created_at,
                "updated_at": run.updated_at,
            },
            conflict_columns="eval_run_id",
            immutable_columns=["created_at"],
        )

    def _write_case_artifact(self, payload: dict[str, Any]) -> None:
        folder = self.path_policy.ensure_allowed_write(self.paths.runtime_root / "evals" / "cases")
        folder.mkdir(parents=True, exist_ok=True)
        destination = self.path_policy.ensure_allowed_write(folder / f"{payload['eval_case_id']}.json")
        destination.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")

    def _write_run_artifact(self, payload: dict[str, Any]) -> None:
        folder = self.path_policy.ensure_allowed_write(self.paths.runtime_root / "evals" / "runs")
        folder.mkdir(parents=True, exist_ok=True)
        destination = self.path_policy.ensure_allowed_write(folder / f"{payload['eval_run_id']}.json")
        destination.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")

    def _case_row_to_payload(self, row) -> dict[str, Any]:
        return {
            "eval_case_id": str(row["eval_case_id"]),
            "suite_id": str(row["suite_id"]),
            "scenario": str(row["scenario"]),
            "target_system": str(row["target_system"]),
            "expected_behavior": str(row["expected_behavior"]),
            "runner_kind": str(row["runner_kind"]),
            "status": str(row["status"]),
            "idempotency_key": str(row["idempotency_key"]) if row["idempotency_key"] else None,
            "source_ids": self._loads(row["source_ids_json"], []),
            "metadata": self._loads(row["metadata_json"], {}),
            "provenance": self._loads(row["provenance_json"], {}),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }

    def _fetch_case_by_idempotency_key(self, idempotency_key: str):
        normalized = str(idempotency_key or "").strip()
        if not normalized:
            return None
        return self.database.fetchone(
            "SELECT * FROM eval_cases WHERE idempotency_key = ?",
            (normalized,),
        )

    @staticmethod
    def _loads(raw: Any, default: Any) -> Any:
        if raw in (None, ""):
            return default
        try:
            return json.loads(str(raw))
        except Exception:
            return default

    def _resolve_runner_kind(self, metadata: dict[str, Any]) -> str:
        explicit = str(metadata.get("runner_kind") or "").strip()
        if explicit:
            return self._normalize_runner_kind(explicit)
        if metadata.get("correlation_id"):
            return EvalRunnerKind.TRACE_REPORT.value
        if metadata.get("dead_letter_id") or (
            metadata.get("source_entity_kind") and metadata.get("source_entity_id")
        ):
            return EvalRunnerKind.DEAD_LETTER_STATUS.value
        if metadata.get("incident_id"):
            return EvalRunnerKind.INCIDENT_STATUS.value
        return EvalRunnerKind.MANUAL_REVIEW.value

    @staticmethod
    def _normalize_runner_kind(value: EvalRunnerKind | str) -> str:
        return EvalRunnerKind(value.value if isinstance(value, EvalRunnerKind) else str(value)).value

    def _provenance_payload(self) -> dict[str, Any]:
        return {
            "repo_branch": self._git_output("rev-parse", "--abbrev-ref", "HEAD") or None,
            "last_commit": self._git_output("log", "-1", "--pretty=format:%H") or None,
            "git_describe": self._git_output("describe", "--always", "--dirty") or None,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "runner_version": "pack3_v1",
        }

    def _git_output(self, *args: str) -> str:
        try:
            completed = subprocess.run(
                ["git", "-C", str(self.repo_root), *args],
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
        except Exception:
            return ""
        return completed.stdout.strip()
