from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .models import ExecutionPolicy, ForbiddenZonePolicy, OperatorAudience, RunSpeechPolicy, StorageRoots


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _expand_path(value: str) -> str:
    return str(Path(os.path.expandvars(os.path.expanduser(value))).resolve(strict=False))


@dataclass(slots=True)
class RuntimeConfig:
    repo_root: Path
    storage_config_path: Path
    runtime_policy_path: Path
    storage_roots: StorageRoots
    forbidden_zone_policy: ForbiddenZonePolicy
    secret_config: SecretConfig
    embedding_policy: EmbeddingPolicy
    execution_policy: ExecutionPolicy
    openclaw_config: OpenClawConfig
    api_dashboard_config: ApiDashboardConfig
    tier_manager_config: TierManagerConfig


@dataclass(slots=True)
class SecretConfig:
    mode: str = "infisical_first"
    required_secret_names: list[str] = field(default_factory=lambda: ["OPENAI_API_KEY"])
    local_fallback_path: str = field(default_factory=lambda: _expand_path("%LOCALAPPDATA%/ProjectOS/secrets.json"))
    infisical_environment: str = "dev"
    infisical_project_id: str | None = None
    infisical_path: str = "/"
    infisical_token_env: str = "INFISICAL_TOKEN"
    infisical_universal_auth_client_id_env: str = "INFISICAL_UNIVERSAL_AUTH_CLIENT_ID"
    infisical_universal_auth_client_secret_env: str = "INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET"


@dataclass(slots=True)
class EmbeddingPolicy:
    provider_mode: str = "auto"
    quality: str = "balanced"
    default_openai_model: str = "text-embedding-3-small"
    max_openai_model: str = "text-embedding-3-large"
    local_model: str = "local-hash-v1"
    local_dimensions: int = 64


@dataclass(slots=True)
class OpenClawConfig:
    binary_command: str = "openclaw"
    runtime_root: str = field(default_factory=lambda: _expand_path("D:/ProjectOS/openclaw-runtime"))
    state_root: str = field(default_factory=lambda: _expand_path("D:/ProjectOS/runtime/openclaw"))
    plugin_id: str = "project-os-gateway-adapter"
    plugin_source_path: str | None = None
    enabled_channels: list[str] = field(default_factory=lambda: ["discord", "webchat"])
    send_ack_replies: bool = False
    timeout_ms: int = 45000
    require_replay_before_live: bool = True


@dataclass(slots=True)
class ApiDashboardConfig:
    host: str = "127.0.0.1"
    port: int = 8765
    limit: int = 8
    refresh_seconds: int = 4
    auto_start: bool = True
    auto_open_browser: bool = True
    require_visible_ui: bool = True
    beacon_wait_seconds: float = 12.0
    recent_beacon_grace_seconds: int = 1800
    founder_approval_grace_seconds: int = 1800


@dataclass(slots=True)
class TierManagerConfig:
    enabled: bool = True
    auto_archive_on_write: bool = True
    warm_min_age_hours: int = 6
    keep_latest_warm_records: int = 8
    max_archive_batch_size: int = 32


def _storage_from_dict(payload: dict[str, str]) -> StorageRoots:
    return StorageRoots(**payload)


def _runtime_policy_defaults() -> dict[str, object]:
    return {
        "secret_config": {
            "mode": "infisical_first",
            "required_secret_names": ["OPENAI_API_KEY"],
            "local_fallback_path": _expand_path("%LOCALAPPDATA%/ProjectOS/secrets.json"),
            "infisical_environment": "dev",
            "infisical_project_id": None,
            "infisical_path": "/",
            "infisical_token_env": "INFISICAL_TOKEN",
            "infisical_universal_auth_client_id_env": "INFISICAL_UNIVERSAL_AUTH_CLIENT_ID",
            "infisical_universal_auth_client_secret_env": "INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET",
        },
        "embedding_policy": {
            "provider_mode": "auto",
            "quality": "balanced",
            "default_openai_model": "text-embedding-3-small",
            "max_openai_model": "text-embedding-3-large",
            "local_model": "local-hash-v1",
            "local_dimensions": 64,
        },
        "execution_policy": {
            "default_model": "gpt-5.4",
            "default_reasoning_effort": "high",
            "escalation_reasoning_effort": "xhigh",
            "exceptional_model": "gpt-5.4-pro",
            "daily_soft_limit_eur": 1.5,
            "monthly_limit_eur": 50.0,
            "deterministic_first": True,
            "allow_pro_default": False,
            "secret_mode": "infisical_first",
            "discord_simple_reasoning_effort": "medium",
            "operator_language": "fr",
            "operator_audience": OperatorAudience.NON_DEVELOPER.value,
            "run_contract_required": True,
            "default_run_speech_policy": RunSpeechPolicy.SILENT_UNTIL_TERMINAL_STATE.value,
            "operator_delivery_max_attempts": 4,
            "operator_delivery_retry_base_seconds": 30,
            "operator_delivery_retry_max_seconds": 900,
            "operator_delivery_max_pending": 64,
        },
        "openclaw_config": {
            "binary_command": "openclaw",
            "runtime_root": _expand_path("D:/ProjectOS/openclaw-runtime"),
            "state_root": _expand_path("D:/ProjectOS/runtime/openclaw"),
            "plugin_id": "project-os-gateway-adapter",
            "plugin_source_path": None,
            "enabled_channels": ["discord", "webchat"],
            "send_ack_replies": False,
            "timeout_ms": 45000,
            "require_replay_before_live": True,
        },
        "api_dashboard_config": {
            "host": "127.0.0.1",
            "port": 8765,
            "limit": 8,
            "refresh_seconds": 4,
            "auto_start": True,
            "auto_open_browser": True,
            "require_visible_ui": True,
            "beacon_wait_seconds": 12.0,
            "recent_beacon_grace_seconds": 1800,
            "founder_approval_grace_seconds": 1800,
        },
        "tier_manager_config": {
            "enabled": True,
            "auto_archive_on_write": True,
            "warm_min_age_hours": 6,
            "keep_latest_warm_records": 8,
            "max_archive_batch_size": 32,
        },
    }


