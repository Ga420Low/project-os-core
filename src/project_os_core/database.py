from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


CURRENT_SCHEMA_VERSION = "4"


class CanonicalDatabase:
    def __init__(self, db_path: Path, vector_dimensions: int = 64):
        self.db_path = db_path
        self.vector_dimensions = vector_dimensions
        self._connection: sqlite3.Connection | None = None
        self.vector_enabled = False

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            self._connection = self._connect()
        return self._connection

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.db_path), check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA foreign_keys=ON")
        self._enable_sqlite_vec(connection)
        self._migrate(connection)
        return connection

    def _enable_sqlite_vec(self, connection: sqlite3.Connection) -> None:
        try:
            import sqlite_vec

            connection.enable_load_extension(True)
            sqlite_vec.load(connection)
            connection.enable_load_extension(False)
            self.vector_enabled = True
        except Exception:
            self.vector_enabled = False

    def _migrate(self, connection: sqlite3.Connection) -> None:
        with connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS journal_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS session_states (
                    session_id TEXT PRIMARY KEY,
                    profile_name TEXT NOT NULL,
                    owner TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS runtime_states (
                    runtime_state_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    verdict TEXT NOT NULL,
                    active_profile TEXT,
                    mission_run_id TEXT,
                    status_summary TEXT,
                    blockers_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    captured_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS approval_records (
                    approval_id TEXT PRIMARY KEY,
                    mission_run_id TEXT,
                    requested_by TEXT NOT NULL,
                    risk_tier TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    status TEXT NOT NULL,
                    expires_at TEXT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS action_evidences (
                    evidence_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    action_name TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    summary TEXT,
                    result_code TEXT,
                    failure_reason TEXT,
                    policy_verdict TEXT,
                    artifact_count INTEGER NOT NULL DEFAULT 0,
                    pre_state_json TEXT NOT NULL,
                    post_state_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS artifact_pointers (
                    artifact_id TEXT PRIMARY KEY,
                    owner_type TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    artifact_kind TEXT NOT NULL,
                    storage_tier TEXT NOT NULL,
                    path TEXT NOT NULL,
                    checksum_sha256 TEXT,
                    size_bytes INTEGER,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS memory_records (
                    memory_id TEXT PRIMARY KEY,
                    openmemory_id TEXT,
                    user_id TEXT NOT NULL,
                    project_id TEXT,
                    mission_id TEXT,
                    content TEXT NOT NULL,
                    memory_type TEXT NOT NULL,
                    tier TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    archived_artifact_path TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS memory_embedding_map (
                    memory_id TEXT PRIMARY KEY,
                    vector_rowid INTEGER UNIQUE NOT NULL
                );

                CREATE TABLE IF NOT EXISTS mission_intents (
                    intent_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    target_profile TEXT,
                    requested_worker TEXT,
                    requested_risk_class TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS mission_runs (
                    mission_run_id TEXT PRIMARY KEY,
                    intent_id TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    profile_name TEXT,
                    status TEXT NOT NULL,
                    execution_class TEXT,
                    routing_decision_id TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS routing_decisions (
                    decision_id TEXT PRIMARY KEY,
                    intent_id TEXT NOT NULL,
                    mission_run_id TEXT,
                    execution_class TEXT NOT NULL,
                    risk_class TEXT NOT NULL,
                    allowed INTEGER NOT NULL,
                    chosen_worker TEXT,
                    model_route_json TEXT NOT NULL,
                    approval_gate_json TEXT NOT NULL,
                    budget_state_json TEXT NOT NULL,
                    route_reason TEXT NOT NULL,
                    blocked_reasons_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS routing_decision_traces (
                    trace_id TEXT PRIMARY KEY,
                    decision_id TEXT NOT NULL,
                    runtime_state_id TEXT,
                    inputs_json TEXT NOT NULL,
                    outputs_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS bootstrap_states (
                    bootstrap_state_id TEXT PRIMARY KEY,
                    strict_ready INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    failures_json TEXT NOT NULL,
                    warnings_json TEXT NOT NULL,
                    checks_json TEXT NOT NULL,
                    roots_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS health_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    overall_status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    path TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS channel_events (
                    event_id TEXT PRIMARY KEY,
                    surface TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    message_kind TEXT,
                    thread_ref_json TEXT NOT NULL,
                    message_json TEXT NOT NULL,
                    raw_payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS conversation_memory_candidates (
                    candidate_id TEXT PRIMARY KEY,
                    source_event_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    classification TEXT NOT NULL,
                    thread_ref_json TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    tier TEXT NOT NULL,
                    should_promote INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS promotion_decisions (
                    promotion_decision_id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    memory_type TEXT,
                    tier TEXT,
                    memory_id TEXT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS gateway_dispatch_results (
                    dispatch_id TEXT PRIMARY KEY,
                    channel_event_id TEXT NOT NULL,
                    envelope_id TEXT NOT NULL,
                    intent_id TEXT NOT NULL,
                    decision_id TEXT,
                    mission_run_id TEXT,
                    memory_candidate_id TEXT,
                    promotion_decision_id TEXT,
                    promoted_memory_ids_json TEXT NOT NULL,
                    reply_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS graph_states (
                    graph_state_id TEXT PRIMARY KEY,
                    mission_run_id TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    active_role TEXT NOT NULL,
                    status TEXT NOT NULL,
                    role_sequence_json TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS role_handoffs (
                    handoff_id TEXT PRIMARY KEY,
                    mission_run_id TEXT NOT NULL,
                    from_role TEXT,
                    to_role TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS execution_checkpoints (
                    execution_checkpoint_id TEXT PRIMARY KEY,
                    mission_run_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    label TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS retry_decisions (
                    retry_decision_id TEXT PRIMARY KEY,
                    mission_run_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    attempt_number INTEGER NOT NULL,
                    retry_allowed INTEGER NOT NULL,
                    next_reasoning_effort TEXT,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS mission_outcomes (
                    outcome_id TEXT PRIMARY KEY,
                    mission_run_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    produced_artifact_ids_json TEXT NOT NULL,
                    next_steps_json TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS routing_assignments (
                    assignment_id TEXT PRIMARY KEY,
                    mission_run_id TEXT NOT NULL,
                    decision_id TEXT NOT NULL,
                    worker_kind TEXT NOT NULL,
                    execution_class TEXT NOT NULL,
                    model_route_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS execution_tickets (
                    ticket_id TEXT PRIMARY KEY,
                    mission_run_id TEXT NOT NULL,
                    assignment_id TEXT NOT NULL,
                    worker_kind TEXT NOT NULL,
                    action_name TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    policy_verdict TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS worker_dispatch_envelopes (
                    dispatch_id TEXT PRIMARY KEY,
                    ticket_id TEXT NOT NULL,
                    worker_request_json TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS context_packs (
                    context_pack_id TEXT PRIMARY KEY,
                    mode TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    branch_name TEXT NOT NULL,
                    target_profile TEXT,
                    source_refs_json TEXT NOT NULL,
                    repo_state_json TEXT NOT NULL,
                    runtime_facts_json TEXT NOT NULL,
                    constraints_json TEXT NOT NULL,
                    acceptance_criteria_json TEXT NOT NULL,
                    skill_tags_json TEXT NOT NULL,
                    artifact_path TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS mega_prompt_templates (
                    prompt_template_id TEXT PRIMARY KEY,
                    context_pack_id TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    agent_identity TEXT NOT NULL,
                    skill_tags_json TEXT NOT NULL,
                    output_contract_json TEXT NOT NULL,
                    rendered_prompt TEXT NOT NULL,
                    model TEXT NOT NULL,
                    reasoning_effort TEXT NOT NULL,
                    artifact_path TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS api_run_requests (
                    run_request_id TEXT PRIMARY KEY,
                    context_pack_id TEXT NOT NULL,
                    prompt_template_id TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    branch_name TEXT NOT NULL,
                    target_profile TEXT,
                    skill_tags_json TEXT NOT NULL,
                    expected_outputs_json TEXT NOT NULL,
                    coding_lane TEXT NOT NULL,
                    desktop_lane TEXT NOT NULL,
                    status TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS api_run_results (
                    run_id TEXT PRIMARY KEY,
                    run_request_id TEXT NOT NULL,
                    model TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    raw_output_path TEXT,
                    prompt_artifact_path TEXT,
                    result_artifact_path TEXT,
                    structured_output_json TEXT NOT NULL,
                    estimated_cost_eur REAL NOT NULL,
                    usage_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS api_run_reviews (
                    review_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    verdict TEXT NOT NULL,
                    reviewer TEXT NOT NULL,
                    findings_json TEXT NOT NULL,
                    accepted_changes_json TEXT NOT NULL,
                    followup_actions_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS learning_signals (
                    signal_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    source_ids_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS decision_records (
                    decision_record_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    source_run_id TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS loop_signals (
                    loop_signal_id TEXT PRIMARY KEY,
                    repeated_pattern TEXT NOT NULL,
                    impacted_area TEXT NOT NULL,
                    recommended_reset TEXT NOT NULL,
                    source_ids_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS refresh_recommendations (
                    refresh_recommendation_id TEXT PRIMARY KEY,
                    cause TEXT NOT NULL,
                    context_to_reload_json TEXT NOT NULL,
                    next_step TEXT NOT NULL,
                    source_ids_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS dataset_candidates (
                    dataset_candidate_id TEXT PRIMARY KEY,
                    source_type TEXT NOT NULL,
                    quality_score REAL NOT NULL,
                    export_ready INTEGER NOT NULL,
                    source_ids_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS eval_candidates (
                    eval_candidate_id TEXT PRIMARY KEY,
                    scenario TEXT NOT NULL,
                    target_system TEXT NOT NULL,
                    expected_behavior TEXT NOT NULL,
                    source_ids_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

            for table, column_sql in (
                ("action_evidences", "result_code TEXT"),
                ("action_evidences", "failure_reason TEXT"),
                ("action_evidences", "policy_verdict TEXT"),
                ("action_evidences", "artifact_count INTEGER NOT NULL DEFAULT 0"),
            ):
                self._ensure_column(connection, table, column_sql)

            self._ensure_indexes(connection)
            self._ensure_vector_table(connection)
            self.set_meta("schema_version", CURRENT_SCHEMA_VERSION, connection=connection)
            self.set_meta("embedding_reindex_state", self.get_meta("embedding_reindex_state", connection) or "completed", connection=connection)
            self.set_meta("embedding_reindex_failure_reason", self.get_meta("embedding_reindex_failure_reason", connection) or "", connection=connection)

    def _ensure_column(self, connection: sqlite3.Connection, table_name: str, column_sql: str) -> None:
        column_name = column_sql.split()[0]
        existing = {row["name"] for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()}
        if column_name not in existing:
            connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}")

    def _ensure_indexes(self, connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_runtime_states_session_captured
                ON runtime_states(session_id, captured_at DESC);
            CREATE INDEX IF NOT EXISTS idx_approval_records_status_created
                ON approval_records(status, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_action_evidences_session_created
                ON action_evidences(session_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_artifact_pointers_owner
                ON artifact_pointers(owner_type, owner_id);
            CREATE INDEX IF NOT EXISTS idx_memory_records_user_updated
                ON memory_records(user_id, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_memory_records_openmemory
                ON memory_records(openmemory_id);
            CREATE INDEX IF NOT EXISTS idx_mission_runs_intent
                ON mission_runs(intent_id);
            CREATE INDEX IF NOT EXISTS idx_routing_decisions_intent
                ON routing_decisions(intent_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_channel_events_channel_created
                ON channel_events(channel, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_candidates_event_created
                ON conversation_memory_candidates(source_event_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_promotion_decisions_candidate
                ON promotion_decisions(candidate_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_gateway_dispatch_event
                ON gateway_dispatch_results(channel_event_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_graph_states_mission
                ON graph_states(mission_run_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_role_handoffs_mission
                ON role_handoffs(mission_run_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_execution_tickets_mission
                ON execution_tickets(mission_run_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_context_packs_created
                ON context_packs(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_api_run_requests_branch_status
                ON api_run_requests(branch_name, status, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_api_run_results_request_created
                ON api_run_results(run_request_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_api_run_reviews_run_created
                ON api_run_reviews(run_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_learning_signals_kind_created
                ON learning_signals(kind, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_decision_records_status_updated
                ON decision_records(status, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_loop_signals_created
                ON loop_signals(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_refresh_recommendations_created
                ON refresh_recommendations(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_dataset_candidates_created
                ON dataset_candidates(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_eval_candidates_created
                ON eval_candidates(created_at DESC);
            """
        )

    def _ensure_vector_table(self, connection: sqlite3.Connection) -> None:
        if not self.vector_enabled:
            return

        existing_dimensions = self.get_meta("embedding_dimensions", connection)
        if existing_dimensions != str(self.vector_dimensions):
            connection.execute("DROP TABLE IF EXISTS memory_embeddings")
            connection.execute("DELETE FROM memory_embedding_map")
            connection.execute(
                f"CREATE VIRTUAL TABLE memory_embeddings USING vec0(embedding float[{self.vector_dimensions}])"
            )
            self.set_meta("embedding_dimensions", str(self.vector_dimensions), connection=connection)
            return

        connection.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS memory_embeddings USING vec0(embedding float[{self.vector_dimensions}])"
        )

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connection
        try:
            connection.execute("BEGIN")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    def execute(
        self,
        sql: str,
        params: tuple[Any, ...] = (),
        *,
        connection: sqlite3.Connection | None = None,
    ) -> sqlite3.Cursor:
        cursor = (connection or self.connection).execute(sql, params)
        if connection is None:
            self.connection.commit()
        return cursor

    def fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        return self.connection.execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        return self.connection.execute(sql, params).fetchall()

    def next_vector_rowid(self, connection: sqlite3.Connection | None = None) -> int:
        row = (connection or self.connection).execute(
            "SELECT COALESCE(MAX(vector_rowid), 0) + 1 AS next_id FROM memory_embedding_map"
        ).fetchone()
        return int(row["next_id"]) if row else 1

    def upsert_vector(
        self,
        memory_id: str,
        vector_literal: str,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        if not self.vector_enabled:
            return
        target = connection or self.connection
        existing = target.execute(
            "SELECT vector_rowid FROM memory_embedding_map WHERE memory_id = ?",
            (memory_id,),
        ).fetchone()
        if existing:
            rowid = int(existing["vector_rowid"])
            target.execute("DELETE FROM memory_embeddings WHERE rowid = ?", (rowid,))
        else:
            rowid = self.next_vector_rowid(connection=target)
            target.execute(
                "INSERT OR REPLACE INTO memory_embedding_map(memory_id, vector_rowid) VALUES (?, ?)",
                (memory_id, rowid),
            )
        target.execute(
            "INSERT INTO memory_embeddings(rowid, embedding) VALUES (?, ?)",
            (rowid, vector_literal),
        )
        if connection is None:
            self.connection.commit()

    def search_vectors(self, vector_literal: str, limit: int) -> list[sqlite3.Row]:
        if not self.vector_enabled:
            return []
        return self.fetchall(
            """
            SELECT memory_embedding_map.memory_id, memory_embeddings.distance
            FROM memory_embeddings
            JOIN memory_embedding_map ON memory_embedding_map.vector_rowid = memory_embeddings.rowid
            WHERE memory_embeddings.embedding MATCH ?
              AND k = ?
            ORDER BY memory_embeddings.distance
            """,
            (vector_literal, limit),
        )

    def status(self) -> dict[str, Any]:
        return {
            "db_path": str(self.db_path),
            "vector_enabled": self.vector_enabled,
            "vector_dimensions": self.vector_dimensions,
            "schema_version": self.get_meta("schema_version"),
            "embedding_strategy_signature": self.get_meta("embedding_strategy_signature"),
            "openmemory_strategy_signature": self.get_meta("openmemory_strategy_signature"),
            "embedding_reindex_state": self.get_meta("embedding_reindex_state"),
        }

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def get_meta(self, key: str, connection: sqlite3.Connection | None = None) -> str | None:
        row = (connection or self.connection).execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row else None

    def set_meta(self, key: str, value: str, connection: sqlite3.Connection | None = None) -> None:
        target = connection or self.connection
        target.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
            (key, value),
        )
        if connection is None:
            self.connection.commit()


def dump_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True)
