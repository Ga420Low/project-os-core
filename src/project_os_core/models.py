from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class MemoryTier(str, Enum):
    HOT = "hot"
    WARM = "warm"
    COLD = "cold"


class MemoryType(str, Enum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"
    EMOTIONAL = "emotional"
    REFLECTIVE = "reflective"


class MissionStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"


class MissionExecutionClass(str, Enum):
    DETERMINISTIC = "deterministic"
    ASSISTED = "assisted"
    SUPERVISED = "supervised"
    BLOCKED = "blocked"


class RuntimeVerdict(str, Enum):
    READY = "ready"
    DEGRADED = "degraded"
    BLOCKED = "blocked"
    AWAY_FROM_TARGET = "away_from_target"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ActionRiskClass(str, Enum):
    READ_ONLY = "read_only"
    SAFE_WRITE = "safe_write"
    DESTRUCTIVE = "destructive"
    EXCEPTIONAL = "exceptional"


class CostClass(str, Enum):
    CHEAP = "cheap"
    STANDARD = "standard"
    HARD = "hard"
    EXCEPTIONAL = "exceptional"


class ModelRouteClass(str, Enum):
    FAST = "fast"
    LOCAL = "local"
    API = "api"


class SensitivityClass(str, Enum):
    S1 = "s1_passthrough"
    S2 = "s2_desensitize"
    S3 = "s3_local"


class OperatorMessageKind(str, Enum):
    CHAT = "chat"
    STATUS_REQUEST = "status_request"
    TASKING = "tasking"
    IDEA = "idea"
    DECISION = "decision"
    NOTE = "note"
    APPROVAL = "approval"
    ARTIFACT_REF = "artifact_ref"


class PromotionAction(str, Enum):
    PROMOTE = "promote"
    SKIP = "skip"


class AgentRole(str, Enum):
    OPERATOR_CONCIERGE = "operator_concierge"
    PLANNER = "planner"
    MEMORY_CURATOR = "memory_curator"
    CRITIC = "critic"
    GUARDIAN = "guardian"
    EXECUTOR_COORDINATOR = "executor_coordinator"


class ApiRunMode(str, Enum):
    AUDIT = "audit"
    DESIGN = "design"
    PATCH_PLAN = "patch_plan"
    GENERATE_PATCH = "generate_patch"


class ApiRunStatus(str, Enum):
    PREPARED = "prepared"
    AWAITING_GO = "awaiting_go"
    RUNNING = "running"
    CLARIFICATION_REQUIRED = "clarification_required"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"
    STOPPED = "stopped"
    REVIEWED = "reviewed"


class ApiRunReviewVerdict(str, Enum):
    ACCEPTED = "accepted"
    ACCEPTED_WITH_RESERVES = "accepted_with_reserves"
    NEEDS_REVISION = "needs_revision"
    NEEDS_CLARIFICATION = "needs_clarification"
    REJECTED = "rejected"


class DecisionStatus(str, Enum):
    CONFIRMED = "confirmed"
    CHANGED = "changed"


class LearningSignalKind(str, Enum):
    PATCH_REJECTED = "patch_rejected"
    PATCH_ACCEPTED = "patch_accepted"
    ISSUE_RESOLVED = "issue_resolved"
    LOOP_DETECTED = "loop_detected"
    CAPABILITY_DRIFT = "capability_drift"
    REFRESH_NEEDED = "refresh_needed"
    DECISION_PROMOTED = "decision_promoted"
    NOISE_DETECTED = "noise_detected"


class CommunicationMode(str, Enum):
    DISCUSSION = "discussion"
    ARCHITECT = "architect"
    BUILDER = "builder"
    REVIEWER = "reviewer"
    GUARDIAN = "guardian"
    INCIDENT = "incident"


class RunSpeechPolicy(str, Enum):
    SILENT_UNTIL_TERMINAL_STATE = "silent_until_terminal_state"
    PHASE_MARKERS_ONLY = "phase_markers_only"
    DIALOGUE_RICH = "dialogue_rich"


class OperatorAudience(str, Enum):
    NON_DEVELOPER = "non_developer"
    TECHNICAL = "technical"


class DiscordChannelClass(str, Enum):
    PILOTAGE = "pilotage"
    RUNS_LIVE = "runs_live"
    APPROVALS = "approvals"
    INCIDENTS = "incidents"
    MISSION_THREAD = "mission_thread"
    UNKNOWN = "unknown"


class RunContractStatus(str, Enum):
    PREPARED = "prepared"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"


class RunLifecycleEventKind(str, Enum):
    RUN_STARTED = "run_started"
    CLARIFICATION_REQUIRED = "clarification_required"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    RUN_REVIEWED = "run_reviewed"
    CONTRACT_PROPOSED = "contract_proposed"
    CONTRACT_APPROVED = "contract_approved"
    CONTRACT_REJECTED = "contract_rejected"
    BUDGET_ALERT = "budget_alert"
    RUN_RELAUNCHED = "run_relaunched"


class OperatorChannelHint(str, Enum):
    RUNS_LIVE = "runs_live"
    APPROVALS = "approvals"
    INCIDENTS = "incidents"


class OperatorDeliveryStatus(str, Enum):
    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"
    SKIPPED = "skipped"
    EXPIRED = "expired"


def to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {key: to_jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    return value


@dataclass(slots=True)
class StorageRoots:
    runtime_root: str
    memory_hot_root: str
    memory_warm_root: str
    index_root: str
    session_root: str
    cache_root: str
    archive_drive: str
    archive_do_not_touch_root: str
    archive_root: str
    archive_episodes_root: str
    archive_evidence_root: str
    archive_screens_root: str
    archive_reports_root: str
    archive_logs_root: str
    archive_snapshots_root: str


@dataclass(slots=True)
class ForbiddenZonePolicy:
    roots: list[str]
    mode: Literal["deny_subtree"] = "deny_subtree"


@dataclass(slots=True)
class ArtifactPointer:
    artifact_id: str
    artifact_kind: str
    storage_tier: MemoryTier
    path: str
    checksum_sha256: str | None = None
    size_bytes: int | None = None
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class MemoryRecord:
    memory_id: str
    user_id: str
    content: str
    memory_type: MemoryType
    tier: MemoryTier
    project_id: str | None = None
    mission_id: str | None = None
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    openmemory_id: str | None = None
    archived_artifact_path: str | None = None
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class RetrievalContext:
    query: str
    user_id: str
    project_id: str | None = None
    mission_id: str | None = None
    tags: list[str] = field(default_factory=list)
    limit: int = 5
    include_private_full: bool = False


@dataclass(slots=True)
class ConversationThreadRef:
    thread_id: str
    channel: str
    external_thread_id: str | None = None
    parent_thread_id: str | None = None
    title: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class OperatorAttachment:
    attachment_id: str
    name: str
    kind: str
    mime_type: str | None = None
    path: str | None = None
    url: str | None = None
    size_bytes: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class OperatorMessage:
    message_id: str
    actor_id: str
    channel: str
    text: str
    thread_ref: ConversationThreadRef
    kind: OperatorMessageKind | None = None
    attachments: list[OperatorAttachment] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class ChannelEvent:
    event_id: str
    surface: str
    event_type: str
    message: OperatorMessage
    raw_payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class OperatorEnvelope:
    envelope_id: str
    actor_id: str
    channel: str
    objective: str
    target_profile: str | None = None
    requested_worker: str | None = None
    requested_risk_class: ActionRiskClass | None = None
    communication_mode: CommunicationMode = CommunicationMode.DISCUSSION
    operator_language: str = "fr"
    audience: OperatorAudience = OperatorAudience.NON_DEVELOPER
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class OperatorReply:
    reply_id: str
    channel: str
    envelope_id: str
    thread_ref: ConversationThreadRef
    summary: str
    mission_run_id: str | None = None
    decision_id: str | None = None
    reply_kind: str = "ack"
    communication_mode: CommunicationMode = CommunicationMode.DISCUSSION
    operator_language: str = "fr"
    audience: OperatorAudience = OperatorAudience.NON_DEVELOPER
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class MissionIntent:
    intent_id: str
    source: str
    actor_id: str
    channel: str
    objective: str
    target_profile: str | None = None
    requested_worker: str | None = None
    requested_risk_class: ActionRiskClass | None = None
    communication_mode: CommunicationMode = CommunicationMode.DISCUSSION
    operator_language: str = "fr"
    audience: OperatorAudience = OperatorAudience.NON_DEVELOPER
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class Checkpoint:
    checkpoint_id: str
    mission_run_id: str
    label: str
    graph_state: dict[str, Any]
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class MissionRun:
    mission_run_id: str
    intent_id: str
    objective: str
    profile_name: str | None
    parent_mission_id: str | None = None
    step_index: int = 0
    total_steps: int = 1
    status: MissionStatus = MissionStatus.QUEUED
    execution_class: MissionExecutionClass | None = None
    routing_decision_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class HumanArtifact:
    artifact_id: str
    source_event_id: str
    thread_ref: ConversationThreadRef
    actor_id: str
    kind: str
    text_excerpt: str | None = None
    attachment: OperatorAttachment | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class ConversationMemoryCandidate:
    candidate_id: str
    source_event_id: str
    thread_ref: ConversationThreadRef
    actor_id: str
    classification: OperatorMessageKind
    summary: str
    content: str
    tags: list[str] = field(default_factory=list)
    tier: MemoryTier = MemoryTier.WARM
    should_promote: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class PromotionDecision:
    promotion_decision_id: str
    candidate_id: str
    action: PromotionAction
    reason: str
    memory_type: MemoryType | None = None
    tier: MemoryTier | None = None
    memory_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class GatewayDispatchResult:
    dispatch_id: str
    channel_event_id: str
    envelope_id: str
    intent_id: str
    decision_id: str | None
    mission_run_id: str | None
    operator_reply: OperatorReply
    promoted_memory_ids: list[str] = field(default_factory=list)
    memory_candidate_id: str | None = None
    promotion_decision_id: str | None = None
    discord_run_card: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class DiscordThreadBinding:
    binding_id: str
    binding_key: str
    surface: str
    channel: str
    thread_id: str
    external_thread_id: str | None = None
    parent_thread_id: str | None = None
    channel_event_id: str | None = None
    dispatch_id: str | None = None
    envelope_id: str | None = None
    decision_id: str | None = None
    mission_run_id: str | None = None
    binding_kind: str = "discussion"
    status: str = "active"
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class RuntimeState:
    runtime_state_id: str
    session_id: str
    verdict: RuntimeVerdict
    active_profile: str | None = None
    mission_run_id: str | None = None
    status_summary: str | None = None
    blockers: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    captured_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class SessionState:
    session_id: str
    profile_name: str
    owner: str
    status: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class ApprovalRecord:
    approval_id: str
    requested_by: str
    risk_tier: str
    reason: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    mission_run_id: str | None = None
    expires_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class ActionEvidence:
    evidence_id: str
    session_id: str
    action_name: str
    success: bool
    summary: str | None = None
    result_code: str | None = None
    failure_reason: str | None = None
    policy_verdict: str | None = None
    artifact_count: int = 0
    pre_state: dict[str, Any] = field(default_factory=dict)
    post_state: dict[str, Any] = field(default_factory=dict)
    artifacts: list[ArtifactPointer] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class WorkerRequest:
    request_id: str
    worker_kind: str
    action_name: str
    payload: dict[str, Any] = field(default_factory=dict)
    precheck_required: bool = True
    postcheck_required: bool = True
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class WorkerResult:
    request_id: str
    success: bool
    summary: str
    evidence_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class RoutingAssignment:
    assignment_id: str
    mission_run_id: str
    decision_id: str
    worker_kind: str
    execution_class: MissionExecutionClass
    model_route: ModelRoute
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class ExecutionTicket:
    ticket_id: str
    mission_run_id: str
    assignment_id: str
    worker_kind: str
    action_name: str
    payload: dict[str, Any] = field(default_factory=dict)
    policy_verdict: str | None = None
    status: str = "issued"
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class WorkerDispatchEnvelope:
    dispatch_id: str
    ticket: ExecutionTicket
    worker_request: WorkerRequest
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class ProfileCapability:
    profile_name: str
    capability_names: list[str]
    default_paths: dict[str, str] = field(default_factory=dict)
    allowed_workers: list[str] = field(default_factory=list)
    required_secrets: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ExecutionPolicy:
    default_model: str
    default_reasoning_effort: str
    escalation_reasoning_effort: str
    exceptional_model: str
    daily_soft_limit_eur: float
    monthly_limit_eur: float
    daily_budget_limit_eur: float = 5.0
    loop_detection_window_hours: int = 2
    loop_detection_threshold: int = 3
    deterministic_first: bool = True
    allow_pro_default: bool = False
    secret_mode: str = "infisical_first"
    discord_simple_model: str = "claude-sonnet-4-20250514"
    discord_simple_reasoning_effort: str = "medium"
    operator_language: str = "fr"
    operator_audience: OperatorAudience = OperatorAudience.NON_DEVELOPER
    run_contract_required: bool = True
    default_run_speech_policy: RunSpeechPolicy = RunSpeechPolicy.SILENT_UNTIL_TERMINAL_STATE
    operator_delivery_max_attempts: int = 4
    operator_delivery_retry_base_seconds: int = 30
    operator_delivery_retry_max_seconds: int = 900
    operator_delivery_max_pending: int = 64
    local_model_enabled: bool = False
    local_model_provider: str = "ollama"
    local_model_base_url: str = "http://127.0.0.1:11434"
    local_model_name: str = "local-llm"
    local_model_timeout_seconds: float = 90.0
    local_model_health_timeout_seconds: float = 5.0
    local_model_reasoning_effort: str = "medium"
    proactive_briefing_max_items: int = 3
    privacy_guard_enabled: bool = True
    s3_requires_local_model: bool = True


@dataclass(slots=True)
class ModelRoute:
    provider: str
    model: str | None
    reasoning_effort: str | None
    route_class: CostClass
    route_tier: ModelRouteClass
    allowed: bool
    reason: str


@dataclass(slots=True)
class AdaptiveModelRoute:
    route_id: str
    channel_class: DiscordChannelClass
    communication_mode: CommunicationMode
    message_kind: OperatorMessageKind | None
    provider: str
    model: str | None
    reasoning_effort: str | None
    deterministic_first: bool
    reason: str
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class BudgetState:
    daily_soft_limit_eur: float
    monthly_limit_eur: float
    daily_spend_estimate_eur: float
    monthly_spend_estimate_eur: float
    mission_estimate_eur: float
    mission_cost_class: CostClass
    within_daily_soft: bool
    within_monthly_limit: bool
    route_reason: str


@dataclass(slots=True)
class ApprovalGate:
    required: bool
    approved: bool
    approval_id: str | None = None
    reason: str | None = None


@dataclass(slots=True)
class RoutingDecision:
    decision_id: str
    intent_id: str
    mission_run_id: str | None
    execution_class: MissionExecutionClass
    risk_class: ActionRiskClass
    allowed: bool
    chosen_worker: str | None
    model_route: ModelRoute
    approval_gate: ApprovalGate
    budget_state: BudgetState
    route_reason: str
    communication_mode: CommunicationMode = CommunicationMode.DISCUSSION
    speech_policy: RunSpeechPolicy = RunSpeechPolicy.SILENT_UNTIL_TERMINAL_STATE
    operator_language: str = "fr"
    audience: OperatorAudience = OperatorAudience.NON_DEVELOPER
    adaptive_model_route: AdaptiveModelRoute | None = None
    blocked_reasons: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class RoutingDecisionTrace:
    trace_id: str
    decision_id: str
    runtime_state_id: str | None
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class GraphState:
    graph_state_id: str
    mission_run_id: str
    objective: str
    active_role: AgentRole
    status: str
    role_sequence: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class RoleHandoff:
    handoff_id: str
    mission_run_id: str
    from_role: AgentRole | None
    to_role: AgentRole
    reason: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class ExecutionCheckpoint:
    execution_checkpoint_id: str
    mission_run_id: str
    role: AgentRole
    label: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class RetryDecision:
    retry_decision_id: str
    mission_run_id: str
    role: AgentRole
    attempt_number: int
    retry_allowed: bool
    next_reasoning_effort: str | None
    reason: str
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class MissionOutcome:
    outcome_id: str
    mission_run_id: str
    status: MissionStatus
    summary: str
    produced_artifact_ids: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class BootstrapState:
    bootstrap_state_id: str
    strict_ready: bool
    status: str
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checks: dict[str, Any] = field(default_factory=dict)
    roots: dict[str, str] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class HealthSnapshot:
    snapshot_id: str
    overall_status: str
    payload: dict[str, Any]
    path: str | None = None
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class OpenClawRuntimeRoots:
    runtime_root: str
    state_root: str
    plugin_source_path: str
    plugin_manifest_path: str
    storage_config_path: str
    runtime_policy_path: str


@dataclass(slots=True)
class OpenClawBootstrapReport:
    report_id: str
    install_method: str
    plugin_status: str
    readiness: str
    blocking_reasons: list[str] = field(default_factory=list)
    actionable_fixes: list[str] = field(default_factory=list)
    checks: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class OpenClawDoctorReport:
    report_id: str
    verdict: str
    summary: str
    actionable_fixes: list[str] = field(default_factory=list)
    checks: list[dict[str, Any]] = field(default_factory=list)
    runtime_roots: OpenClawRuntimeRoots | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class OpenClawReplayFixture:
    fixture_id: str
    channel: str
    thread_ref: str
    message_type: str
    attachments: list[str] = field(default_factory=list)
    expected_route: dict[str, Any] = field(default_factory=dict)
    payload_path: str | None = None
    description: str | None = None


@dataclass(slots=True)
class OpenClawReplayResult:
    replay_result_id: str
    fixture_id: str
    dispatch_status: str
    router_verdict: str
    policy_verdict: str
    promoted_memory_count: int = 0
    artifact_count: int = 0
    passed: bool = False
    run_card: dict[str, Any] = field(default_factory=dict)
    evidence_refs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class OpenClawLiveValidationResult:
    validation_id: str
    channel: str
    success: bool
    evidence_refs: list[str] = field(default_factory=list)
    failure_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class OpenClawTruthHealthReport:
    report_id: str
    verdict: str
    summary: str
    channel: str
    actionable_fixes: list[str] = field(default_factory=list)
    checks: list[dict[str, Any]] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class OpenClawTrustAuditReport:
    report_id: str
    verdict: str
    summary: str
    actionable_fixes: list[str] = field(default_factory=list)
    checks: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class ContextSource:
    source_id: str
    path: str
    kind: str
    content: str
    truncated: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ContextPack:
    context_pack_id: str
    mode: ApiRunMode
    objective: str
    branch_name: str
    target_profile: str | None = None
    source_refs: list[ContextSource] = field(default_factory=list)
    repo_state: dict[str, Any] = field(default_factory=dict)
    runtime_facts: dict[str, Any] = field(default_factory=dict)
    constraints: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    skill_tags: list[str] = field(default_factory=list)
    artifact_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class MegaPromptTemplate:
    prompt_template_id: str
    context_pack_id: str
    mode: ApiRunMode
    agent_identity: str
    skill_tags: list[str]
    output_contract: list[str]
    rendered_prompt: str
    model: str
    reasoning_effort: str
    artifact_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class ApiRunRequest:
    run_request_id: str
    context_pack_id: str
    prompt_template_id: str
    mode: ApiRunMode
    objective: str
    branch_name: str
    target_profile: str | None = None
    mission_chain_id: str | None = None
    mission_step_index: int | None = None
    skill_tags: list[str] = field(default_factory=list)
    expected_outputs: list[str] = field(default_factory=list)
    coding_lane: str = "repo_cli"
    desktop_lane: str = "future_computer_use"
    communication_mode: CommunicationMode = CommunicationMode.BUILDER
    speech_policy: RunSpeechPolicy = RunSpeechPolicy.SILENT_UNTIL_TERMINAL_STATE
    operator_language: str = "fr"
    audience: OperatorAudience = OperatorAudience.NON_DEVELOPER
    run_contract_required: bool = True
    contract_id: str | None = None
    status: ApiRunStatus = ApiRunStatus.PREPARED
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class ApiRunArtifact:
    artifact_id: str
    run_id: str
    artifact_kind: str
    path: str
    checksum_sha256: str | None = None
    size_bytes: int | None = None
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class ApiRunResult:
    run_id: str
    run_request_id: str
    model: str
    mode: ApiRunMode
    status: ApiRunStatus
    structured_output: dict[str, Any] = field(default_factory=dict)
    raw_output_path: str | None = None
    prompt_artifact_path: str | None = None
    result_artifact_path: str | None = None
    estimated_cost_eur: float = 0.0
    usage: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class ApiRunReview:
    review_id: str
    run_id: str
    verdict: ApiRunReviewVerdict
    reviewer: str
    findings: list[str] = field(default_factory=list)
    accepted_changes: list[str] = field(default_factory=list)
    followup_actions: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class RunContract:
    contract_id: str
    context_pack_id: str
    prompt_template_id: str
    mode: ApiRunMode
    objective: str
    branch_name: str
    target_profile: str | None = None
    model: str = "gpt-5.4"
    reasoning_effort: str = "high"
    communication_mode: CommunicationMode = CommunicationMode.BUILDER
    speech_policy: RunSpeechPolicy = RunSpeechPolicy.SILENT_UNTIL_TERMINAL_STATE
    operator_language: str = "fr"
    audience: OperatorAudience = OperatorAudience.NON_DEVELOPER
    expected_outputs: list[str] = field(default_factory=list)
    summary: str = ""
    non_goals: list[str] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)
    estimated_cost_eur: float = 0.0
    founder_decision: str | None = None
    founder_decision_at: str | None = None
    status: RunContractStatus = RunContractStatus.PREPARED
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class CompletionReport:
    report_id: str
    run_id: str
    verdict: str
    summary: str
    done_items: list[str] = field(default_factory=list)
    test_summary: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    next_action: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class BlockageReport:
    report_id: str
    run_id: str
    cause: str
    impact: str
    choices: list[str] = field(default_factory=list)
    recommendation: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class ClarificationReport:
    report_id: str
    run_id: str
    cause: str
    impact: str
    question_for_founder: str
    recommended_contract_change: str
    requires_reapproval: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class RunLifecycleEvent:
    lifecycle_event_id: str
    run_id: str
    run_request_id: str
    kind: RunLifecycleEventKind
    title: str
    summary: str
    contract_id: str | None = None
    branch_name: str | None = None
    mode: ApiRunMode | None = None
    channel_hint: OperatorChannelHint = OperatorChannelHint.RUNS_LIVE
    status: ApiRunStatus | None = None
    phase: str | None = None
    blocking_question: str | None = None
    recommended_action: str | None = None
    requires_reapproval: bool = False
    artifact_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class OperatorDelivery:
    delivery_id: str
    lifecycle_event_id: str
    adapter: str
    surface: str
    channel_hint: OperatorChannelHint
    status: OperatorDeliveryStatus = OperatorDeliveryStatus.PENDING
    attempts: int = 0
    payload: dict[str, Any] = field(default_factory=dict)
    last_error: str | None = None
    next_attempt_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class LearningSignal:
    signal_id: str
    kind: LearningSignalKind
    severity: str
    summary: str
    source_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class NoiseSignal:
    noise_signal_id: str
    run_id: str
    reason: str
    evidence: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class DecisionRecord:
    decision_record_id: str
    status: DecisionStatus
    scope: str
    summary: str
    source_run_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class LoopSignal:
    loop_signal_id: str
    repeated_pattern: str
    impacted_area: str
    recommended_reset: str
    source_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class RefreshRecommendation:
    refresh_recommendation_id: str
    cause: str
    context_to_reload: list[str] = field(default_factory=list)
    next_step: str = ""
    source_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class DatasetCandidate:
    dataset_candidate_id: str
    source_type: str
    quality_score: float
    export_ready: bool
    source_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class EvalCandidate:
    eval_candidate_id: str
    scenario: str
    target_system: str
    expected_behavior: str
    source_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class DiscordRunCard:
    card_id: str
    run_id: str | None
    channel_class: DiscordChannelClass
    title: str
    status: str
    summary: str
    branch_name: str | None = None
    phase: str | None = None
    estimated_cost_eur: float = 0.0
    verdict: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)