def _load_runtime_policy(
    root: Path,
    policy_path: str | Path | None = None,
) -> tuple[SecretConfig, EmbeddingPolicy, ExecutionPolicy, OpenClawConfig, ApiDashboardConfig, TierManagerConfig]:
    env_override = os.getenv("PROJECT_OS_RUNTIME_POLICY")
    chosen = Path(policy_path) if policy_path else (Path(env_override) if env_override else None)
    if chosen is None:
        local = root / "config" / "runtime_policy.local.json"
        example = root / "config" / "runtime_policy.example.json"
        chosen = local if local.exists() else example

    payload = _runtime_policy_defaults()
    if chosen.exists():
        loaded = json.loads(chosen.read_text(encoding="utf-8"))
        for key in (
            "secret_config",
            "embedding_policy",
            "execution_policy",
            "openclaw_config",
            "api_dashboard_config",
            "tier_manager_config",
        ):
            if key in loaded and isinstance(loaded[key], dict):
                payload[key].update(loaded[key])

    secret_payload = dict(payload["secret_config"])
    secret_payload["local_fallback_path"] = _expand_path(str(secret_payload["local_fallback_path"]))
    secret_config = SecretConfig(**secret_payload)
    embedding_policy = EmbeddingPolicy(**payload["embedding_policy"])
    execution_payload = dict(payload["execution_policy"])
    execution_payload["operator_audience"] = OperatorAudience(str(execution_payload["operator_audience"]))
    execution_payload["default_run_speech_policy"] = RunSpeechPolicy(str(execution_payload["default_run_speech_policy"]))
    execution_policy = ExecutionPolicy(**execution_payload)
    openclaw_payload = dict(payload["openclaw_config"])
    openclaw_payload["runtime_root"] = _expand_path(str(openclaw_payload["runtime_root"]))
    openclaw_payload["state_root"] = _expand_path(str(openclaw_payload["state_root"]))
    plugin_source_path = openclaw_payload.get("plugin_source_path")
    if plugin_source_path:
        openclaw_payload["plugin_source_path"] = _expand_path(str(plugin_source_path))
    openclaw_config = OpenClawConfig(**openclaw_payload)
    api_dashboard_config = ApiDashboardConfig(**payload["api_dashboard_config"])
    tier_manager_config = TierManagerConfig(**payload["tier_manager_config"])
    return secret_config, embedding_policy, execution_policy, openclaw_config, api_dashboard_config, tier_manager_config


def load_runtime_config(config_path: str | Path | None = None, policy_path: str | Path | None = None) -> RuntimeConfig:
    root = repo_root()
    env_override = os.getenv("PROJECT_OS_STORAGE_CONFIG")
    chosen = Path(config_path) if config_path else (Path(env_override) if env_override else None)

    if chosen is None:
        local = root / "config" / "storage_roots.local.json"
        example = root / "config" / "storage_roots.example.json"
        chosen = local if local.exists() else example

    payload = json.loads(Path(chosen).read_text(encoding="utf-8"))
    chosen_storage_path = Path(chosen).resolve(strict=False)
    chosen_policy_path = Path(policy_path).resolve(strict=False) if policy_path else (
        root / "config" / ("runtime_policy.local.json" if (root / "config" / "runtime_policy.local.json").exists() else "runtime_policy.example.json")
    ).resolve(strict=False)
    storage_roots = _storage_from_dict(payload)
    policy = ForbiddenZonePolicy(roots=[storage_roots.archive_do_not_touch_root])
    secret_config, embedding_policy, execution_policy, openclaw_config, api_dashboard_config, tier_manager_config = _load_runtime_policy(root, policy_path)
    return RuntimeConfig(
        repo_root=root,
        storage_config_path=chosen_storage_path,
        runtime_policy_path=chosen_policy_path,
        storage_roots=storage_roots,
        forbidden_zone_policy=policy,
        secret_config=secret_config,
        embedding_policy=embedding_policy,
        execution_policy=execution_policy,
        openclaw_config=openclaw_config,
        api_dashboard_config=api_dashboard_config,
        tier_manager_config=tier_manager_config,
    )
