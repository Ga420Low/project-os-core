from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from ..config import MemoryBlocksConfig
from ..database import CanonicalDatabase, dump_json
from ..models import MemoryBlock, MemoryBlockAccessPolicy, new_id, to_jsonable, utc_now_iso
from ..paths import PathPolicy, ProjectPaths


DEFAULT_SHARED_BLOCKS: tuple[dict[str, Any], ...] = (
    {
        "block_name": "system/founder.md",
        "owner_role": "guardian",
        "access_policy": {
            "readers": ["discord", "guardian", "memory_curator", "executor_coordinator", "planner"],
            "writers": ["guardian", "memory_curator", "system"],
            "surfaces": ["discord", "cli", "scheduler"],
            "sensitivity": "s2_desensitize",
        },
        "content": "# Founder\n\nFacts durables sur le fondateur, ses preferences et les garde-fous.\n",
    },
    {
        "block_name": "system/project_identity.md",
        "owner_role": "guardian",
        "access_policy": {
            "readers": ["discord", "guardian", "memory_curator", "planner", "executor_coordinator"],
            "writers": ["guardian", "system"],
            "surfaces": ["discord", "cli", "scheduler"],
            "sensitivity": "s1_passthrough",
        },
        "content": "# Project Identity\n\nProject OS reste le cerveau. OpenClaw reste la surface operateur.\n",
    },
    {
        "block_name": "runtime/mission_state.md",
        "owner_role": "executor_coordinator",
        "access_policy": {
            "readers": ["discord", "guardian", "memory_curator", "executor_coordinator", "planner"],
            "writers": ["executor_coordinator", "memory_curator", "system"],
            "surfaces": ["discord", "cli", "scheduler"],
            "sensitivity": "s1_passthrough",
        },
        "content": "# Mission State\n\nAucun etat mission consolide pour le moment.\n",
    },
    {
        "block_name": "runtime/discord_state.md",
        "owner_role": "operator_concierge",
        "access_policy": {
            "readers": ["discord", "guardian", "memory_curator", "operator_concierge"],
            "writers": ["operator_concierge", "memory_curator", "system"],
            "surfaces": ["discord", "cli", "scheduler"],
            "sensitivity": "s1_passthrough",
        },
        "content": "# Discord State\n\nAucun contexte Discord consolide pour le moment.\n",
    },
    {
        "block_name": "runtime/uefn_state.md",
        "owner_role": "executor_coordinator",
        "access_policy": {
            "readers": ["guardian", "memory_curator", "executor_coordinator"],
            "writers": ["executor_coordinator", "memory_curator", "system"],
            "surfaces": ["cli", "scheduler"],
            "sensitivity": "s2_desensitize",
        },
        "content": "# UEFN State\n\nAucun etat UEFN consolide pour le moment.\n",
    },
    {
        "block_name": "profiles/founder_stable_profile.md",
        "owner_role": "guardian",
        "access_policy": {
            "readers": ["discord", "guardian", "memory_curator", "planner", "executor_coordinator"],
            "writers": ["guardian", "memory_curator", "system"],
            "surfaces": ["discord", "cli", "scheduler"],
            "sensitivity": "s2_desensitize",
        },
        "content": "# Founder Stable Profile\n\nPreferer les verites durables et les decisions confirmee.\n",
    },
    {
        "block_name": "profiles/recent_operating_context.md",
        "owner_role": "memory_curator",
        "access_policy": {
            "readers": ["discord", "guardian", "memory_curator", "planner", "executor_coordinator"],
            "writers": ["memory_curator", "system"],
            "surfaces": ["discord", "cli", "scheduler"],
            "sensitivity": "s1_passthrough",
        },
        "content": "# Recent Operating Context\n\nAucun contexte recent consolide pour le moment.\n",
    },
    {
        "block_name": "skills/README.md",
        "owner_role": "planner",
        "access_policy": {
            "readers": ["discord", "guardian", "memory_curator", "planner", "executor_coordinator"],
            "writers": ["planner", "memory_curator", "system"],
            "surfaces": ["discord", "cli", "scheduler"],
            "sensitivity": "s1_passthrough",
        },
        "content": "# Skills\n\nCatalogue memo des skills partagees par Project OS.\n",
    },
)


