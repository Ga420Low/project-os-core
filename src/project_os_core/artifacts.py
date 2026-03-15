from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .models import ArtifactPointer, MemoryTier, new_id
from .paths import PathPolicy, ProjectPaths


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _folder_for(paths: ProjectPaths, artifact_kind: str, storage_tier: MemoryTier) -> Path:
    if storage_tier is MemoryTier.COLD:
        if artifact_kind in {"evidence", "action_evidence"}:
            return paths.archive_evidence_root
        if artifact_kind in {"screen", "screenshot"}:
            return paths.archive_screens_root
        if artifact_kind == "report":
            return paths.archive_reports_root
        if artifact_kind == "log":
            return paths.archive_logs_root
        if artifact_kind == "snapshot":
            return paths.archive_snapshots_root
        return paths.archive_episodes_root
    if storage_tier is MemoryTier.WARM:
        return paths.memory_artifact_root / artifact_kind
    return paths.runtime_artifact_root / artifact_kind


def write_json_artifact(
    *,
    paths: ProjectPaths,
    path_policy: PathPolicy,
    owner_id: str,
    artifact_kind: str,
    storage_tier: MemoryTier,
    payload: Any,
) -> ArtifactPointer:
    folder = _folder_for(paths, artifact_kind, storage_tier)
    folder.mkdir(parents=True, exist_ok=True)
    destination = path_policy.ensure_allowed_write(folder / f"{owner_id}.json")
    encoded = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True).encode("utf-8")
    temp_path = destination.with_suffix(f"{destination.suffix}.tmp")
    temp_path.write_bytes(encoded)
    temp_path.replace(destination)
    pointer = ArtifactPointer(
        artifact_id=new_id("artifact"),
        artifact_kind=artifact_kind,
        storage_tier=storage_tier,
        path=str(destination),
        checksum_sha256=_sha256(encoded),
        size_bytes=len(encoded),
    )
    validate_artifact_pointer(pointer, path_policy)
    return pointer


def write_text_artifact(
    *,
    paths: ProjectPaths,
    path_policy: PathPolicy,
    owner_id: str,
    artifact_kind: str,
    storage_tier: MemoryTier,
    text: str,
    suffix: str = ".md",
) -> ArtifactPointer:
    folder = _folder_for(paths, artifact_kind, storage_tier)
    folder.mkdir(parents=True, exist_ok=True)
    destination = path_policy.ensure_allowed_write(folder / f"{owner_id}{suffix}")
    encoded = str(text).encode("utf-8")
    temp_path = destination.with_suffix(f"{destination.suffix}.tmp")
    temp_path.write_bytes(encoded)
    temp_path.replace(destination)
    pointer = ArtifactPointer(
        artifact_id=new_id("artifact"),
        artifact_kind=artifact_kind,
        storage_tier=storage_tier,
        path=str(destination),
        checksum_sha256=_sha256(encoded),
        size_bytes=len(encoded),
    )
    validate_artifact_pointer(pointer, path_policy)
    return pointer


def validate_artifact_pointer(pointer: ArtifactPointer, path_policy: PathPolicy) -> None:
    artifact_path = path_policy.ensure_allowed_write(pointer.path)
    payload = artifact_path.read_bytes()
    checksum = _sha256(payload)
    if pointer.size_bytes is not None and artifact_path.stat().st_size != pointer.size_bytes:
        raise ValueError(f"Artifact size mismatch for {artifact_path}")
    if pointer.checksum_sha256 and checksum != pointer.checksum_sha256:
        raise ValueError(f"Artifact checksum mismatch for {artifact_path}")
