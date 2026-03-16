from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from project_os_core.gateway.openclaw_adapter import build_dispatch_from_openclaw_payload
from project_os_core.models import ApiRunStatus, OperatorChannelHint, RunLifecycleEventKind
from project_os_core.services import build_app_services


class OpenClawLiveTests(unittest.TestCase):
    @staticmethod
    def _default_pairing_state() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
        paired = {
            "device-1": {
                "deviceId": "device-1",
                "role": "operator",
                "roles": ["operator"],
                "scopes": ["operator.read", "operator.write", "operator.approvals", "operator.pairing"],
                "approvedScopes": ["operator.read", "operator.write", "operator.approvals", "operator.pairing"],
                "tokens": {
                    "operator": {
                        "token": "device-token-1",
                        "role": "operator",
                        "scopes": ["operator.read", "operator.write", "operator.approvals", "operator.pairing"],
                        "createdAtMs": 1773535537616,
                    }
                },
                "createdAtMs": 1773535537616,
                "approvedAtMs": 1773535537616,
            }
        }
        pending = {}
        identity = {
            "version": 1,
            "deviceId": "device-1",
            "tokens": {
                "operator": {
                    "token": "device-token-1",
                    "role": "operator",
                    "scopes": ["operator.read", "operator.write", "operator.approvals", "operator.pairing"],
                    "updatedAtMs": 1773539125844,
                }
            },
        }
        return paired, pending, identity

    def _runtime_config_payload(self, tmp_path: Path, plugin_source: Path) -> dict[str, object]:
        return {
            "agents": {
                "defaults": {
                    "typingMode": "instant",
                    "typingIntervalSeconds": 6,
                }
            },
            "session": {
                "threadBindings": {
                    "enabled": True,
                    "idleHours": 24,
                    "maxAgeHours": 0,
                },
                "sendPolicy": {
                    "default": "allow",
                    "rules": [
                        {"action": "deny", "match": {"channel": "discord", "chatType": "group"}},
                        {"action": "deny", "match": {"channel": "discord", "chatType": "channel"}},
                    ],
                },
            },
            "channels": {
                "discord": {
                    "enabled": True,
                    "groupPolicy": "allowlist",
                    "threadBindings": {
                        "enabled": True,
                        "idleHours": 24,
                        "maxAgeHours": 0,
                        "spawnSubagentSessions": False,
                    },
                    "autoPresence": {
                        "enabled": True,
                        "intervalMs": 30000,
                        "minUpdateIntervalMs": 15000,
                        "healthyText": "project os healthy",
                        "degradedText": "project os degraded",
                        "exhaustedText": "project os exhausted: {reason}",
                    },
                    "execApprovals": {
                        "enabled": True,
                        "approvers": ["1482209095984484443"],
                        "target": "dm",
                        "cleanupAfterResolve": True,
                    },
                    "accounts": {
                        "discord-main": {
                            "enabled": True,
                            "token": {"source": "env", "provider": "env", "id": "DISCORD_BOT_TOKEN"},
                            "groupPolicy": "allowlist",
                        }
                    },
                    "guilds": {
                        "*": {
                            "channels": {
                                "1482231737361891368": {
                                    "allow": True,
                                    "requireMention": True,
                                }
                            }
                        }
                    },
                }
            },
            "gateway": {
                "mode": "local",
                "auth": {
                    "mode": "token",
                    "token": {"source": "env", "provider": "env", "id": "OPENCLAW_GATEWAY_TOKEN"},
                },
            },
            "plugins": {
                "allow": ["project-os-gateway-adapter", "discord", "device-pair", "memory-core"],
                "installs": {
                    "project-os-gateway-adapter": {
                        "source": "path",
                        "sourcePath": str(plugin_source),
                        "installPath": str(plugin_source),
                        "version": "0.1.0",
                    }
                },
                "entries": {
                    "project-os-gateway-adapter": {
                        "enabled": True,
                        "config": {
                            "enabledChannels": ["discord", "webchat"],
                            "discordAccountId": "discord-main",
                            "sendAckReplies": False,
                            "suppressNativeDiscordReplies": True,
                        },
                    },
                    "discord": {
                        "enabled": True,
                    },
                },
                "load": {"paths": [str(plugin_source)]},
            },
        }

    def _build_services(self, tmp_path: Path):
        repo_root = Path(__file__).resolve().parents[2]
        plugin_source = repo_root / "integrations" / "openclaw" / "project-os-gateway-adapter"

        storage_payload = {
            "runtime_root": str(tmp_path / "runtime"),
            "memory_hot_root": str(tmp_path / "memory_hot"),
            "memory_warm_root": str(tmp_path / "memory_warm"),
            "index_root": str(tmp_path / "indexes"),
            "session_root": str(tmp_path / "sessions"),
            "cache_root": str(tmp_path / "cache"),
            "archive_drive": "Z:",
            "archive_do_not_touch_root": str(tmp_path / "archive" / "DO_NOT_TOUCH"),
            "archive_root": str(tmp_path / "archive"),
            "archive_episodes_root": str(tmp_path / "archive" / "episodes"),
            "archive_evidence_root": str(tmp_path / "archive" / "evidence"),
            "archive_screens_root": str(tmp_path / "archive" / "screens"),
            "archive_reports_root": str(tmp_path / "archive" / "reports"),
            "archive_logs_root": str(tmp_path / "archive" / "logs"),
            "archive_snapshots_root": str(tmp_path / "archive" / "snapshots"),
        }
        config_path = tmp_path / "storage_roots.json"
        config_path.write_text(json.dumps(storage_payload), encoding="utf-8")

        policy_payload = {
            "secret_config": {
                "mode": "infisical_first",
                "required_secret_names": ["OPENAI_API_KEY"],
                "local_fallback_path": str(tmp_path / "secrets.json"),
            },
            "embedding_policy": {
                "provider_mode": "local_hash",
                "quality": "balanced",
                "local_model": "local-hash-v1",
                "local_dimensions": 64,
            },
            "openclaw_config": {
                "runtime_root": str(tmp_path / "openclaw-runtime"),
                "state_root": str(tmp_path / "runtime" / "openclaw"),
                "plugin_source_path": str(plugin_source),
                "enabled_channels": ["discord", "webchat"],
                "send_ack_replies": False,
                "discord_thread_bindings_required": True,
                "discord_auto_presence_required": True,
                "discord_exec_approvals_required": True,
                "discord_exec_target": "dm",
                "discord_exec_approver_ids": ["1482209095984484443"],
                "require_replay_before_live": True,
            },
        }
        policy_path = tmp_path / "runtime_policy.json"
        policy_path.write_text(json.dumps(policy_payload), encoding="utf-8")

        services = build_app_services(config_path=str(config_path), policy_path=str(policy_path))
        services.secret_resolver.write_local_fallback("OPENAI_API_KEY", "sk-test-secret")
        services.paths.openclaw_state_root.mkdir(parents=True, exist_ok=True)
        (services.paths.openclaw_state_root / "openclaw.json").write_text(
            json.dumps(self._runtime_config_payload(tmp_path, plugin_source)),
            encoding="utf-8",
        )
        devices_root = services.paths.openclaw_state_root / "devices"
        identity_root = services.paths.openclaw_state_root / "identity"
        devices_root.mkdir(parents=True, exist_ok=True)
        identity_root.mkdir(parents=True, exist_ok=True)
        paired, pending, identity = self._default_pairing_state()
        (devices_root / "paired.json").write_text(json.dumps(paired), encoding="utf-8")
        (devices_root / "pending.json").write_text(json.dumps(pending), encoding="utf-8")
        (identity_root / "device-auth.json").write_text(json.dumps(identity), encoding="utf-8")
        return services

    @staticmethod
    def _stub_openclaw_binary_and_status(services) -> None:
        services.openclaw._resolve_openclaw_binary = lambda: "openclaw"  # type: ignore[method-assign]
        services.openclaw._plugin_visible = lambda: (True, {"id": "project-os-gateway-adapter"})  # type: ignore[method-assign]
        services.openclaw._lookup_process_or_windows_env = (  # type: ignore[method-assign]
            lambda name: f"{name.lower()}-value" if name in {"OPENCLAW_GATEWAY_TOKEN", "DISCORD_BOT_TOKEN"} else None
        )

        def _fake_command(args, *, timeout_ms):
            if args[:2] == ["plugins", "doctor"]:
                return {"ok": True, "stdout": '{"status":"ok"}', "stderr": "", "parsed": {"status": "ok"}, "returncode": 0}
            if args[:3] == ["config", "validate", "--json"]:
                return {"ok": True, "stdout": '{"valid":true}', "stderr": "", "parsed": {"valid": True}, "returncode": 0}
            if args[:3] == ["gateway", "status", "--json"]:
                return {
                    "ok": True,
                    "stdout": (
                        '{"service":{"loaded":true,"runtime":{"status":"unknown"}},'
                        '"port":{"status":"busy","listeners":[{"pid":123,"address":"127.0.0.1:18789"}]},'
                        '"rpc":{"ok":true}}'
                    ),
                    "stderr": "",
                    "parsed": {
                        "service": {"loaded": True, "runtime": {"status": "unknown"}},
                        "port": {"status": "busy", "listeners": [{"pid": 123, "address": "127.0.0.1:18789"}]},
                        "rpc": {"ok": True},
                    },
                    "returncode": 0,
                }
            if args[:3] == ["plugins", "list", "--json"]:
                return {
                    "ok": True,
                    "stdout": '[{"id":"project-os-gateway-adapter","enabled":true}]',
                    "stderr": "",
                    "parsed": [{"id": "project-os-gateway-adapter", "enabled": True}],
                    "returncode": 0,
                }
            raise AssertionError(f"Unexpected OpenClaw command: {args}")

        services.openclaw._run_openclaw_command = _fake_command  # type: ignore[method-assign]

    @staticmethod
    def _record_real_openclaw_dispatch(services, *, text: str = "Lance une verification browser via OpenClaw.") -> None:
        services.openclaw._prepare_ready_session("browser")  # type: ignore[attr-defined]
        payload = {
            "source": "openclaw",
            "surface": "discord",
            "event_type": "message.received",
            "event": {
                "from": "discord-user-42",
                "content": text,
                "timestamp": 1770000100,
                "metadata": {
                    "source": "openclaw",
                    "senderId": "42",
                    "senderName": "Founder",
                    "messageId": "discord-live-proof-1",
                    "threadId": "discord-live-thread-1",
                    "originatingChannel": "discord",
                    "originatingTo": "123456",
                    "channelName": "project-os",
                },
            },
            "context": {
                "channelId": "discord",
                "accountId": "default",
                "conversationId": "123456",
            },
            "config": {
                "target_profile": "browser",
                "requested_worker": "browser",
                "metadata": {"source": "unit-test"},
            },
        }
        adapted = build_dispatch_from_openclaw_payload(payload)
        services.gateway.dispatch_event(
            adapted.event,
            target_profile=adapted.target_profile,
            requested_worker=adapted.requested_worker,
            risk_class=adapted.risk_class,
            metadata=adapted.metadata,
        )

    def test_openclaw_adapter_preserves_rich_attachment_metadata(self):
        payload = {
            "source": "openclaw",
            "surface": "discord",
            "event_type": "message.received",
            "event": {
                "from": "discord-user-42",
                "content": "Voici le vocal et le brief.",
                "timestamp": 1770000100,
                "metadata": {
                    "senderId": "42",
                    "messageId": "discord-attach-1",
                    "originatingChannel": "discord",
                    "attachments": [
                        {
                            "name": "voice-note.m4a",
                            "mimeType": "audio/mp4",
                            "url": "https://example.test/voice-note.m4a",
                            "sizeBytes": 2048,
                            "durationSecs": 92,
                        },
                        {
                            "fileName": "brief.pdf",
                            "contentType": "application/pdf",
                            "path": "D:/captures/brief.pdf",
                            "size": 4096,
                        },
                    ],
                },
            },
            "context": {
                "channelId": "discord",
                "accountId": "default",
                "conversationId": "123456",
            },
            "config": {},
        }

        adapted = build_dispatch_from_openclaw_payload(payload)

        self.assertEqual(len(adapted.event.message.attachments), 2)
        first, second = adapted.event.message.attachments
        self.assertEqual(first.kind, "audio")
        self.assertEqual(first.url, "https://example.test/voice-note.m4a")
        self.assertEqual(first.size_bytes, 2048)
        self.assertEqual(first.metadata["duration_secs"], 92)
        self.assertEqual(second.kind, "document")
        self.assertEqual(second.path, "D:/captures/brief.pdf")
        self.assertEqual(second.size_bytes, 4096)

    def test_openclaw_adapter_repairs_common_mojibake_on_message_content(self):
        payload = {
            "source": "openclaw",
            "surface": "discord",
            "event_type": "message.received",
            "event": {
                "from": "discord-user-42",
                "content": "Quelle problÃ¨me dâ€™encodage ? cafÃ© Ã©tÃ©",
                "timestamp": 1770000101,
                "metadata": {
                    "senderId": "42",
                    "messageId": "discord-mojibake-1",
                    "originatingChannel": "discord",
                },
            },
            "context": {
                "channelId": "discord",
                "accountId": "default",
                "conversationId": "123456",
            },
            "config": {},
        }

        adapted = build_dispatch_from_openclaw_payload(payload)

        self.assertEqual(adapted.event.message.text, "Quelle problème d’encodage ? café été")

    def test_openclaw_bootstrap_blocks_cleanly_when_binary_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                services.openclaw._resolve_openclaw_binary = lambda: None  # type: ignore[method-assign]
                report = services.openclaw.bootstrap()
                self.assertEqual(report.readiness, "bloque")
                self.assertIn("openclaw_binary_missing", report.blocking_reasons)
                self.assertEqual(report.plugin_status, "binary_missing")
            finally:
                services.close()

    def test_openclaw_doctor_blocks_cleanly_when_binary_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                services.openclaw._resolve_openclaw_binary = lambda: None  # type: ignore[method-assign]
                report = services.openclaw.doctor()
                self.assertEqual(report.verdict, "bloque")
                self.assertTrue(any("Installe OpenClaw" in item for item in report.actionable_fixes))
            finally:
                services.close()

    def test_openclaw_doctor_blocks_on_insecure_live_runtime_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            services = self._build_services(tmp_path)
            try:
                insecure_payload = self._runtime_config_payload(
                    tmp_path,
                    Path(__file__).resolve().parents[2] / "integrations" / "openclaw" / "project-os-gateway-adapter",
                )
                insecure_payload["channels"]["discord"]["groupPolicy"] = "open"  # type: ignore[index]
                insecure_payload["channels"]["discord"]["accounts"]["discord-main"]["token"] = "discord-plaintext-token"  # type: ignore[index]
                insecure_payload["channels"]["discord"]["accounts"]["discord-main"]["groupPolicy"] = "open"  # type: ignore[index]
                insecure_payload["channels"]["discord"]["guilds"]["*"]["channels"]["1482231737361891368"]["requireMention"] = False  # type: ignore[index]
                insecure_payload["session"].pop("threadBindings", None)  # type: ignore[index]
                insecure_payload["session"].pop("sendPolicy", None)  # type: ignore[index]
                insecure_payload["channels"]["discord"].pop("threadBindings", None)  # type: ignore[index]
                insecure_payload["channels"]["discord"].pop("autoPresence", None)  # type: ignore[index]
                insecure_payload["channels"]["discord"].pop("execApprovals", None)  # type: ignore[index]
                insecure_payload["gateway"]["auth"]["token"] = "gateway-plaintext-token"  # type: ignore[index]
                insecure_payload["plugins"]["allow"] = []  # type: ignore[index]
                insecure_payload["plugins"]["entries"]["project-os-gateway-adapter"]["config"]["sendAckReplies"] = True  # type: ignore[index]
                insecure_payload["plugins"]["entries"]["project-os-gateway-adapter"]["config"]["suppressNativeDiscordReplies"] = False  # type: ignore[index]
                (services.paths.openclaw_state_root / "openclaw.json").write_text(
                    json.dumps(insecure_payload),
                    encoding="utf-8",
                )

                services.openclaw._resolve_openclaw_binary = lambda: "openclaw"  # type: ignore[method-assign]
                services.openclaw._plugin_visible = lambda: (True, {"id": "project-os-gateway-adapter"})  # type: ignore[method-assign]
                services.openclaw._lookup_process_or_windows_env = (  # type: ignore[method-assign]
                    lambda name: "gateway-token-from-user-env"
                    if name == "OPENCLAW_GATEWAY_TOKEN"
                    else ("discord-token-from-user-env" if name == "DISCORD_BOT_TOKEN" else None)
                )

                def _fake_command(args, *, timeout_ms):
                    if args[:2] == ["plugins", "doctor"]:
                        return {"ok": True, "stdout": '{"status":"ok"}', "stderr": "", "parsed": {"status": "ok"}, "returncode": 0}
                    if args[:3] == ["config", "validate", "--json"]:
                        return {"ok": True, "stdout": '{"valid":true}', "stderr": "", "parsed": {"valid": True}, "returncode": 0}
                    if args[:3] == ["gateway", "status", "--json"]:
                        return {
                            "ok": True,
                            "stdout": '{"service":{"loaded":false},"runtime":{"status":"unknown"}}',
                            "stderr": "",
                            "parsed": {"service": {"loaded": False}, "runtime": {"status": "unknown"}},
                            "returncode": 0,
                        }
                    if args[:3] == ["plugins", "list", "--json"]:
                        return {
                            "ok": True,
                            "stdout": '[{"id":"project-os-gateway-adapter","enabled":true}]',
                            "stderr": "",
                            "parsed": [{"id": "project-os-gateway-adapter", "enabled": True}],
                            "returncode": 0,
                        }
                    raise AssertionError(f"Unexpected OpenClaw command: {args}")

                services.openclaw._run_openclaw_command = _fake_command  # type: ignore[method-assign]

                report = services.openclaw.doctor()
                self.assertEqual(report.verdict, "bloque")
                by_name = {item["name"]: item for item in report.checks}
                self.assertEqual(by_name["runtime_secrets"]["status"], "bloque")
                self.assertEqual(by_name["discord_policy"]["status"], "bloque")
                self.assertEqual(by_name["discord_single_voice_ready"]["status"], "bloque")
                self.assertEqual(by_name["discord_operations_ux"]["status"], "bloque")
                self.assertEqual(by_name["plugins_allowlist"]["status"], "bloque")
                self.assertEqual(by_name["speech_policy"]["status"], "bloque")
                self.assertEqual(by_name["gateway_status"]["status"], "bloque")
            finally:
                services.close()

    def test_openclaw_doctor_blocks_when_local_lane_is_enabled_but_not_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                services.config.execution_policy.local_model_enabled = True
                services.router.execution_policy.local_model_enabled = True
                services.openclaw.local_model_client = type(
                    "StubLocalDown",
                    (),
                    {
                        "health": lambda self, force=False: {
                            "status": "blocked",
                            "reason": "service_unreachable",
                            "provider": "ollama",
                            "model": "qwen2.5:14b",
                            "base_url": "http://127.0.0.1:11434",
                        }
                    },
                )()
                self._stub_openclaw_binary_and_status(services)

                report = services.openclaw.doctor()

                self.assertEqual(report.verdict, "bloque")
                by_name = {item["name"]: item for item in report.checks}
                self.assertEqual(by_name["local_model_route"]["status"], "bloque")
            finally:
                services.close()

    def test_openclaw_doctor_accepts_private_server_without_mentions_when_policy_allows_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            services = self._build_services(tmp_path)
            try:
                runtime_payload = self._runtime_config_payload(
                    tmp_path,
                    Path(__file__).resolve().parents[2] / "integrations" / "openclaw" / "project-os-gateway-adapter",
                )
                runtime_payload["channels"]["discord"]["guilds"] = {"*": {"requireMention": False}}  # type: ignore[index]
                (services.paths.openclaw_state_root / "openclaw.json").write_text(
                    json.dumps(runtime_payload),
                    encoding="utf-8",
                )

                services.config.openclaw_config.discord_require_mention = False
                self._stub_openclaw_binary_and_status(services)

                report = services.openclaw.doctor()

                self.assertEqual(report.verdict, "OK")
                by_name = {item["name"]: item for item in report.checks}
                self.assertEqual(by_name["discord_policy"]["status"], "ok")
                self.assertEqual(by_name["discord_single_voice_ready"]["status"], "ok")
            finally:
                services.close()

    def test_openclaw_replay_all_fixtures_respects_router_and_selective_sync(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                report = services.openclaw.replay(run_all=True)
                self.assertEqual(report["verdict"], "OK")
                self.assertEqual(report["failed"], 0)

                by_fixture = {item["fixture_id"]: item for item in report["results"]}
                self.assertEqual(by_fixture["simple_text"]["promoted_memory_count"], 1)
                self.assertEqual(by_fixture["with_attachment"]["promoted_memory_count"], 1)
                self.assertEqual(by_fixture["tasking_browser"]["promoted_memory_count"], 1)
                self.assertEqual(by_fixture["small_talk_skip"]["promoted_memory_count"], 0)
                self.assertTrue(by_fixture["small_talk_skip"]["passed"])
            finally:
                services.close()

    def test_openclaw_validate_live_requires_replay_and_enabled_channel_before_live_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                payload_file = str(Path(__file__).resolve().parents[2] / "fixtures" / "openclaw" / "simple_text.json")
                result = services.openclaw.validate_live(channel="discord", payload_file=payload_file)
                self.assertFalse(result.success)
                self.assertIn("Replay OpenClaw non valide", result.failure_reason or "")

                services.openclaw._write_json(  # type: ignore[attr-defined]
                    services.paths.openclaw_replay_report_path,
                    {"verdict": "OK", "total": 1, "passed": 1, "failed": 0, "results": []},
                )
                services.config.openclaw_config.enabled_channels = ["webchat"]
                result = services.openclaw.validate_live(channel="discord", payload_file=payload_file)
                self.assertFalse(result.success)
                self.assertIn("Canal non active", result.failure_reason or "")
            finally:
                services.close()

    def test_openclaw_validate_live_succeeds_when_real_openclaw_event_reached_router(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                self._stub_openclaw_binary_and_status(services)
                services.openclaw._write_json(  # type: ignore[attr-defined]
                    services.paths.openclaw_replay_report_path,
                    {"verdict": "OK", "total": 1, "passed": 1, "failed": 0, "results": []},
                )
                self._record_real_openclaw_dispatch(services)

                result = services.openclaw.validate_live(channel="discord")
                self.assertTrue(result.success)
                self.assertGreaterEqual(len(result.evidence_refs), 2)
            finally:
                services.close()

    def test_openclaw_validate_live_blocks_when_single_voice_contract_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            services = self._build_services(tmp_path)
            try:
                self._stub_openclaw_binary_and_status(services)
                services.openclaw._write_json(  # type: ignore[attr-defined]
                    services.paths.openclaw_replay_report_path,
                    {"verdict": "OK", "total": 1, "passed": 1, "failed": 0, "results": []},
                )
                runtime_payload = self._runtime_config_payload(
                    tmp_path,
                    Path(__file__).resolve().parents[2] / "integrations" / "openclaw" / "project-os-gateway-adapter",
                )
                runtime_payload["session"].pop("sendPolicy", None)  # type: ignore[index]
                (services.paths.openclaw_state_root / "openclaw.json").write_text(
                    json.dumps(runtime_payload),
                    encoding="utf-8",
                )

                result = services.openclaw.validate_live(channel="discord")

                self.assertFalse(result.success)
                self.assertIn("single voice", result.failure_reason or "")
                self.assertEqual(result.metadata["single_voice_check"]["name"], "discord_single_voice_ready")
            finally:
                services.close()

    def test_openclaw_doctor_blocks_when_discord_typing_policy_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            services = self._build_services(tmp_path)
            try:
                self._stub_openclaw_binary_and_status(services)
                runtime_payload = self._runtime_config_payload(
                    tmp_path,
                    Path(__file__).resolve().parents[2] / "integrations" / "openclaw" / "project-os-gateway-adapter",
                )
                runtime_payload["agents"]["defaults"].pop("typingMode", None)  # type: ignore[index]
                runtime_payload["agents"]["defaults"].pop("typingIntervalSeconds", None)  # type: ignore[index]
                (services.paths.openclaw_state_root / "openclaw.json").write_text(
                    json.dumps(runtime_payload),
                    encoding="utf-8",
                )

                report = services.openclaw.doctor()

                checks_by_name = {item["name"]: item for item in report.checks}
                self.assertEqual(checks_by_name["discord_operations_ux"]["status"], "bloque")
                details = checks_by_name["discord_operations_ux"]["details"]
                self.assertTrue(any(item["path"] == "agents.defaults.typingMode" for item in details))
            finally:
                services.close()

    def test_openclaw_truth_health_accepts_windows_unknown_runtime_when_listener_and_rpc_are_healthy(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                self._stub_openclaw_binary_and_status(services)
                services.openclaw._write_json(  # type: ignore[attr-defined]
                    services.paths.openclaw_replay_report_path,
                    {"report_id": "replay_test", "verdict": "OK", "total": 1, "passed": 1, "failed": 0, "results": []},
                )
                self._record_real_openclaw_dispatch(services)

                report = services.openclaw.truth_health(channel="discord")
                self.assertEqual(report.verdict, "OK")
                checks_by_name = {item["name"]: item for item in report.checks}
                self.assertEqual(checks_by_name["gateway_status"]["status"], "ok")
                self.assertEqual(checks_by_name["discord_single_voice_ready"]["status"], "ok")
                self.assertEqual(checks_by_name["live_bridge_proof"]["status"], "ok")
            finally:
                services.close()

    def test_openclaw_discord_calibration_snapshot_collects_events_deliveries_and_log_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                self._stub_openclaw_binary_and_status(services)
                self._record_real_openclaw_dispatch(services, text="Analyse en direct du bot Discord.")
                log_root = services.paths.openclaw_state_root / "logs"
                log_root.mkdir(parents=True, exist_ok=True)
                log_path = log_root / "openclaw-2026-03-16.log"
                log_path.write_text("line-1\nline-2\nline-3\n", encoding="utf-8")

                services.api_runs.publish_operator_update(
                    title="Calibration Discord",
                    summary="Reply visible pour le watcher.",
                    text="Reply visible pour le watcher.",
                    kind=RunLifecycleEventKind.RUN_COMPLETED,
                    status=ApiRunStatus.COMPLETED,
                    channel_hint=OperatorChannelHint.RUNS_LIVE,
                    target="channel:123456",
                    reply_to="discord-live-proof-1",
                    metadata={"source": "unit-test"},
                )

                snapshot = services.openclaw.discord_calibration_snapshot(limit=3, log_lines=2)

                self.assertEqual(snapshot["channel"], "discord")
                self.assertTrue(snapshot["gateway_status"]["healthy"])
                self.assertIsNotNone(snapshot["live_proof"])
                self.assertGreaterEqual(len(snapshot["recent_events"]), 1)
                self.assertEqual(snapshot["recent_events"][0]["source"], "openclaw")
                self.assertIn("Analyse en direct", snapshot["recent_events"][0]["text"])
                self.assertGreaterEqual(len(snapshot["recent_deliveries"]), 1)
                self.assertEqual(snapshot["recent_deliveries"][0]["target"], "channel:123456")
                self.assertIsNotNone(snapshot["openclaw_log_tail"])
                self.assertEqual(snapshot["openclaw_log_tail"]["path"], str(log_path))
                self.assertEqual(snapshot["openclaw_log_tail"]["lines"], ["line-2", "line-3"])
            finally:
                services.close()

    def test_openclaw_gateway_status_uses_windows_user_env_token_when_process_env_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                services.openclaw._resolve_openclaw_binary = lambda: "openclaw"  # type: ignore[method-assign]
                services.openclaw._lookup_process_or_windows_env = (  # type: ignore[method-assign]
                    lambda name: "gateway-token-from-user-env" if name == "OPENCLAW_GATEWAY_TOKEN" else None
                )

                seen_commands: list[list[str]] = []

                def _fake_command(args, *, timeout_ms):
                    seen_commands.append(list(args))
                    return {
                        "ok": True,
                        "stdout": '{"service":{"loaded":true,"runtime":{"status":"running"}},"port":{"status":"busy","listeners":[{"pid":123}]}}',
                        "stderr": "",
                        "parsed": {
                            "service": {"loaded": True, "runtime": {"status": "running"}},
                            "port": {"status": "busy", "listeners": [{"pid": 123}]},
                        },
                        "returncode": 0,
                    }

                services.openclaw._run_openclaw_command = _fake_command  # type: ignore[method-assign]

                runtime_config = self._runtime_config_payload(
                    Path(tmp),
                    Path(__file__).resolve().parents[2] / "integrations" / "openclaw" / "project-os-gateway-adapter",
                )
                services.openclaw._gateway_status_command(runtime_config)

                self.assertEqual(
                    seen_commands[0],
                    ["gateway", "status", "--json", "--token", "gateway-token-from-user-env"],
                )
            finally:
                services.close()

    def test_openclaw_trust_audit_passes_with_trusted_plugin_and_clean_pairing_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                services.openclaw._resolve_openclaw_binary = lambda: "openclaw"  # type: ignore[method-assign]

                def _fake_command(args, *, timeout_ms):
                    if args[:3] == ["plugins", "list", "--json"]:
                        return {
                            "ok": True,
                            "stdout": json.dumps(
                                {
                                    "plugins": [
                                        {
                                            "id": "project-os-gateway-adapter",
                                            "enabled": True,
                                            "status": "loaded",
                                            "origin": "config",
                                            "source": str(
                                                (
                                                    Path(__file__).resolve().parents[2]
                                                    / "integrations"
                                                    / "openclaw"
                                                    / "project-os-gateway-adapter"
                                                    / "index.js"
                                                ).resolve(strict=False)
                                            ),
                                            "version": "0.1.0",
                                        },
                                        {
                                            "id": "discord",
                                            "enabled": True,
                                            "status": "loaded",
                                            "origin": "bundled",
                                            "source": "bundled://discord",
                                            "version": "2026.3.12",
                                        },
                                        {
                                            "id": "device-pair",
                                            "enabled": True,
                                            "status": "loaded",
                                            "origin": "bundled",
                                            "source": "bundled://device-pair",
                                            "version": "2026.3.12",
                                        },
                                        {
                                            "id": "memory-core",
                                            "enabled": True,
                                            "status": "loaded",
                                            "origin": "bundled",
                                            "source": "bundled://memory-core",
                                            "version": "2026.3.12",
                                        },
                                    ]
                                }
                            ),
                            "stderr": "",
                            "parsed": {
                                "plugins": [
                                    {
                                        "id": "project-os-gateway-adapter",
                                        "enabled": True,
                                        "status": "loaded",
                                        "origin": "config",
                                        "source": str(
                                            (
                                                Path(__file__).resolve().parents[2]
                                                / "integrations"
                                                / "openclaw"
                                                / "project-os-gateway-adapter"
                                                / "index.js"
                                            ).resolve(strict=False)
                                        ),
                                        "version": "0.1.0",
                                    },
                                    {"id": "discord", "enabled": True, "status": "loaded", "origin": "bundled", "source": "bundled://discord", "version": "2026.3.12"},
                                    {"id": "device-pair", "enabled": True, "status": "loaded", "origin": "bundled", "source": "bundled://device-pair", "version": "2026.3.12"},
                                    {"id": "memory-core", "enabled": True, "status": "loaded", "origin": "bundled", "source": "bundled://memory-core", "version": "2026.3.12"},
                                ]
                            },
                            "returncode": 0,
                        }
                    raise AssertionError(f"Unexpected OpenClaw command: {args}")

                services.openclaw._run_openclaw_command = _fake_command  # type: ignore[method-assign]

                report = services.openclaw.trust_audit()
                self.assertEqual(report.verdict, "OK")
                checks_by_name = {item["name"]: item for item in report.checks}
                self.assertEqual(checks_by_name["plugin_catalog"]["status"], "ok")
                self.assertEqual(checks_by_name["plugin_install_policy"]["status"], "ok")
                self.assertEqual(checks_by_name["pairing_store"]["status"], "ok")
                self.assertEqual(checks_by_name["pairing_secret_exposure"]["status"], "ok")
            finally:
                services.close()

    def test_openclaw_trust_audit_blocks_on_untrusted_plugin_or_secret_leak(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                services.openclaw._resolve_openclaw_binary = lambda: "openclaw"  # type: ignore[method-assign]
                leak_path = services.paths.openclaw_state_root / "agents" / "main" / "sessions" / "leak.log"
                leak_path.parent.mkdir(parents=True, exist_ok=True)
                leak_path.write_text("device-token-1", encoding="utf-8")

                def _fake_command(args, *, timeout_ms):
                    if args[:3] == ["plugins", "list", "--json"]:
                        return {
                            "ok": True,
                            "stdout": json.dumps(
                                {
                                    "plugins": [
                                        {
                                            "id": "project-os-gateway-adapter",
                                            "enabled": True,
                                            "status": "loaded",
                                            "origin": "config",
                                            "source": str(
                                                (
                                                    Path(__file__).resolve().parents[2]
                                                    / "integrations"
                                                    / "openclaw"
                                                    / "project-os-gateway-adapter"
                                                    / "index.js"
                                                ).resolve(strict=False)
                                            ),
                                            "version": "0.1.0",
                                        },
                                        {
                                            "id": "rogue-plugin",
                                            "enabled": True,
                                            "status": "loaded",
                                            "origin": "config",
                                            "source": "D:/tmp/rogue/index.js",
                                            "version": "9.9.9",
                                        },
                                    ]
                                }
                            ),
                            "stderr": "",
                            "parsed": {
                                "plugins": [
                                    {
                                        "id": "project-os-gateway-adapter",
                                        "enabled": True,
                                        "status": "loaded",
                                        "origin": "config",
                                        "source": str(
                                            (
                                                Path(__file__).resolve().parents[2]
                                                / "integrations"
                                                / "openclaw"
                                                / "project-os-gateway-adapter"
                                                / "index.js"
                                            ).resolve(strict=False)
                                        ),
                                        "version": "0.1.0",
                                    },
                                    {"id": "rogue-plugin", "enabled": True, "status": "loaded", "origin": "config", "source": "D:/tmp/rogue/index.js", "version": "9.9.9"},
                                ]
                            },
                            "returncode": 0,
                        }
                    raise AssertionError(f"Unexpected OpenClaw command: {args}")

                services.openclaw._run_openclaw_command = _fake_command  # type: ignore[method-assign]

                report = services.openclaw.trust_audit()
                self.assertEqual(report.verdict, "bloque")
                checks_by_name = {item["name"]: item for item in report.checks}
                self.assertEqual(checks_by_name["plugin_catalog"]["status"], "bloque")
                self.assertEqual(checks_by_name["pairing_secret_exposure"]["status"], "bloque")
            finally:
                services.close()

    def test_openclaw_self_heal_is_noop_when_gateway_is_already_healthy(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                services.openclaw._resolve_openclaw_binary = lambda: "openclaw"  # type: ignore[method-assign]

                def _fake_command(args, *, timeout_ms):
                    if args[:3] == ["gateway", "status", "--json"]:
                        return {
                            "ok": True,
                            "stdout": '{"service":{"loaded":true,"runtime":{"status":"unknown"}},"port":{"status":"busy","listeners":[{"pid":123}]},"rpc":{"ok":true}}',
                            "stderr": "",
                            "parsed": {
                                "service": {"loaded": True, "runtime": {"status": "unknown"}},
                                "port": {"status": "busy", "listeners": [{"pid": 123}]},
                                "rpc": {"ok": True},
                            },
                            "returncode": 0,
                        }
                    raise AssertionError(f"Unexpected OpenClaw command: {args}")

                services.openclaw._run_openclaw_command = _fake_command  # type: ignore[method-assign]

                report = services.openclaw.self_heal()
                self.assertEqual(report.status, "healthy")
                self.assertEqual(report.actions, [])
            finally:
                services.close()

    def test_openclaw_self_heal_repairs_gateway_with_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                services.openclaw._resolve_openclaw_binary = lambda: "openclaw"  # type: ignore[method-assign]
                status_payloads = [
                    {
                        "service": {"loaded": True, "runtime": {"status": "unknown"}},
                        "port": {"status": "free", "listeners": []},
                        "rpc": {"ok": False},
                    },
                    {
                        "service": {"loaded": True, "runtime": {"status": "unknown"}},
                        "port": {"status": "busy", "listeners": [{"pid": 123}]},
                        "rpc": {"ok": True},
                    },
                ]

                def _fake_command(args, *, timeout_ms):
                    if args[:3] == ["gateway", "status", "--json"]:
                        parsed = status_payloads.pop(0)
                        return {
                            "ok": True,
                            "stdout": json.dumps(parsed),
                            "stderr": "",
                            "parsed": parsed,
                            "returncode": 0,
                        }
                    if args[:2] == ["gateway", "restart"]:
                        return {"ok": True, "stdout": "", "stderr": "", "parsed": None, "returncode": 0}
                    raise AssertionError(f"Unexpected OpenClaw command: {args}")

                services.openclaw._run_openclaw_command = _fake_command  # type: ignore[method-assign]

                report = services.openclaw.self_heal()
                self.assertEqual(report.status, "restarted")
                self.assertEqual(report.actions, ["gateway_restart"])
            finally:
                services.close()

    def test_openclaw_self_heal_falls_back_to_start_after_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                services.openclaw._resolve_openclaw_binary = lambda: "openclaw"  # type: ignore[method-assign]
                status_payloads = [
                    {
                        "service": {"loaded": True, "runtime": {"status": "unknown"}},
                        "port": {"status": "free", "listeners": []},
                        "rpc": {"ok": False},
                    },
                    {
                        "service": {"loaded": True, "runtime": {"status": "unknown"}},
                        "port": {"status": "free", "listeners": []},
                        "rpc": {"ok": False},
                    },
                    {
                        "service": {"loaded": True, "runtime": {"status": "unknown"}},
                        "port": {"status": "busy", "listeners": [{"pid": 123}]},
                        "rpc": {"ok": True},
                    },
                ]

                def _fake_command(args, *, timeout_ms):
                    if args[:3] == ["gateway", "status", "--json"]:
                        parsed = status_payloads.pop(0)
                        return {
                            "ok": True,
                            "stdout": json.dumps(parsed),
                            "stderr": "",
                            "parsed": parsed,
                            "returncode": 0,
                        }
                    if args[:2] == ["gateway", "restart"]:
                        return {"ok": False, "stdout": "", "stderr": "restart timeout", "parsed": None, "returncode": 1}
                    if args[:2] == ["gateway", "start"]:
                        return {"ok": True, "stdout": "", "stderr": "", "parsed": None, "returncode": 0}
                    raise AssertionError(f"Unexpected OpenClaw command: {args}")

                services.openclaw._run_openclaw_command = _fake_command  # type: ignore[method-assign]

                report = services.openclaw.self_heal()
                self.assertEqual(report.status, "started")
                self.assertEqual(report.actions, ["gateway_restart", "gateway_start"])
            finally:
                services.close()

    def test_openclaw_self_heal_respects_cooldown_after_recent_repair(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                services.openclaw._resolve_openclaw_binary = lambda: "openclaw"  # type: ignore[method-assign]
                services.openclaw._write_json(  # type: ignore[attr-defined]
                    services.paths.openclaw_self_heal_report_path,
                    {
                        "report_id": "openclaw_self_heal_previous",
                        "status": "restarted",
                        "created_at": "2026-03-15T05:58:00+00:00",
                        "metadata": {
                            "last_repair_attempt_at": "2999-03-15T05:58:00+00:00",
                        },
                    },
                )

                def _fake_command(args, *, timeout_ms):
                    if args[:3] == ["gateway", "status", "--json"]:
                        parsed = {
                            "service": {"loaded": True, "runtime": {"status": "unknown"}},
                            "port": {"status": "free", "listeners": []},
                            "rpc": {"ok": False},
                        }
                        return {
                            "ok": True,
                            "stdout": json.dumps(parsed),
                            "stderr": "",
                            "parsed": parsed,
                            "returncode": 0,
                        }
                    raise AssertionError(f"Unexpected OpenClaw command: {args}")

                services.openclaw._run_openclaw_command = _fake_command  # type: ignore[method-assign]

                report = services.openclaw.self_heal()
                self.assertEqual(report.status, "cooldown_skip")
                self.assertEqual(report.actions, [])
            finally:
                services.close()


if __name__ == "__main__":
    unittest.main()