class MemoryBlockStore:
    def __init__(
        self,
        database: CanonicalDatabase,
        paths: ProjectPaths,
        path_policy: PathPolicy,
        config: MemoryBlocksConfig | None = None,
    ) -> None:
        self.database = database
        self.paths = paths
        self.path_policy = path_policy
        self.config = config or MemoryBlocksConfig()
        self._trace_callback: Callable[..., dict[str, Any]] | None = None

    def attach_tracer(self, trace_callback: Callable[..., dict[str, Any]]) -> None:
        self._trace_callback = trace_callback

    def ensure_default_blocks(self) -> list[MemoryBlock]:
        blocks: list[MemoryBlock] = []
        for item in DEFAULT_SHARED_BLOCKS:
            block = self.upsert_block(
                block_name=str(item["block_name"]),
                content=str(item["content"]),
                owner_role=str(item["owner_role"]),
                access_policy=MemoryBlockAccessPolicy(**item["access_policy"]),
                provenance=["bootstrap:memory_os"],
                updated_by_role="system",
                reason="bootstrap_default",
                surface="scheduler",
                only_if_missing=True,
            )
            blocks.append(block)
        return blocks

    def list_blocks(self) -> list[MemoryBlock]:
        rows = self.database.fetchall("SELECT * FROM memory_blocks ORDER BY block_name ASC")
        return [self._row_to_block(row) for row in rows]

    def get_block(self, block_name: str) -> MemoryBlock:
        normalized = self._normalize_block_name(block_name)
        row = self.database.fetchone("SELECT * FROM memory_blocks WHERE block_name = ?", (normalized,))
        if row is None:
            raise KeyError(f"Unknown memory block: {normalized}")
        return self._row_to_block(row)

    def upsert_block(
        self,
        *,
        block_name: str,
        content: str,
        owner_role: str,
        access_policy: MemoryBlockAccessPolicy | None = None,
        provenance: list[str] | None = None,
        updated_by_role: str | None = None,
        updated_by_run_id: str | None = None,
        reason: str | None = None,
        metadata: dict[str, Any] | None = None,
        surface: str | None = None,
        only_if_missing: bool = False,
    ) -> MemoryBlock:
        normalized = self._normalize_block_name(block_name)
        existing = self.database.fetchone("SELECT * FROM memory_blocks WHERE block_name = ?", (normalized,))
        if only_if_missing and existing is not None:
            return self._row_to_block(existing)
        policy = access_policy or (
            self._row_to_block(existing).access_policy if existing is not None else MemoryBlockAccessPolicy()
        )
        actor_role = updated_by_role or "system"
        effective_surface = self._normalize_surface(surface, actor_role)
        self._assert_write_allowed(
            block_name=normalized,
            actor_role=actor_role,
            policy=policy,
            surface=effective_surface,
        )
        content_size = len(content.encode("utf-8"))
        if content_size > int(self.config.max_block_bytes):
            raise ValueError(
                f"Block '{normalized}' exceeds max_block_bytes={self.config.max_block_bytes} ({content_size} bytes)"
            )
        now = utc_now_iso()
        provenance_items = list(provenance or [])
        if existing is not None:
            previous = json.loads(str(existing["provenance_json"])) if existing["provenance_json"] else []
            for item in previous:
                if item not in provenance_items:
                    provenance_items.append(item)
        policy_json = dump_json(to_jsonable(policy))
        metadata_json = dump_json(dict(metadata or {}))
        hash_sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if existing is not None and self._is_noop_update(
            existing=existing,
            content=content,
            owner_role=owner_role,
            hash_sha256=hash_sha256,
            policy_json=policy_json,
            metadata_json=metadata_json,
            provenance_items=provenance_items,
        ):
            return self._row_to_block(existing)
        path = self._block_path(normalized)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        version = (int(existing["version"]) + 1) if existing is not None else 1
        block_id = str(existing["block_id"]) if existing is not None else new_id("memory_block")
        created_at = str(existing["created_at"]) if existing is not None else now
        payload_metadata = dict(metadata or {})
        self.database.upsert(
            "memory_blocks",
            {
                "block_id": block_id,
                "block_name": normalized,
                "owner_role": owner_role,
                "path": str(path),
                "hash_sha256": hash_sha256,
                "version": version,
                "access_policy_json": policy_json,
                "provenance_json": dump_json(provenance_items),
                "last_updated_by_role": actor_role,
                "last_updated_by_run_id": updated_by_run_id,
                "metadata_json": metadata_json,
                "created_at": created_at,
                "updated_at": now,
            },
            conflict_columns="block_id",
            immutable_columns=["created_at"],
        )
        self.database.upsert(
            "memory_block_revisions",
            {
                "revision_id": new_id("memory_block_rev"),
                "block_id": block_id,
                "block_name": normalized,
                "version": version,
                "path": str(path),
                "hash_sha256": hash_sha256,
                "content": content,
                "content_summary": self._content_summary(content),
                "change_reason": reason,
                "provenance_json": dump_json(provenance_items),
                "updated_by_role": actor_role,
                "updated_by_run_id": updated_by_run_id,
                "created_at": now,
            },
            conflict_columns="revision_id",
            immutable_columns=["created_at"],
        )
        block = self.get_block(normalized)
        self._trace(
            operation="block_write",
            target_type="memory_block",
            target_id=block.block_id,
            detail={
                "block_name": block.block_name,
                "version": block.version,
                "reason": reason,
                "surface": effective_surface,
            },
        )
        return block

    def read_block_content(
        self,
        block_name: str,
        *,
        reader_role: str | None = None,
        surface: str | None = None,
    ) -> str:
        block = self.get_block(block_name)
        actor_role = reader_role or "system"
        effective_surface = self._normalize_surface(surface, actor_role)
        self._assert_read_allowed(block=block, actor_role=actor_role, surface=effective_surface)
        content = Path(block.path).read_text(encoding="utf-8")
        self._trace(
            operation="block_read",
            target_type="memory_block",
            target_id=block.block_id,
            detail={"block_name": block.block_name, "surface": effective_surface},
        )
        return content

    def refresh_runtime_blocks(self) -> dict[str, Any]:
        updates: dict[str, Any] = {}
        latest_runtime = self.database.fetchone(
            "SELECT * FROM runtime_states ORDER BY captured_at DESC LIMIT 1"
        )
        latest_snapshot = self.database.fetchone(
            "SELECT * FROM session_snapshots ORDER BY created_at DESC LIMIT 1"
        )
        latest_channel = self.database.fetchone(
            "SELECT channel, conversation_key, message_json, created_at FROM channel_events ORDER BY created_at DESC LIMIT 1"
        )
        latest_confirmed_decisions = self.database.fetchall(
            """
            SELECT status, scope, summary, updated_at
            FROM decision_records
            WHERE status IN ('confirmed', 'changed')
            ORDER BY updated_at DESC
            LIMIT 8
            """
        )
        latest_runs = self.database.fetchall(
            """
            SELECT mission_run_id, objective, profile_name, status, updated_at
            FROM mission_runs
            ORDER BY updated_at DESC
            LIMIT 5
            """
        )
        mission_lines = ["# Mission State", ""]
        if latest_runs:
            for row in latest_runs:
                mission_lines.append(
                    f"- {row['mission_run_id']}: {row['status']} | {row['profile_name'] or 'n/a'} | {row['objective']}"
                )
        else:
            mission_lines.append("- aucun run recent")
        if latest_runtime is not None:
            mission_lines.extend(
                [
                    "",
                    f"Runtime verdict: {latest_runtime['verdict']}",
                    f"Active profile: {latest_runtime['active_profile'] or 'n/a'}",
                    f"Status summary: {latest_runtime['status_summary'] or 'n/a'}",
                ]
            )
        updates["runtime/mission_state.md"] = self.upsert_block(
            block_name="runtime/mission_state.md",
            content="\n".join(mission_lines).strip() + "\n",
            owner_role="executor_coordinator",
            updated_by_role="system",
            reason="refresh_runtime_blocks",
            provenance=["scheduler:memory_block_refresh"],
            surface="scheduler",
        )
        discord_lines = ["# Discord State", ""]
        if latest_channel is not None:
            message = json.loads(str(latest_channel["message_json"])) if latest_channel["message_json"] else {}
            discord_lines.extend(
                [
                    f"Last channel: {latest_channel['channel']}",
                    f"Conversation key: {latest_channel['conversation_key'] or 'n/a'}",
                    f"Last message: {str(message.get('text') or '').strip() or 'n/a'}",
                    f"Updated at: {latest_channel['created_at']}",
                ]
            )
        else:
            discord_lines.append("Aucun message Discord recent.")
        if latest_snapshot is not None:
            snapshot_payload = json.loads(str(latest_snapshot["metadata_json"])) if latest_snapshot["metadata_json"] else {}
            discord_lines.append(f"Pending deliveries: {latest_snapshot['pending_deliveries']}")
            if snapshot_payload:
                discord_lines.append(f"Snapshot metadata: {json.dumps(snapshot_payload, ensure_ascii=True, sort_keys=True)}")
        updates["runtime/discord_state.md"] = self.upsert_block(
            block_name="runtime/discord_state.md",
            content="\n".join(discord_lines).strip() + "\n",
            owner_role="operator_concierge",
            updated_by_role="system",
            reason="refresh_runtime_blocks",
            provenance=["scheduler:memory_block_refresh"],
            surface="scheduler",
        )
        uefn_lines = ["# UEFN State", ""]
        uefn_facts = self.database.fetchall(
            """
            SELECT entity, relation, value, valid_at
            FROM temporal_graph_facts
            WHERE entity LIKE 'uefn_%' OR entity LIKE 'unreal_%'
            ORDER BY valid_at DESC, created_at DESC
            LIMIT 5
            """
        )
        if uefn_facts:
            for row in uefn_facts:
                uefn_lines.append(
                    f"- {row['entity']} {row['relation']} {row['value']} (valid_at={row['valid_at']})"
                )
        else:
            uefn_lines.append("- Aucun evenement UEFN structure n'a encore ete consolide.")
        updates["runtime/uefn_state.md"] = self.upsert_block(
            block_name="runtime/uefn_state.md",
            content="\n".join(uefn_lines).strip() + "\n",
            owner_role="executor_coordinator",
            updated_by_role="system",
            reason="refresh_runtime_blocks",
            provenance=["scheduler:memory_block_refresh"],
            surface="scheduler",
        )
        recent_lines = ["# Recent Operating Context", ""]
        if latest_runs:
            recent_lines.append("## Recent runs")
            for row in latest_runs[:3]:
                recent_lines.append(f"- {row['status']}: {row['objective']}")
        if latest_channel is not None:
            message = json.loads(str(latest_channel["message_json"])) if latest_channel["message_json"] else {}
            recent_lines.extend(
                [
                    "",
                    "## Recent discord",
                    f"- {str(message.get('text') or '').strip() or 'n/a'}",
                ]
            )
        updates["profiles/recent_operating_context.md"] = self.upsert_block(
            block_name="profiles/recent_operating_context.md",
            content="\n".join(recent_lines).strip() + "\n",
            owner_role="memory_curator",
            updated_by_role="system",
            reason="refresh_runtime_blocks",
            provenance=["scheduler:memory_block_refresh"],
            surface="scheduler",
        )
        stable_lines = ["# Founder Stable Profile", ""]
        if latest_confirmed_decisions:
            stable_lines.append("## Durable decisions")
            for row in latest_confirmed_decisions:
                stable_lines.append(f"- [{row['status']}] {row['scope']}: {row['summary']}")
        else:
            stable_lines.append("- Aucune decision durable consolidee pour le moment.")
        updates["profiles/founder_stable_profile.md"] = self.upsert_block(
            block_name="profiles/founder_stable_profile.md",
            content="\n".join(stable_lines).strip() + "\n",
            owner_role="guardian",
            updated_by_role="system",
            reason="refresh_runtime_blocks",
            provenance=["scheduler:memory_block_refresh"],
            surface="scheduler",
        )
        return {
            "updated_blocks": sorted(updates.keys()),
            "version_map": {name: block.version for name, block in updates.items()},
        }

    def _block_path(self, block_name: str) -> Path:
        return self.path_policy.ensure_allowed_write(self.paths.memory_blocks_root / block_name)

    @staticmethod
    def _normalize_block_name(block_name: str) -> str:
        cleaned = block_name.strip().replace("\\", "/")
        if not cleaned:
            raise ValueError("block_name must not be empty")
        if cleaned.startswith("/"):
            cleaned = cleaned[1:]
        if not cleaned.endswith(".md"):
            cleaned = f"{cleaned}.md"
        return cleaned

    @staticmethod
    def _content_summary(content: str) -> str:
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        return " ".join(lines[:2])[:240]

    def _assert_write_allowed(
        self,
        *,
        block_name: str,
        actor_role: str,
        policy: MemoryBlockAccessPolicy,
        surface: str | None,
    ) -> None:
        if policy.writers and actor_role not in policy.writers and actor_role != "system":
            raise PermissionError(f"Writer role '{actor_role}' is not allowed for block '{block_name}'")
        self._assert_surface_allowed(policy=policy, surface=surface, block_name=block_name)
        if self._is_critical_block(block_name) and actor_role not in {"guardian", "memory_curator", "system"}:
            raise PermissionError(
                f"Writer role '{actor_role}' is not allowed to modify critical block '{block_name}'"
            )

    def _assert_read_allowed(self, *, block: MemoryBlock, actor_role: str, surface: str | None) -> None:
        if block.access_policy.readers and actor_role not in block.access_policy.readers and actor_role != "system":
            raise PermissionError(f"Reader role '{actor_role}' is not allowed for block '{block.block_name}'")
        self._assert_surface_allowed(policy=block.access_policy, surface=surface, block_name=block.block_name)

    @staticmethod
    def _normalize_surface(surface: str | None, actor_role: str) -> str | None:
        if surface:
            return surface.strip().lower()
        normalized_role = actor_role.strip().lower()
        if normalized_role in {"discord", "cli", "scheduler"}:
            return normalized_role
        return None

    @staticmethod
    def _assert_surface_allowed(
        *,
        policy: MemoryBlockAccessPolicy,
        surface: str | None,
        block_name: str,
    ) -> None:
        if not surface or not policy.surfaces:
            return
        if surface not in {item.strip().lower() for item in policy.surfaces}:
            raise PermissionError(f"Surface '{surface}' is not allowed for block '{block_name}'")

    def _is_critical_block(self, block_name: str) -> bool:
        return any(block_name.startswith(prefix) for prefix in self.config.critical_prefixes)

    def _is_noop_update(
        self,
        *,
        existing,
        content: str,
        owner_role: str,
        hash_sha256: str,
        policy_json: str,
        metadata_json: str,
        provenance_items: list[str],
    ) -> bool:
        current_block = self._row_to_block(existing)
        return (
            current_block.content == content
            and str(existing["owner_role"]) == owner_role
            and str(existing["hash_sha256"]) == hash_sha256
            and dump_json(to_jsonable(current_block.access_policy)) == policy_json
            and dump_json(current_block.metadata) == metadata_json
            and dump_json(current_block.provenance) == dump_json(provenance_items)
        )

    def _trace(self, *, operation: str, target_type: str, target_id: str, detail: dict[str, Any]) -> None:
        if self._trace_callback is None:
            return
        self._trace_callback(
            operation=operation,
            target_type=target_type,
            target_id=target_id,
            detail=detail,
        )

    def _row_to_block(self, row) -> MemoryBlock:
        path = Path(str(row["path"]))
        content = path.read_text(encoding="utf-8") if path.exists() else ""
        access_policy_payload = json.loads(str(row["access_policy_json"])) if row["access_policy_json"] else {}
        provenance = json.loads(str(row["provenance_json"])) if row["provenance_json"] else []
        metadata = json.loads(str(row["metadata_json"])) if row["metadata_json"] else {}
        return MemoryBlock(
            block_id=str(row["block_id"]),
            block_name=str(row["block_name"]),
            owner_role=str(row["owner_role"]),
            path=str(path),
            content=content,
            hash_sha256=str(row["hash_sha256"]),
            version=int(row["version"]),
            access_policy=MemoryBlockAccessPolicy(**access_policy_payload),
            provenance=list(provenance),
            last_updated_by_role=str(row["last_updated_by_role"]) if row["last_updated_by_role"] else None,
            last_updated_by_run_id=str(row["last_updated_by_run_id"]) if row["last_updated_by_run_id"] else None,
            metadata=metadata,
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )
