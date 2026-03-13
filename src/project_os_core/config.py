from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .models import ExecutionPolicy, ForbiddenZonePolicy, StorageRoots


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _expand_path(value: str) -> str:
    return str(Path(os.path.expandvars(os.path.expanduser(value))).resolve(strict=False))


@dataclass(slots=True)
class RuntimeConfig:
    repo_root: Path
    storage_roots: StorageRoots
    forbidden_zone_policy: ForbiddenZonePolicy
    secret_config: SecretConfig
    embedding_policy: EmbeddingPolicy
    execution_policy: ExecutionPolicy


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
        },
    }


def _load_runtime_policy(root: Path, policy_path: str | Path | None = None) -> tuple[SecretConfig, EmbeddingPolicy, ExecutionPolicy]:
    env_override = os.getenv("PROJECT_OS_RUNTIME_POLICY")
    chosen = Path(policy_path) if policy_path else (Path(env_override) if env_override else None)
    if chosen is None:
        local = root / "config" / "runtime_policy.local.json"
        example = root / "config" / "runtime_policy.example.json"
        chosen = local if local.exists() else example

    payload = _runtime_policy_defaults()
    if chosen.exists():
        loaded = json.loads(chosen.read_text(encoding="utf-8"))
        for key in ("secret_config", "embedding_policy", "execution_policy"):
            if key in loaded and isinstance(loaded[key], dict):
                payload[key].update(loaded[key])

    secret_payload = dict(payload["secret_config"])
    secret_payload["local_fallback_path"] = _expand_path(str(secret_payload["local_fallback_path"]))
    secret_config = SecretConfig(**secret_payload)
    embedding_policy = EmbeddingPolicy(**payload["embedding_policy"])
    execution_policy = ExecutionPolicy(**payload["execution_policy"])
    return secret_config, embedding_policy, execution_policy


def load_runtime_config(config_path: str | Path | None = None, policy_path: str | Path | None = None) -> RuntimeConfig:
    root = repo_root()
    env_override = os.getenv("PROJECT_OS_STORAGE_CONFIG")
    chosen = Path(config_path) if config_path else (Path(env_override) if env_override else None)

    if chosen is None:
        local = root / "config" / "storage_roots.local.json"
        example = root / "config" / "storage_roots.example.json"
        chosen = local if local.exists() else example

    payload = json.loads(Path(chosen).read_text(encoding="utf-8"))
    storage_roots = _storage_from_dict(payload)
    policy = ForbiddenZonePolicy(roots=[storage_roots.archive_do_not_touch_root])
    secret_config, embedding_policy, execution_policy = _load_runtime_policy(root, policy_path)
    return RuntimeConfig(
        repo_root=root,
        storage_roots=storage_roots,
        forbidden_zone_policy=policy,
        secret_config=secret_config,
        embedding_policy=embedding_policy,
        execution_policy=execution_policy,
    )
