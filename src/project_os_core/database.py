from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4


CURRENT_SCHEMA_VERSION = "21"


def _quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_prefixed_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


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
                    correlation_id TEXT,
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
                    correlation_id TEXT,
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
                    correlation_id TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS routing_decision_traces (
                    trace_id TEXT PRIMARY KEY,
                    decision_id TEXT NOT NULL,
                    runtime_state_id TEXT,
                    inputs_json TEXT NOT NULL,
                    outputs_json TEXT NOT NULL,
                    correlation_id TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS trace_edges (
                    trace_edge_id TEXT PRIMARY KEY,
                    parent_id TEXT NOT NULL,
                    parent_kind TEXT NOT NULL,
                    child_id TEXT NOT NULL,
                    child_kind TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS output_quarantine_records (
                    quarantine_id TEXT PRIMARY KEY,
                    source_system TEXT NOT NULL,
                    source_entity_kind TEXT NOT NULL,
                    source_entity_id TEXT NOT NULL,
                    reason_code TEXT NOT NULL,
                    status TEXT NOT NULL,
                    provider TEXT,
                    model TEXT,
                    response_id TEXT,
                    previous_response_id TEXT,
                    run_id TEXT,
                    mission_run_id TEXT,
                    dispatch_id TEXT,
                    decision_id TEXT,
                    intent_id TEXT,
                    channel_event_id TEXT,
                    record_locator TEXT,
                    markers_json TEXT NOT NULL DEFAULT '[]',
                    payload_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS dead_letter_records (
                    dead_letter_id TEXT PRIMARY KEY,
                    domain TEXT NOT NULL,
                    source_entity_kind TEXT NOT NULL,
                    source_entity_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error_code TEXT,
                    error_message TEXT,
                    replayable INTEGER NOT NULL DEFAULT 0,
                    recovery_command TEXT,
                    artifact_path TEXT,
                    correlation_id TEXT,
                    run_id TEXT,
                    mission_run_id TEXT,
                    dispatch_id TEXT,
                    channel_event_id TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS debug_replay_runs (
                    replay_id TEXT PRIMARY KEY,
                    source_entity_kind TEXT NOT NULL,
                    source_entity_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    idempotency_key TEXT,
                    source_identifier TEXT,
                    trigger_kind TEXT NOT NULL,
                    correlation_id TEXT,
                    run_id TEXT,
                    mission_run_id TEXT,
                    dispatch_id TEXT,
                    channel_event_id TEXT,
                    result_entity_kind TEXT,
                    result_entity_id TEXT,
                    artifact_path TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
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
                    correlation_id TEXT,
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
                    correlation_id TEXT,
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

                CREATE TABLE IF NOT EXISTS incident_records (
                    incident_id TEXT PRIMARY KEY,
                    severity TEXT NOT NULL,
                    status TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    symptom TEXT NOT NULL,
                    root_cause_hypothesis TEXT,
                    fix_summary TEXT,
                    source_ids_json TEXT NOT NULL DEFAULT '[]',
                    verification_refs_json TEXT NOT NULL DEFAULT '[]',
                    correlation_id TEXT,
                    run_id TEXT,
                    mission_run_id TEXT,
                    dispatch_id TEXT,
                    channel_event_id TEXT,
                    replay_id TEXT,
                    dead_letter_id TEXT,
                    eval_case_id TEXT,
                    latest_eval_run_id TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    resolved_at TEXT
                );

                CREATE TABLE IF NOT EXISTS eval_cases (
                    eval_case_id TEXT PRIMARY KEY,
                    suite_id TEXT NOT NULL,
                    scenario TEXT NOT NULL,
                    target_system TEXT NOT NULL,
                    expected_behavior TEXT NOT NULL,
                    runner_kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    idempotency_key TEXT,
                    source_ids_json TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    provenance_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS eval_runs (
                    eval_run_id TEXT PRIMARY KEY,
                    suite_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    trigger_kind TEXT NOT NULL,
                    case_ids_json TEXT NOT NULL DEFAULT '[]',
                    results_json TEXT NOT NULL DEFAULT '[]',
                    passed_count INTEGER NOT NULL DEFAULT 0,
                    failed_count INTEGER NOT NULL DEFAULT 0,
                    skipped_count INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    provenance_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
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

                CREATE TABLE IF NOT EXISTS deep_research_source_observations (
                    observation_id TEXT PRIMARY KEY,
                    run_id TEXT,
                    normalized_source_id TEXT NOT NULL,
                    normalized_url TEXT,
                    domain TEXT,
                    publisher TEXT,
                    source_kind TEXT NOT NULL,
                    lane TEXT,
                    trust_class TEXT NOT NULL,
                    reputation_class TEXT NOT NULL,
                    score REAL NOT NULL,
                    corroborated INTEGER NOT NULL DEFAULT 0,
                    contradicted INTEGER NOT NULL DEFAULT 0,
                    published_at TEXT,
                    observed_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS deep_research_source_reputation (
                    normalized_source_id TEXT PRIMARY KEY,
                    normalized_url TEXT,
                    domain TEXT,
                    publisher TEXT,
                    source_kind TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    observation_count INTEGER NOT NULL DEFAULT 0,
                    trusted_count INTEGER NOT NULL DEFAULT 0,
                    weak_count INTEGER NOT NULL DEFAULT 0,
                    quarantined_count INTEGER NOT NULL DEFAULT 0,
                    corroborated_count INTEGER NOT NULL DEFAULT 0,
                    contradicted_count INTEGER NOT NULL DEFAULT 0,
                    latest_published_at TEXT,
                    last_score REAL NOT NULL DEFAULT 0,
                    last_trust_class TEXT NOT NULL DEFAULT 'weak_signal',
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS thread_ledgers (
                    thread_ledger_id TEXT PRIMARY KEY,
                    surface TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    external_thread_id TEXT,
                    conversation_key TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    active_subject TEXT,
                    subtopics_json TEXT NOT NULL DEFAULT '[]',
                    last_operator_reply_id TEXT,
                    last_authoritative_reply_summary TEXT,
                    last_artifact_id TEXT,
                    last_pdf_artifact_id TEXT,
                    last_bundle_id TEXT,
                    active_bundle_ids_json TEXT NOT NULL DEFAULT '[]',
                    active_analysis_object_ids_json TEXT NOT NULL DEFAULT '[]',
                    referenced_object_ids_json TEXT NOT NULL DEFAULT '[]',
                    pending_approval_ids_json TEXT NOT NULL DEFAULT '[]',
                    mode TEXT,
                    claims_json TEXT NOT NULL DEFAULT '[]',
                    questions_json TEXT NOT NULL DEFAULT '[]',
                    decisions_json TEXT NOT NULL DEFAULT '[]',
                    contradictions_json TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS thread_ledger_events (
                    thread_ledger_event_id TEXT PRIMARY KEY,
                    thread_ledger_id TEXT NOT NULL,
                    event_kind TEXT NOT NULL,
                    related_id TEXT,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS artifact_ledger_entries (
                    artifact_ledger_entry_id TEXT PRIMARY KEY,
                    artifact_id TEXT NOT NULL,
                    artifact_kind TEXT NOT NULL,
                    owner_type TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    surface TEXT,
                    channel TEXT,
                    thread_id TEXT,
                    external_thread_id TEXT,
                    conversation_key TEXT,
                    reply_id TEXT,
                    run_id TEXT,
                    approval_id TEXT,
                    bundle_id TEXT,
                    source_object_id TEXT,
                    source_ids_json TEXT NOT NULL DEFAULT '[]',
                    cold_artifact_id TEXT,
                    cold_path TEXT,
                    ingestion_status TEXT NOT NULL DEFAULT 'ready',
                    source_locator TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS analysis_objects (
                    object_id TEXT PRIMARY KEY,
                    object_type TEXT NOT NULL,
                    surface TEXT,
                    channel TEXT,
                    thread_id TEXT,
                    conversation_key TEXT,
                    title TEXT,
                    summary_short TEXT NOT NULL DEFAULT '',
                    summary_full TEXT NOT NULL DEFAULT '',
                    source_ids_json TEXT NOT NULL DEFAULT '[]',
                    artifact_ids_json TEXT NOT NULL DEFAULT '[]',
                    claims_json TEXT NOT NULL DEFAULT '[]',
                    questions_json TEXT NOT NULL DEFAULT '[]',
                    decisions_json TEXT NOT NULL DEFAULT '[]',
                    confidence REAL NOT NULL DEFAULT 0.0,
                    status TEXT NOT NULL DEFAULT 'active',
                    content_status TEXT NOT NULL DEFAULT 'ready',
                    source_mime_type TEXT,
                    extracted_text_artifact_id TEXT,
                    bundle_ids_json TEXT NOT NULL DEFAULT '[]',
                    supersedes_json TEXT NOT NULL DEFAULT '[]',
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS analysis_bundles (
                    bundle_id TEXT PRIMARY KEY,
                    bundle_kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    surface TEXT,
                    channel TEXT,
                    thread_id TEXT,
                    conversation_key TEXT,
                    summary_short TEXT NOT NULL DEFAULT '',
                    summary_full TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS bundle_members (
                    bundle_id TEXT NOT NULL,
                    object_id TEXT NOT NULL,
                    member_role TEXT NOT NULL DEFAULT 'member',
                    position INTEGER,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (bundle_id, object_id)
                );

                CREATE TABLE IF NOT EXISTS working_set_snapshots (
                    working_set_id TEXT PRIMARY KEY,
                    surface TEXT,
                    channel TEXT,
                    thread_id TEXT,
                    conversation_key TEXT,
                    message_id TEXT,
                    summary TEXT NOT NULL DEFAULT '',
                    selected_object_ids_json TEXT NOT NULL DEFAULT '[]',
                    selected_object_digests_json TEXT NOT NULL DEFAULT '[]',
                    selected_artifact_ids_json TEXT NOT NULL DEFAULT '[]',
                    selected_bundle_ids_json TEXT NOT NULL DEFAULT '[]',
                    reasons_json TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS artifact_ingestion_tasks (
                    task_id TEXT PRIMARY KEY,
                    artifact_id TEXT NOT NULL,
                    conversation_key TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS reference_resolutions (
                    resolution_id TEXT PRIMARY KEY,
                    resolution_kind TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    surface TEXT,
                    channel TEXT,
                    thread_id TEXT,
                    conversation_key TEXT,
                    message_id TEXT,
                    target_type TEXT,
                    target_id TEXT,
                    reason TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS claim_records (
                    claim_record_id TEXT PRIMARY KEY,
                    conversation_key TEXT,
                    thread_id TEXT,
                    object_id TEXT,
                    claim_text TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 0.0,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS question_records (
                    question_record_id TEXT PRIMARY KEY,
                    conversation_key TEXT,
                    thread_id TEXT,
                    object_id TEXT,
                    question_text TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 0.0,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS rating_records (
                    rating_record_id TEXT PRIMARY KEY,
                    conversation_key TEXT,
                    thread_id TEXT,
                    object_id TEXT,
                    score REAL,
                    rationale TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                """
            )

            for table, column_sql in (
                ("action_evidences", "result_code TEXT"),
                ("action_evidences", "failure_reason TEXT"),
                ("action_evidences", "policy_verdict TEXT"),
                ("action_evidences", "artifact_count INTEGER NOT NULL DEFAULT 0"),
                ("mission_intents", "correlation_id TEXT"),
                ("mission_runs", "parent_mission_id TEXT"),
                ("mission_runs", "step_index INTEGER NOT NULL DEFAULT 0"),
                ("mission_runs", "total_steps INTEGER NOT NULL DEFAULT 1"),
                ("mission_runs", "correlation_id TEXT"),
                ("routing_decisions", "correlation_id TEXT"),
                ("routing_decision_traces", "correlation_id TEXT"),
                ("channel_events", "source_message_id TEXT"),
                ("channel_events", "conversation_key TEXT"),
                ("channel_events", "ingress_dedup_key TEXT"),
                ("channel_events", "correlation_id TEXT"),
                ("gateway_dispatch_results", "correlation_id TEXT"),
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
                ("artifact_ledger_entries", "ingestion_status TEXT NOT NULL DEFAULT 'ready'"),
                ("artifact_ledger_entries", "source_locator TEXT"),
                ("analysis_objects", "content_status TEXT NOT NULL DEFAULT 'ready'"),
                ("analysis_objects", "source_mime_type TEXT"),
                ("analysis_objects", "extracted_text_artifact_id TEXT"),
                ("analysis_objects", "bundle_ids_json TEXT NOT NULL DEFAULT '[]'"),
                ("working_set_snapshots", "selected_object_digests_json TEXT NOT NULL DEFAULT '[]'"),
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
            CREATE INDEX IF NOT EXISTS idx_mission_intents_correlation_created
                ON mission_intents(correlation_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_mission_runs_parent_step
                ON mission_runs(parent_mission_id, step_index, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_mission_runs_correlation_created
                ON mission_runs(correlation_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_mission_chains_status_updated
                ON mission_chains(status, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_name_enabled
                ON scheduled_tasks(name, enabled);
            CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_next_run
                ON scheduled_tasks(enabled, next_run_at ASC);
            CREATE INDEX IF NOT EXISTS idx_routing_decisions_intent
                ON routing_decisions(intent_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_routing_decisions_correlation_created
                ON routing_decisions(correlation_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_routing_traces_correlation_created
                ON routing_decision_traces(correlation_id, created_at DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_trace_edges_relation
                ON trace_edges(parent_id, parent_kind, child_id, child_kind, relation);
            CREATE INDEX IF NOT EXISTS idx_trace_edges_parent_created
                ON trace_edges(parent_id, parent_kind, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_trace_edges_child_created
                ON trace_edges(child_id, child_kind, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_output_quarantine_source_created
                ON output_quarantine_records(source_system, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_output_quarantine_status_created
                ON output_quarantine_records(status, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_output_quarantine_entity_created
                ON output_quarantine_records(source_entity_kind, source_entity_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_output_quarantine_run_created
                ON output_quarantine_records(run_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_dead_letter_domain_created
                ON dead_letter_records(domain, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_dead_letter_source_created
                ON dead_letter_records(source_entity_kind, source_entity_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_dead_letter_status_created
                ON dead_letter_records(status, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_dead_letter_correlation_created
                ON dead_letter_records(correlation_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_debug_replay_source_created
                ON debug_replay_runs(source_entity_kind, source_entity_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_debug_replay_status_created
                ON debug_replay_runs(status, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_debug_replay_correlation_created
                ON debug_replay_runs(correlation_id, created_at DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_debug_replay_idempotency
                ON debug_replay_runs(idempotency_key)
                WHERE idempotency_key IS NOT NULL;
            CREATE INDEX IF NOT EXISTS idx_channel_events_channel_created
                ON channel_events(channel, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_channel_events_correlation_created
                ON channel_events(correlation_id, created_at DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_channel_events_ingress_dedup
                ON channel_events(ingress_dedup_key)
                WHERE ingress_dedup_key IS NOT NULL;
            CREATE INDEX IF NOT EXISTS idx_candidates_event_created
                ON conversation_memory_candidates(source_event_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_promotion_decisions_candidate
                ON promotion_decisions(candidate_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_gateway_dispatch_event
                ON gateway_dispatch_results(channel_event_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_gateway_dispatch_correlation_created
                ON gateway_dispatch_results(correlation_id, created_at DESC);
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
            CREATE INDEX IF NOT EXISTS idx_incident_records_status_updated
                ON incident_records(status, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_incident_records_severity_created
                ON incident_records(severity, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_incident_records_correlation_created
                ON incident_records(correlation_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_eval_cases_suite_status
                ON eval_cases(suite_id, status, updated_at DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_eval_cases_idempotency
                ON eval_cases(idempotency_key)
                WHERE idempotency_key IS NOT NULL;
            CREATE INDEX IF NOT EXISTS idx_eval_runs_suite_created
                ON eval_runs(suite_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_eval_runs_status_created
                ON eval_runs(status, created_at DESC);
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
            CREATE INDEX IF NOT EXISTS idx_deep_research_obs_run_observed
                ON deep_research_source_observations(run_id, observed_at DESC);
            CREATE INDEX IF NOT EXISTS idx_deep_research_obs_source_observed
                ON deep_research_source_observations(normalized_source_id, observed_at DESC);
            CREATE INDEX IF NOT EXISTS idx_deep_research_obs_domain_observed
                ON deep_research_source_observations(domain, observed_at DESC);
            CREATE INDEX IF NOT EXISTS idx_deep_research_rep_domain_updated
                ON deep_research_source_reputation(domain, last_seen_at DESC);
            CREATE INDEX IF NOT EXISTS idx_deep_research_rep_score_updated
                ON deep_research_source_reputation(last_score DESC, last_seen_at DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_thread_ledgers_conversation
                ON thread_ledgers(surface, channel, conversation_key);
            CREATE INDEX IF NOT EXISTS idx_thread_ledger_events_thread_created
                ON thread_ledger_events(thread_ledger_id, created_at DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_artifact_ledger_entries_artifact
                ON artifact_ledger_entries(artifact_id);
            CREATE INDEX IF NOT EXISTS idx_artifact_ledger_entries_conversation_created
                ON artifact_ledger_entries(conversation_key, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_analysis_objects_conversation_updated
                ON analysis_objects(conversation_key, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_analysis_objects_thread_updated
                ON analysis_objects(thread_id, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_analysis_bundles_conversation_updated
                ON analysis_bundles(conversation_key, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_bundle_members_bundle_created
                ON bundle_members(bundle_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_working_set_snapshots_conversation_created
                ON working_set_snapshots(conversation_key, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_artifact_ingestion_tasks_status_updated
                ON artifact_ingestion_tasks(status, updated_at ASC, created_at ASC);
            CREATE INDEX IF NOT EXISTS idx_artifact_ingestion_tasks_artifact
                ON artifact_ingestion_tasks(artifact_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_reference_resolutions_conversation_created
                ON reference_resolutions(conversation_key, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_claim_records_conversation_created
                ON claim_records(conversation_key, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_question_records_conversation_created
                ON question_records(conversation_key, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_rating_records_conversation_created
                ON rating_records(conversation_key, created_at DESC);
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

    def record_trace_edge(
        self,
        *,
        parent_id: str,
        parent_kind: str,
        child_id: str,
        child_kind: str,
        relation: str,
        metadata: dict[str, Any] | None = None,
        trace_edge_id: str | None = None,
        created_at: str | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> str:
        existing = self.fetchone(
            """
            SELECT trace_edge_id
            FROM trace_edges
            WHERE parent_id = ?
              AND parent_kind = ?
              AND child_id = ?
              AND child_kind = ?
              AND relation = ?
            """,
            (parent_id, parent_kind, child_id, child_kind, relation),
            connection=connection,
        )
        if existing is not None:
            edge_id = str(existing["trace_edge_id"])
            self.upsert(
                "trace_edges",
                {
                    "trace_edge_id": edge_id,
                    "parent_id": parent_id,
                    "parent_kind": parent_kind,
                    "child_id": child_id,
                    "child_kind": child_kind,
                    "relation": relation,
                    "metadata_json": dump_json(metadata or {}),
                    "created_at": created_at or _utc_now_iso(),
                },
                conflict_columns="trace_edge_id",
                immutable_columns=["created_at"],
                connection=connection,
            )
            return edge_id

        edge_id = trace_edge_id or _new_prefixed_id("trace_edge")
        self.upsert(
            "trace_edges",
            {
                "trace_edge_id": edge_id,
                "parent_id": parent_id,
                "parent_kind": parent_kind,
                "child_id": child_id,
                "child_kind": child_kind,
                "relation": relation,
                "metadata_json": dump_json(metadata or {}),
                "created_at": created_at or _utc_now_iso(),
            },
            conflict_columns="trace_edge_id",
            immutable_columns=["created_at"],
            connection=connection,
        )
        return edge_id

    def record_output_quarantine(
        self,
        *,
        source_system: str,
        source_entity_kind: str,
        source_entity_id: str,
        reason_code: str,
        status: str = "active",
        provider: str | None = None,
        model: str | None = None,
        response_id: str | None = None,
        previous_response_id: str | None = None,
        run_id: str | None = None,
        mission_run_id: str | None = None,
        dispatch_id: str | None = None,
        decision_id: str | None = None,
        intent_id: str | None = None,
        channel_event_id: str | None = None,
        record_locator: str | None = None,
        markers: list[str] | tuple[str, ...] | None = None,
        payload: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        quarantine_id: str | None = None,
        created_at: str | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> str:
        quarantine_record_id = quarantine_id or _new_prefixed_id("quarantine")
        self.upsert(
            "output_quarantine_records",
            {
                "quarantine_id": quarantine_record_id,
                "source_system": source_system,
                "source_entity_kind": source_entity_kind,
                "source_entity_id": source_entity_id,
                "reason_code": reason_code,
                "status": status,
                "provider": provider,
                "model": model,
                "response_id": response_id,
                "previous_response_id": previous_response_id,
                "run_id": run_id,
                "mission_run_id": mission_run_id,
                "dispatch_id": dispatch_id,
                "decision_id": decision_id,
                "intent_id": intent_id,
                "channel_event_id": channel_event_id,
                "record_locator": record_locator,
                "markers_json": dump_json(list(markers or [])),
                "payload_json": dump_json(payload or {}),
                "metadata_json": dump_json(metadata or {}),
                "created_at": created_at or _utc_now_iso(),
            },
            conflict_columns="quarantine_id",
            immutable_columns=["created_at"],
            connection=connection,
        )
        return quarantine_record_id

    def record_dead_letter(
        self,
        *,
        domain: str,
        source_entity_kind: str,
        source_entity_id: str,
        status: str = "active",
        error_code: str | None = None,
        error_message: str | None = None,
        replayable: bool = False,
        recovery_command: str | None = None,
        artifact_path: str | None = None,
        correlation_id: str | None = None,
        run_id: str | None = None,
        mission_run_id: str | None = None,
        dispatch_id: str | None = None,
        channel_event_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        dead_letter_id: str | None = None,
        created_at: str | None = None,
        updated_at: str | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> str:
        record_id = dead_letter_id or _new_prefixed_id("dead_letter")
        created_value = created_at or _utc_now_iso()
        updated_value = updated_at or created_value
        self.upsert(
            "dead_letter_records",
            {
                "dead_letter_id": record_id,
                "domain": domain,
                "source_entity_kind": source_entity_kind,
                "source_entity_id": source_entity_id,
                "status": status,
                "error_code": error_code,
                "error_message": error_message,
                "replayable": 1 if replayable else 0,
                "recovery_command": recovery_command,
                "artifact_path": artifact_path,
                "correlation_id": correlation_id,
                "run_id": run_id,
                "mission_run_id": mission_run_id,
                "dispatch_id": dispatch_id,
                "channel_event_id": channel_event_id,
                "metadata_json": dump_json(metadata or {}),
                "created_at": created_value,
                "updated_at": updated_value,
            },
            conflict_columns="dead_letter_id",
            immutable_columns=["created_at"],
            connection=connection,
        )
        return record_id

    def update_dead_letter_status_for_source(
        self,
        *,
        source_entity_kind: str,
        source_entity_id: str,
        status: str,
        metadata: dict[str, Any] | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> int:
        rows = self.fetchall(
            """
            SELECT dead_letter_id, metadata_json
            FROM dead_letter_records
            WHERE source_entity_kind = ?
              AND source_entity_id = ?
              AND status IN ('active', 'requeued')
            ORDER BY created_at DESC
            """,
            (source_entity_kind, source_entity_id),
            connection=connection,
        )
        updated_at = _utc_now_iso()
        count = 0
        for row in rows:
            current_metadata: dict[str, Any]
            try:
                current_metadata = json.loads(str(row["metadata_json"] or "{}"))
            except Exception:
                current_metadata = {}
            current_metadata.update(metadata or {})
            self.execute(
                """
                UPDATE dead_letter_records
                SET status = ?, metadata_json = ?, updated_at = ?
                WHERE dead_letter_id = ?
                """,
                (status, dump_json(current_metadata), updated_at, str(row["dead_letter_id"])),
                connection=connection,
            )
            count += 1
        return count

    def fetch_debug_replay_by_idempotency_key(self, idempotency_key: str) -> sqlite3.Row | None:
        normalized = str(idempotency_key or "").strip()
        if not normalized:
            return None
        return self.fetchone(
            "SELECT * FROM debug_replay_runs WHERE idempotency_key = ?",
            (normalized,),
        )

    def record_debug_replay_run(
        self,
        *,
        source_entity_kind: str,
        source_entity_id: str,
        status: str = "running",
        idempotency_key: str | None = None,
        source_identifier: str | None = None,
        trigger_kind: str = "manual",
        correlation_id: str | None = None,
        run_id: str | None = None,
        mission_run_id: str | None = None,
        dispatch_id: str | None = None,
        channel_event_id: str | None = None,
        result_entity_kind: str | None = None,
        result_entity_id: str | None = None,
        artifact_path: str | None = None,
        metadata: dict[str, Any] | None = None,
        replay_id: str | None = None,
        created_at: str | None = None,
        updated_at: str | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> str:
        record_id = replay_id or _new_prefixed_id("debug_replay")
        created_value = created_at or _utc_now_iso()
        updated_value = updated_at or created_value
        self.upsert(
            "debug_replay_runs",
            {
                "replay_id": record_id,
                "source_entity_kind": source_entity_kind,
                "source_entity_id": source_entity_id,
                "status": status,
                "idempotency_key": idempotency_key,
                "source_identifier": source_identifier,
                "trigger_kind": trigger_kind,
                "correlation_id": correlation_id,
                "run_id": run_id,
                "mission_run_id": mission_run_id,
                "dispatch_id": dispatch_id,
                "channel_event_id": channel_event_id,
                "result_entity_kind": result_entity_kind,
                "result_entity_id": result_entity_id,
                "artifact_path": artifact_path,
                "metadata_json": dump_json(metadata or {}),
                "created_at": created_value,
                "updated_at": updated_value,
            },
            conflict_columns="replay_id",
            immutable_columns=["created_at"],
            connection=connection,
        )
        return record_id

    def update_debug_replay_run(
        self,
        replay_id: str,
        *,
        status: str,
        correlation_id: str | None = None,
        run_id: str | None = None,
        mission_run_id: str | None = None,
        dispatch_id: str | None = None,
        channel_event_id: str | None = None,
        result_entity_kind: str | None = None,
        result_entity_id: str | None = None,
        artifact_path: str | None = None,
        metadata: dict[str, Any] | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        row = self.fetchone(
            "SELECT metadata_json FROM debug_replay_runs WHERE replay_id = ?",
            (replay_id,),
            connection=connection,
        )
        existing_metadata: dict[str, Any]
        try:
            existing_metadata = json.loads(str(row["metadata_json"] or "{}")) if row is not None else {}
        except Exception:
            existing_metadata = {}
        existing_metadata.update(metadata or {})
        self.execute(
            """
            UPDATE debug_replay_runs
            SET status = ?, correlation_id = COALESCE(?, correlation_id), run_id = COALESCE(?, run_id),
                mission_run_id = COALESCE(?, mission_run_id), dispatch_id = COALESCE(?, dispatch_id),
                channel_event_id = COALESCE(?, channel_event_id), result_entity_kind = COALESCE(?, result_entity_kind),
                result_entity_id = COALESCE(?, result_entity_id), artifact_path = COALESCE(?, artifact_path),
                metadata_json = ?, updated_at = ?
            WHERE replay_id = ?
            """,
            (
                status,
                correlation_id,
                run_id,
                mission_run_id,
                dispatch_id,
                channel_event_id,
                result_entity_kind,
                result_entity_id,
                artifact_path,
                dump_json(existing_metadata),
                _utc_now_iso(),
                replay_id,
            ),
            connection=connection,
        )

    def fetch_trace_report(self, correlation_id: str) -> dict[str, Any]:
        normalized = str(correlation_id or "").strip()
        payload: dict[str, Any] = {
            "found": False,
            "correlation_id": normalized,
            "summary": {},
            "channel_events": [],
            "mission_intents": [],
            "routing_decisions": [],
            "routing_traces": [],
            "mission_runs": [],
            "gateway_dispatches": [],
            "debug_replays": [],
            "dead_letters": [],
            "incidents": [],
            "eval_runs": [],
            "trace_edges": [],
        }
        if not normalized:
            return payload

        def _loads(raw: Any, default: Any) -> Any:
            if raw in (None, ""):
                return default
            try:
                return json.loads(str(raw))
            except Exception:
                return default

        channel_events = [
            {
                "event_id": str(row["event_id"]),
                "surface": str(row["surface"]),
                "event_type": str(row["event_type"]),
                "actor_id": str(row["actor_id"]),
                "channel": str(row["channel"]),
                "message_kind": str(row["message_kind"]) if row["message_kind"] else None,
                "source_message_id": str(row["source_message_id"]) if row["source_message_id"] else None,
                "conversation_key": str(row["conversation_key"]) if row["conversation_key"] else None,
                "ingress_dedup_key": str(row["ingress_dedup_key"]) if row["ingress_dedup_key"] else None,
                "correlation_id": str(row["correlation_id"]) if row["correlation_id"] else None,
                "thread_ref": _loads(row["thread_ref_json"], {}),
                "message": _loads(row["message_json"], {}),
                "raw_payload": _loads(row["raw_payload_json"], {}),
                "created_at": str(row["created_at"]),
            }
            for row in self.fetchall(
                """
                SELECT *
                FROM channel_events
                WHERE correlation_id = ?
                ORDER BY created_at ASC
                """,
                (normalized,),
            )
        ]
        mission_intents = [
            {
                "intent_id": str(row["intent_id"]),
                "source": str(row["source"]),
                "actor_id": str(row["actor_id"]),
                "channel": str(row["channel"]),
                "objective": str(row["objective"]),
                "target_profile": str(row["target_profile"]) if row["target_profile"] else None,
                "requested_worker": str(row["requested_worker"]) if row["requested_worker"] else None,
                "requested_risk_class": str(row["requested_risk_class"]) if row["requested_risk_class"] else None,
                "correlation_id": str(row["correlation_id"]) if row["correlation_id"] else None,
                "metadata": _loads(row["metadata_json"], {}),
                "created_at": str(row["created_at"]),
            }
            for row in self.fetchall(
                """
                SELECT *
                FROM mission_intents
                WHERE correlation_id = ?
                ORDER BY created_at ASC
                """,
                (normalized,),
            )
        ]
        routing_decisions = [
            {
                "decision_id": str(row["decision_id"]),
                "intent_id": str(row["intent_id"]),
                "mission_run_id": str(row["mission_run_id"]) if row["mission_run_id"] else None,
                "execution_class": str(row["execution_class"]),
                "risk_class": str(row["risk_class"]),
                "allowed": bool(row["allowed"]),
                "chosen_worker": str(row["chosen_worker"]) if row["chosen_worker"] else None,
                "model_route": _loads(row["model_route_json"], {}),
                "approval_gate": _loads(row["approval_gate_json"], {}),
                "budget_state": _loads(row["budget_state_json"], {}),
                "route_reason": str(row["route_reason"]),
                "blocked_reasons": _loads(row["blocked_reasons_json"], []),
                "correlation_id": str(row["correlation_id"]) if row["correlation_id"] else None,
                "created_at": str(row["created_at"]),
            }
            for row in self.fetchall(
                """
                SELECT *
                FROM routing_decisions
                WHERE correlation_id = ?
                ORDER BY created_at ASC
                """,
                (normalized,),
            )
        ]
        routing_traces = [
            {
                "trace_id": str(row["trace_id"]),
                "decision_id": str(row["decision_id"]),
                "runtime_state_id": str(row["runtime_state_id"]) if row["runtime_state_id"] else None,
                "inputs": _loads(row["inputs_json"], {}),
                "outputs": _loads(row["outputs_json"], {}),
                "correlation_id": str(row["correlation_id"]) if row["correlation_id"] else None,
                "created_at": str(row["created_at"]),
            }
            for row in self.fetchall(
                """
                SELECT *
                FROM routing_decision_traces
                WHERE correlation_id = ?
                ORDER BY created_at ASC
                """,
                (normalized,),
            )
        ]
        mission_runs = [
            {
                "mission_run_id": str(row["mission_run_id"]),
                "intent_id": str(row["intent_id"]),
                "objective": str(row["objective"]),
                "profile_name": str(row["profile_name"]) if row["profile_name"] else None,
                "parent_mission_id": str(row["parent_mission_id"]) if row["parent_mission_id"] else None,
                "step_index": int(row["step_index"]),
                "total_steps": int(row["total_steps"]),
                "status": str(row["status"]),
                "execution_class": str(row["execution_class"]) if row["execution_class"] else None,
                "routing_decision_id": str(row["routing_decision_id"]) if row["routing_decision_id"] else None,
                "correlation_id": str(row["correlation_id"]) if row["correlation_id"] else None,
                "metadata": _loads(row["metadata_json"], {}),
                "created_at": str(row["created_at"]),
                "updated_at": str(row["updated_at"]),
            }
            for row in self.fetchall(
                """
                SELECT *
                FROM mission_runs
                WHERE correlation_id = ?
                ORDER BY created_at ASC
                """,
                (normalized,),
            )
        ]
        gateway_dispatches = [
            {
                "dispatch_id": str(row["dispatch_id"]),
                "channel_event_id": str(row["channel_event_id"]),
                "envelope_id": str(row["envelope_id"]),
                "intent_id": str(row["intent_id"]),
                "decision_id": str(row["decision_id"]) if row["decision_id"] else None,
                "mission_run_id": str(row["mission_run_id"]) if row["mission_run_id"] else None,
                "correlation_id": str(row["correlation_id"]) if row["correlation_id"] else None,
                "memory_candidate_id": str(row["memory_candidate_id"]) if row["memory_candidate_id"] else None,
                "promotion_decision_id": str(row["promotion_decision_id"]) if row["promotion_decision_id"] else None,
                "promoted_memory_ids": _loads(row["promoted_memory_ids_json"], []),
                "reply": _loads(row["reply_json"], {}),
                "metadata": _loads(row["metadata_json"], {}),
                "created_at": str(row["created_at"]),
            }
            for row in self.fetchall(
                """
                SELECT *
                FROM gateway_dispatch_results
                WHERE correlation_id = ?
                ORDER BY created_at ASC
                """,
                (normalized,),
            )
        ]
        incidents = [
            {
                "incident_id": str(row["incident_id"]),
                "severity": str(row["severity"]),
                "status": str(row["status"]),
                "summary": str(row["summary"]),
                "symptom": str(row["symptom"]),
                "verification_refs": _loads(row["verification_refs_json"], []),
                "latest_eval_run_id": str(row["latest_eval_run_id"]) if row["latest_eval_run_id"] else None,
                "correlation_id": str(row["correlation_id"]) if row["correlation_id"] else None,
                "created_at": str(row["created_at"]),
                "updated_at": str(row["updated_at"]),
                "resolved_at": str(row["resolved_at"]) if row["resolved_at"] else None,
            }
            for row in self.fetchall(
                """
                SELECT *
                FROM incident_records
                WHERE correlation_id = ?
                ORDER BY created_at ASC
                """,
                (normalized,),
            )
        ]
        incident_eval_run_ids = [
            str(item["latest_eval_run_id"])
            for item in incidents
            if item.get("latest_eval_run_id")
        ]
        eval_runs: list[dict[str, Any]] = []
        if incident_eval_run_ids:
            placeholders = ", ".join("?" for _ in incident_eval_run_ids)
            eval_runs = [
                {
                    "eval_run_id": str(row["eval_run_id"]),
                    "suite_id": str(row["suite_id"]),
                    "status": str(row["status"]),
                    "trigger_kind": str(row["trigger_kind"]),
                    "case_ids": _loads(row["case_ids_json"], []),
                    "passed_count": int(row["passed_count"]),
                    "failed_count": int(row["failed_count"]),
                    "skipped_count": int(row["skipped_count"]),
                    "metadata": _loads(row["metadata_json"], {}),
                    "provenance": _loads(row["provenance_json"], {}),
                    "created_at": str(row["created_at"]),
                    "updated_at": str(row["updated_at"]),
                }
                for row in self.fetchall(
                    f"""
                    SELECT *
                    FROM eval_runs
                    WHERE eval_run_id IN ({placeholders})
                    ORDER BY created_at ASC
                    """,
                    tuple(incident_eval_run_ids),
                )
            ]

        entities = channel_events + mission_intents + routing_decisions + routing_traces + mission_runs + gateway_dispatches + incidents + eval_runs
        if not entities:
            return payload

        entity_ids = {
            item["event_id"]
            for item in channel_events
        } | {
            item["intent_id"]
            for item in mission_intents
        } | {
            item["decision_id"]
            for item in routing_decisions
        } | {
            item["trace_id"]
            for item in routing_traces
        } | {
            item["mission_run_id"]
            for item in mission_runs
        } | {
            item["dispatch_id"]
            for item in gateway_dispatches
        } | {
            item["incident_id"]
            for item in incidents
        } | {
            item["eval_run_id"]
            for item in eval_runs
        }
        trace_edges: list[dict[str, Any]] = []
        if entity_ids:
            placeholders = ", ".join("?" for _ in entity_ids)
            debug_replay_rows = self.fetchall(
                f"""
                SELECT *
                FROM debug_replay_runs
                WHERE correlation_id = ?
                   OR source_entity_id IN ({placeholders})
                   OR result_entity_id IN ({placeholders})
                ORDER BY created_at ASC
                """,
                (normalized, *tuple(entity_ids), *tuple(entity_ids)),
            )
            dead_letter_rows = self.fetchall(
                f"""
                SELECT *
                FROM dead_letter_records
                WHERE correlation_id = ?
                   OR source_entity_id IN ({placeholders})
                ORDER BY created_at ASC
                """,
                (normalized, *tuple(entity_ids)),
            )
            rows = self.fetchall(
                f"""
                SELECT *
                FROM trace_edges
                WHERE parent_id IN ({placeholders})
                   OR child_id IN ({placeholders})
                ORDER BY created_at ASC
                """,
                tuple(entity_ids) + tuple(entity_ids),
            )
            trace_edges = [
                {
                    "trace_edge_id": str(row["trace_edge_id"]),
                    "parent_id": str(row["parent_id"]),
                    "parent_kind": str(row["parent_kind"]),
                    "child_id": str(row["child_id"]),
                    "child_kind": str(row["child_kind"]),
                    "relation": str(row["relation"]),
                    "metadata": _loads(row["metadata_json"], {}),
                    "created_at": str(row["created_at"]),
                }
                for row in rows
            ]
            debug_replays = [
                {
                    "replay_id": str(row["replay_id"]),
                    "source_entity_kind": str(row["source_entity_kind"]),
                    "source_entity_id": str(row["source_entity_id"]),
                    "status": str(row["status"]),
                    "idempotency_key": str(row["idempotency_key"]) if row["idempotency_key"] else None,
                    "source_identifier": str(row["source_identifier"]) if row["source_identifier"] else None,
                    "trigger_kind": str(row["trigger_kind"]),
                    "correlation_id": str(row["correlation_id"]) if row["correlation_id"] else None,
                    "run_id": str(row["run_id"]) if row["run_id"] else None,
                    "mission_run_id": str(row["mission_run_id"]) if row["mission_run_id"] else None,
                    "dispatch_id": str(row["dispatch_id"]) if row["dispatch_id"] else None,
                    "channel_event_id": str(row["channel_event_id"]) if row["channel_event_id"] else None,
                    "result_entity_kind": str(row["result_entity_kind"]) if row["result_entity_kind"] else None,
                    "result_entity_id": str(row["result_entity_id"]) if row["result_entity_id"] else None,
                    "artifact_path": str(row["artifact_path"]) if row["artifact_path"] else None,
                    "metadata": _loads(row["metadata_json"], {}),
                    "created_at": str(row["created_at"]),
                    "updated_at": str(row["updated_at"]),
                }
                for row in debug_replay_rows
            ]
            dead_letters = [
                {
                    "dead_letter_id": str(row["dead_letter_id"]),
                    "domain": str(row["domain"]),
                    "source_entity_kind": str(row["source_entity_kind"]),
                    "source_entity_id": str(row["source_entity_id"]),
                    "status": str(row["status"]),
                    "error_code": str(row["error_code"]) if row["error_code"] else None,
                    "error_message": str(row["error_message"]) if row["error_message"] else None,
                    "replayable": bool(row["replayable"]),
                    "recovery_command": str(row["recovery_command"]) if row["recovery_command"] else None,
                    "artifact_path": str(row["artifact_path"]) if row["artifact_path"] else None,
                    "correlation_id": str(row["correlation_id"]) if row["correlation_id"] else None,
                    "run_id": str(row["run_id"]) if row["run_id"] else None,
                    "mission_run_id": str(row["mission_run_id"]) if row["mission_run_id"] else None,
                    "dispatch_id": str(row["dispatch_id"]) if row["dispatch_id"] else None,
                    "channel_event_id": str(row["channel_event_id"]) if row["channel_event_id"] else None,
                    "metadata": _loads(row["metadata_json"], {}),
                    "created_at": str(row["created_at"]),
                    "updated_at": str(row["updated_at"]),
                }
                for row in dead_letter_rows
            ]
        else:
            debug_replays = [
                {
                    "replay_id": str(row["replay_id"]),
                    "source_entity_kind": str(row["source_entity_kind"]),
                    "source_entity_id": str(row["source_entity_id"]),
                    "status": str(row["status"]),
                    "idempotency_key": str(row["idempotency_key"]) if row["idempotency_key"] else None,
                    "source_identifier": str(row["source_identifier"]) if row["source_identifier"] else None,
                    "trigger_kind": str(row["trigger_kind"]),
                    "correlation_id": str(row["correlation_id"]) if row["correlation_id"] else None,
                    "run_id": str(row["run_id"]) if row["run_id"] else None,
                    "mission_run_id": str(row["mission_run_id"]) if row["mission_run_id"] else None,
                    "dispatch_id": str(row["dispatch_id"]) if row["dispatch_id"] else None,
                    "channel_event_id": str(row["channel_event_id"]) if row["channel_event_id"] else None,
                    "result_entity_kind": str(row["result_entity_kind"]) if row["result_entity_kind"] else None,
                    "result_entity_id": str(row["result_entity_id"]) if row["result_entity_id"] else None,
                    "artifact_path": str(row["artifact_path"]) if row["artifact_path"] else None,
                    "metadata": _loads(row["metadata_json"], {}),
                    "created_at": str(row["created_at"]),
                    "updated_at": str(row["updated_at"]),
                }
                for row in self.fetchall(
                    """
                    SELECT *
                    FROM debug_replay_runs
                    WHERE correlation_id = ?
                    ORDER BY created_at ASC
                    """,
                    (normalized,),
                )
            ]
            dead_letters = [
                {
                    "dead_letter_id": str(row["dead_letter_id"]),
                    "domain": str(row["domain"]),
                    "source_entity_kind": str(row["source_entity_kind"]),
                    "source_entity_id": str(row["source_entity_id"]),
                    "status": str(row["status"]),
                    "error_code": str(row["error_code"]) if row["error_code"] else None,
                    "error_message": str(row["error_message"]) if row["error_message"] else None,
                    "replayable": bool(row["replayable"]),
                    "recovery_command": str(row["recovery_command"]) if row["recovery_command"] else None,
                    "artifact_path": str(row["artifact_path"]) if row["artifact_path"] else None,
                    "correlation_id": str(row["correlation_id"]) if row["correlation_id"] else None,
                    "run_id": str(row["run_id"]) if row["run_id"] else None,
                    "mission_run_id": str(row["mission_run_id"]) if row["mission_run_id"] else None,
                    "dispatch_id": str(row["dispatch_id"]) if row["dispatch_id"] else None,
                    "channel_event_id": str(row["channel_event_id"]) if row["channel_event_id"] else None,
                    "metadata": _loads(row["metadata_json"], {}),
                    "created_at": str(row["created_at"]),
                    "updated_at": str(row["updated_at"]),
                }
                for row in self.fetchall(
                    """
                    SELECT *
                    FROM dead_letter_records
                    WHERE correlation_id = ?
                    ORDER BY created_at ASC
                    """,
                    (normalized,),
                )
            ]

        created_values = [
            item["created_at"]
            for item in entities
            if isinstance(item, dict) and item.get("created_at")
        ]
        summary = {
            "channel_event_ids": [item["event_id"] for item in channel_events],
            "dispatch_ids": [item["dispatch_id"] for item in gateway_dispatches],
            "intent_ids": [item["intent_id"] for item in mission_intents],
            "decision_ids": [item["decision_id"] for item in routing_decisions],
            "trace_ids": [item["trace_id"] for item in routing_traces],
            "mission_run_ids": [item["mission_run_id"] for item in mission_runs],
            "surface": channel_events[0]["surface"] if channel_events else None,
            "channel": channel_events[0]["channel"] if channel_events else (mission_intents[0]["channel"] if mission_intents else None),
            "conversation_key": channel_events[0]["conversation_key"] if channel_events else None,
            "first_created_at": min(created_values) if created_values else None,
            "last_created_at": max(created_values) if created_values else None,
            "counts": {
                "channel_events": len(channel_events),
                "gateway_dispatches": len(gateway_dispatches),
                "mission_intents": len(mission_intents),
                "routing_decisions": len(routing_decisions),
                "routing_traces": len(routing_traces),
                "mission_runs": len(mission_runs),
                "debug_replays": len(debug_replays),
                "dead_letters": len(dead_letters),
                "incidents": len(incidents),
                "eval_runs": len(eval_runs),
                "trace_edges": len(trace_edges),
            },
        }

        payload.update(
            {
                "found": True,
                "summary": summary,
                "channel_events": channel_events,
                "mission_intents": mission_intents,
                "routing_decisions": routing_decisions,
                "routing_traces": routing_traces,
                "mission_runs": mission_runs,
                "gateway_dispatches": gateway_dispatches,
                "debug_replays": debug_replays,
                "dead_letters": dead_letters,
                "incidents": incidents,
                "eval_runs": eval_runs,
                "trace_edges": trace_edges,
            }
        )
        return payload

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
