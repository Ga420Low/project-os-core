from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


CURRENT_SCHEMA_VERSION = "14"


def _quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


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
                    parent_mission_id TEXT,
                    step_index INTEGER NOT NULL DEFAULT 0,
                    total_steps INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL,
                    execution_class TEXT,
                    routing_decision_id TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS mission_chains (
                    chain_id TEXT PRIMARY KEY,
                    objective TEXT NOT NULL,
                    steps_json TEXT NOT NULL,
                    current_step_index INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'running',
                    total_cost_eur REAL NOT NULL DEFAULT 0.0,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS scheduled_tasks (
                    task_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    schedule_kind TEXT NOT NULL,
                    interval_seconds INTEGER,
                    daily_at_hour INTEGER,
                    daily_at_minute INTEGER,
                    command TEXT NOT NULL,
                    command_args_json TEXT NOT NULL DEFAULT '{}',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    last_run_at TEXT,
                    next_run_at TEXT,
                    last_status TEXT,
                    last_error TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
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
                    source_message_id TEXT,
                    conversation_key TEXT,
                    ingress_dedup_key TEXT,
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

                CREATE TABLE IF NOT EXISTS discord_thread_bindings (
                    binding_id TEXT PRIMARY KEY,
                    binding_key TEXT NOT NULL,
                    surface TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    external_thread_id TEXT,
                    parent_thread_id TEXT,
                    channel_event_id TEXT,
                    dispatch_id TEXT,
                    envelope_id TEXT,
                    decision_id TEXT,
                    mission_run_id TEXT,
                    binding_kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS session_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    active_runs_json TEXT NOT NULL DEFAULT '[]',
                    pending_clarifications_json TEXT NOT NULL DEFAULT '[]',
                    pending_contracts_json TEXT NOT NULL DEFAULT '[]',
                    pending_approvals_json TEXT NOT NULL DEFAULT '[]',
                    pending_deliveries INTEGER NOT NULL DEFAULT 0,
                    daily_spend_eur REAL NOT NULL DEFAULT 0.0,
                    active_missions_json TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
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
                    mission_chain_id TEXT,
                    mission_step_index INTEGER,
                    skill_tags_json TEXT NOT NULL,
                    expected_outputs_json TEXT NOT NULL,
                    coding_lane TEXT NOT NULL,
                    desktop_lane TEXT NOT NULL,
                    communication_mode TEXT,
                    speech_policy TEXT,
                    operator_language TEXT,
                    audience TEXT,
                    run_contract_required INTEGER,
                    contract_id TEXT,
                    status TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS api_run_contracts (
                    contract_id TEXT PRIMARY KEY,
                    context_pack_id TEXT NOT NULL,
                    prompt_template_id TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    branch_name TEXT NOT NULL,
                    target_profile TEXT,
                    model TEXT NOT NULL,
                    reasoning_effort TEXT NOT NULL,
                    communication_mode TEXT NOT NULL,
                    speech_policy TEXT NOT NULL,
                    operator_language TEXT NOT NULL,
                    audience TEXT NOT NULL,
                    expected_outputs_json TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    non_goals_json TEXT NOT NULL,
                    success_criteria_json TEXT NOT NULL,
                    estimated_cost_eur REAL NOT NULL,
                    founder_decision TEXT,
                    founder_decision_at TEXT,
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

                CREATE TABLE IF NOT EXISTS api_run_events (
                    event_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    machine_summary TEXT NOT NULL,
                    human_summary TEXT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS completion_reports (
                    report_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    verdict TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    done_items_json TEXT NOT NULL,
                    test_summary_json TEXT NOT NULL,
                    risks_json TEXT NOT NULL,
                    next_action TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS blockage_reports (
                    report_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    cause TEXT NOT NULL,
                    impact TEXT NOT NULL,
                    choices_json TEXT NOT NULL,
                    recommendation TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS clarification_reports (
                    report_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    cause TEXT NOT NULL,
                    impact TEXT NOT NULL,
                    question_for_founder TEXT NOT NULL,
                    recommended_contract_change TEXT NOT NULL,
                    requires_reapproval INTEGER NOT NULL DEFAULT 1,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS api_run_lifecycle_events (
                    lifecycle_event_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    run_request_id TEXT NOT NULL,
                    contract_id TEXT,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    branch_name TEXT,
                    mode TEXT,
                    channel_hint TEXT NOT NULL,
                    status TEXT,
                    phase TEXT,
                    blocking_question TEXT,
                    recommended_action TEXT,
                    requires_reapproval INTEGER NOT NULL DEFAULT 0,
                    artifact_path TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS api_run_operator_deliveries (
                    delivery_id TEXT PRIMARY KEY,
                    lifecycle_event_id TEXT NOT NULL,
                    adapter TEXT NOT NULL,
                    surface TEXT NOT NULL,
                    channel_hint TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    payload_json TEXT NOT NULL,
                    last_error TEXT,
                    next_attempt_at TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
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

                CREATE TABLE IF NOT EXISTS noise_signals (
                    noise_signal_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
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

                CREATE TABLE IF NOT EXISTS mem_cubes (
                    cube_id TEXT PRIMARY KEY,
                    layer TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    supersedes_json TEXT NOT NULL,
                    sources_json TEXT NOT NULL,
                    access_scope TEXT NOT NULL,
                    usage_stats_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS memory_blocks (
                    block_id TEXT PRIMARY KEY,
                    block_name TEXT NOT NULL UNIQUE,
                    owner_role TEXT NOT NULL,
                    path TEXT NOT NULL,
                    hash_sha256 TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    access_policy_json TEXT NOT NULL,
                    provenance_json TEXT NOT NULL,
                    last_updated_by_role TEXT,
                    last_updated_by_run_id TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS memory_block_revisions (
                    revision_id TEXT PRIMARY KEY,
                    block_id TEXT NOT NULL,
                    block_name TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    path TEXT NOT NULL,
                    hash_sha256 TEXT NOT NULL,
                    content TEXT NOT NULL,
                    content_summary TEXT,
                    change_reason TEXT,
                    provenance_json TEXT NOT NULL,
                    updated_by_role TEXT,
                    updated_by_run_id TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS curator_runs (
                    curator_run_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    trigger TEXT NOT NULL,
                    window_start TEXT NOT NULL,
                    window_end TEXT NOT NULL,
                    llm_mode TEXT NOT NULL,
                    model TEXT,
                    summary TEXT,
                    input_summary_json TEXT NOT NULL,
                    output_summary_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS thought_memories (
                    thought_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    content TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    status TEXT NOT NULL,
                    source_ids_json TEXT NOT NULL,
                    supersedes_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS supersession_records (
                    supersession_record_id TEXT PRIMARY KEY,
                    superseded_type TEXT NOT NULL,
                    superseded_id TEXT NOT NULL,
                    superseding_type TEXT NOT NULL,
                    superseding_id TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS memory_operation_traces (
                    trace_id TEXT PRIMARY KEY,
                    operation TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    detail_json TEXT NOT NULL,
                    routing_trace_id TEXT,
                    run_id TEXT,
                    decision_record_id TEXT,
                    channel_event_id TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS temporal_graph_facts (
                    fact_id TEXT PRIMARY KEY,
                    episode_id TEXT,
                    entity TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    value TEXT NOT NULL,
                    valid_at TEXT NOT NULL,
                    invalid_at TEXT,
                    source_ref TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS github_issue_ingestions (
                    repo TEXT NOT NULL,
                    issue_number INTEGER NOT NULL,
                    issue_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    state TEXT NOT NULL,
                    labels_json TEXT NOT NULL DEFAULT '[]',
                    payload_sha256 TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    closed_at TEXT,
                    ingested_at TEXT NOT NULL,
                    learning_refs_json TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY (repo, issue_number)
                );
                """
            )

            for table, column_sql in (
                ("action_evidences", "result_code TEXT"),
                ("action_evidences", "failure_reason TEXT"),
                ("action_evidences", "policy_verdict TEXT"),
                ("action_evidences", "artifact_count INTEGER NOT NULL DEFAULT 0"),
                ("mission_runs", "parent_mission_id TEXT"),
                ("mission_runs", "step_index INTEGER NOT NULL DEFAULT 0"),
                ("mission_runs", "total_steps INTEGER NOT NULL DEFAULT 1"),
                ("channel_events", "source_message_id TEXT"),
                ("channel_events", "conversation_key TEXT"),
                ("channel_events", "ingress_dedup_key TEXT"),
                ("api_run_requests", "communication_mode TEXT"),
                ("api_run_requests", "speech_policy TEXT"),
                ("api_run_requests", "operator_language TEXT"),
                ("api_run_requests", "audience TEXT"),
                ("api_run_requests", "run_contract_required INTEGER"),
                ("api_run_requests", "contract_id TEXT"),
                ("api_run_requests", "mission_chain_id TEXT"),
                ("api_run_requests", "mission_step_index INTEGER"),
                ("api_run_contracts", "founder_decision_at TEXT"),
                ("api_run_operator_deliveries", "next_attempt_at TEXT"),
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
            CREATE INDEX IF NOT EXISTS idx_mission_runs_parent_step
                ON mission_runs(parent_mission_id, step_index, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_mission_chains_status_updated
                ON mission_chains(status, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_name_enabled
                ON scheduled_tasks(name, enabled);
            CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_next_run
                ON scheduled_tasks(enabled, next_run_at ASC);
            CREATE INDEX IF NOT EXISTS idx_routing_decisions_intent
                ON routing_decisions(intent_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_channel_events_channel_created
                ON channel_events(channel, created_at DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_channel_events_ingress_dedup
                ON channel_events(ingress_dedup_key)
                WHERE ingress_dedup_key IS NOT NULL;
            CREATE INDEX IF NOT EXISTS idx_candidates_event_created
                ON conversation_memory_candidates(source_event_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_promotion_decisions_candidate
                ON promotion_decisions(candidate_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_gateway_dispatch_event
                ON gateway_dispatch_results(channel_event_id, created_at DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_discord_thread_bindings_key
                ON discord_thread_bindings(binding_key);
            CREATE INDEX IF NOT EXISTS idx_discord_thread_bindings_mission_updated
                ON discord_thread_bindings(mission_run_id, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_discord_thread_bindings_surface_updated
                ON discord_thread_bindings(surface, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_session_snapshots_created
                ON session_snapshots(created_at DESC);
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
            CREATE INDEX IF NOT EXISTS idx_api_run_requests_chain_step
                ON api_run_requests(mission_chain_id, mission_step_index, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_api_run_requests_contract
                ON api_run_requests(contract_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_api_run_results_request_created
                ON api_run_results(run_request_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_api_run_contracts_status_created
                ON api_run_contracts(status, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_api_run_reviews_run_created
                ON api_run_reviews(run_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_api_run_events_run_created
                ON api_run_events(run_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_completion_reports_run_created
                ON completion_reports(run_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_blockage_reports_run_created
                ON blockage_reports(run_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_clarification_reports_run_created
                ON clarification_reports(run_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_api_run_lifecycle_events_run_created
                ON api_run_lifecycle_events(run_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_api_run_lifecycle_events_kind_created
                ON api_run_lifecycle_events(kind, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_api_run_operator_deliveries_status_updated
                ON api_run_operator_deliveries(status, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_api_run_operator_deliveries_event_created
                ON api_run_operator_deliveries(lifecycle_event_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_api_run_operator_deliveries_status_next_attempt
                ON api_run_operator_deliveries(status, next_attempt_at ASC, created_at ASC);
            CREATE INDEX IF NOT EXISTS idx_learning_signals_kind_created
                ON learning_signals(kind, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_decision_records_status_updated
                ON decision_records(status, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_loop_signals_created
                ON loop_signals(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_noise_signals_run_created
                ON noise_signals(run_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_refresh_recommendations_created
                ON refresh_recommendations(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_dataset_candidates_created
                ON dataset_candidates(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_eval_candidates_created
                ON eval_candidates(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_mem_cubes_layer_updated
                ON mem_cubes(layer, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_mem_cubes_kind_updated
                ON mem_cubes(kind, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_memory_blocks_name_updated
                ON memory_blocks(block_name, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_memory_block_revisions_block_created
                ON memory_block_revisions(block_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_curator_runs_status_updated
                ON curator_runs(status, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_curator_runs_window
                ON curator_runs(window_start, window_end, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_thought_memories_status_updated
                ON thought_memories(status, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_thought_memories_kind_updated
                ON thought_memories(kind, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_supersession_superseded
                ON supersession_records(superseded_type, superseded_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_memory_operation_traces_target
                ON memory_operation_traces(target_type, target_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_memory_operation_traces_operation
                ON memory_operation_traces(operation, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_temporal_graph_facts_entity_valid
                ON temporal_graph_facts(entity, valid_at DESC);
            CREATE INDEX IF NOT EXISTS idx_temporal_graph_facts_source
                ON temporal_graph_facts(source_ref, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_github_issue_ingestions_ingested
                ON github_issue_ingestions(ingested_at DESC);
            CREATE INDEX IF NOT EXISTS idx_github_issue_ingestions_updated
                ON github_issue_ingestions(updated_at DESC);
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

    def fetchone(
        self,
        sql: str,
        params: tuple[Any, ...] = (),
        *,
        connection: sqlite3.Connection | None = None,
    ) -> sqlite3.Row | None:
        return (connection or self.connection).execute(sql, params).fetchone()

    def fetchall(
        self,
        sql: str,
        params: tuple[Any, ...] = (),
        *,
        connection: sqlite3.Connection | None = None,
    ) -> list[sqlite3.Row]:
        return (connection or self.connection).execute(sql, params).fetchall()

    def upsert(
        self,
        table: str,
        values: dict[str, Any],
        *,
        conflict_columns: str | list[str] | tuple[str, ...],
        immutable_columns: list[str] | tuple[str, ...] = (),
        update_columns: list[str] | tuple[str, ...] | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> sqlite3.Cursor:
        if isinstance(conflict_columns, str):
            conflict_names = [conflict_columns]
        else:
            conflict_names = list(conflict_columns)
        if not conflict_names:
            raise ValueError("conflict_columns must not be empty")

        column_names = list(values.keys())
        if not column_names:
            raise ValueError("values must not be empty")

        if update_columns is None:
            blocked = set(conflict_names) | set(immutable_columns)
            update_names = [name for name in column_names if name not in blocked]
        else:
            update_names = list(update_columns)

        columns_sql = ", ".join(_quote_identifier(name) for name in column_names)
        placeholders = ", ".join("?" for _ in column_names)
        conflict_sql = ", ".join(_quote_identifier(name) for name in conflict_names)
        sql = (
            f"INSERT INTO {_quote_identifier(table)} ({columns_sql}) "
            f"VALUES ({placeholders}) "
        )
        if update_names:
            assignments = ", ".join(
                f"{_quote_identifier(name)} = excluded.{_quote_identifier(name)}"
                for name in update_names
            )
            sql += f"ON CONFLICT({conflict_sql}) DO UPDATE SET {assignments}"
        else:
            sql += f"ON CONFLICT({conflict_sql}) DO NOTHING"
        params = tuple(values[name] for name in column_names)
        return self.execute(sql, params, connection=connection)

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
            self.upsert(
                "memory_embedding_map",
                {"memory_id": memory_id, "vector_rowid": rowid},
                conflict_columns="memory_id",
                connection=target,
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
        self.upsert(
            "meta",
            {"key": key, "value": value},
            conflict_columns="key",
            connection=connection,
        )


def dump_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True)
