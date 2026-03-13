from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from ..config import RuntimeConfig
from ..database import CanonicalDatabase
from ..models import (
    OpenClawBootstrapReport,
    OpenClawDoctorReport,
    OpenClawLiveValidationResult,
    OpenClawReplayFixture,
    OpenClawReplayResult,
    OpenClawRuntimeRoots,
    RuntimeState,
    RuntimeVerdict,
    new_id,
    to_jsonable,
)
from ..observability import StructuredLogger
from ..paths import PathPolicy, ProjectPaths
from ..runtime.store import RuntimeStore


class OpenClawLiveService:
    def __init__(
        self,
        *,
        config: RuntimeConfig,
        paths: ProjectPaths,
        path_policy: PathPolicy,
        runtime: RuntimeStore,
        database: CanonicalDatabase,
        logger: StructuredLogger,
    ) -> None:
        self.config = config
        self.paths = paths
        self.path_policy = path_policy
        self.runtime = runtime
        self.database = database
        self.logger = logger
        self.repo_root = config.repo_root
        self.fixtures_root = self.repo_root / "fixtures" / "openclaw"
        self.plugin_source_path = self._resolve_plugin_source_path()
        self.plugin_manifest_path = self.plugin_source_path / "openclaw.plugin.json"
        self.project_os_entrypoint = self.repo_root / "scripts" / "project_os_entry.py"

    def runtime_roots(self) -> OpenClawRuntimeRoots:
        return OpenClawRuntimeRoots(
            runtime_root=str(self.paths.openclaw_runtime_root),
            state_root=str(self.paths.openclaw_state_root),
            plugin_source_path=str(self.plugin_source_path),
            plugin_manifest_path=str(self.plugin_manifest_path),
            storage_config_path=str(self.config.storage_config_path),
            runtime_policy_path=str(self.config.runtime_policy_path),
        )

    def bootstrap(self, *, install_if_missing: bool = False) -> OpenClawBootstrapReport:
        runtime_roots = self.runtime_roots()
        checks: list[dict[str, Any]] = []
        blocking_reasons: list[str] = []
        actionable_fixes: list[str] = []
        install_method = "absent"
        plugin_status = "not_ready"

        self._ensure_openclaw_roots()
        self._check_exists(
            checks,
            "racine_runtime_openclaw",
            self.paths.openclaw_runtime_root,
            blocking_reasons,
            "runtime_root_missing",
            actionable_fixes,
            "Cree la racine runtime OpenClaw sur D:/ProjectOS/openclaw-runtime.",
        )
        self._check_exists(
            checks,
            "etat_openclaw",
            self.paths.openclaw_state_root,
            blocking_reasons,
            "state_root_missing",
            actionable_fixes,
            "Cree la racine d'etat OpenClaw dans D:/ProjectOS/runtime/openclaw.",
        )
        self._check_exists(
            checks,
            "config_project_os",
            Path(runtime_roots.storage_config_path),
            blocking_reasons,
            "storage_config_missing",
            actionable_fixes,
            "Verifie le fichier storage_roots.local.json de Project OS.",
        )
        self._check_exists(
            checks,
            "policy_project_os",
            Path(runtime_roots.runtime_policy_path),
            blocking_reasons,
            "runtime_policy_missing",
            actionable_fixes,
            "Verifie le fichier runtime_policy.local.json de Project OS.",
        )
        self._check_exists(
            checks,
            "plugin_source",
            self.plugin_source_path,
            blocking_reasons,
            "plugin_source_missing",
            actionable_fixes,
            "Verifie le dossier du plugin Project OS pour OpenClaw.",
        )
        self._check_exists(
            checks,
            "plugin_manifest",
            self.plugin_manifest_path,
            blocking_reasons,
            "plugin_manifest_missing",
            actionable_fixes,
            "Ajoute ou repare openclaw.plugin.json dans le plugin Project OS.",
        )
        self._check_exists(
            checks,
            "project_os_entrypoint",
            self.project_os_entrypoint,
            blocking_reasons,
            "python_entrypoint_missing",
            actionable_fixes,
            "Verifie scripts/project_os_entry.py.",
        )

        binary_path = self._resolve_openclaw_binary()
        if binary_path:
            binary_health = self._smoke_check_openclaw_binary(binary_path)
            if binary_health["ok"]:
                install_method = "existing_binary"
                checks.append(self._ok_check("openclaw_binaire", f"OpenClaw trouve: {binary_path}"))
            elif install_if_missing:
                checks.append(self._warn_check("openclaw_binaire", "OpenClaw est present mais doit etre repare.", binary_health["details"]))
                install_attempt = self._install_openclaw_from_registry()
                checks.append(install_attempt["check"])
                if install_attempt["ok"]:
                    binary_path = self._resolve_openclaw_binary()
                    install_method = "installed_registry"
                else:
                    blocking_reasons.append("openclaw_binary_broken")
                    actionable_fixes.append("Reinstalle OpenClaw depuis le registre npm ou via le script officiel.")
            else:
                checks.append(self._blocked_check("openclaw_binaire", "OpenClaw est present mais le binaire est casse.", binary_health["details"]))
                blocking_reasons.append("openclaw_binary_broken")
                actionable_fixes.append("Relance `project-os openclaw bootstrap --install-if-missing` pour reparer OpenClaw.")
        elif install_if_missing:
            install_attempt = self._install_openclaw_from_registry()
            checks.append(install_attempt["check"])
            if install_attempt["ok"]:
                binary_path = self._resolve_openclaw_binary()
                install_method = "installed_registry"
            else:
                fallback_attempt = self._install_openclaw_from_local_checkout()
                checks.append(fallback_attempt["check"])
                if fallback_attempt["ok"]:
                    binary_path = self._resolve_openclaw_binary()
                    install_method = "installed_local_checkout"
                else:
                    blocking_reasons.append("openclaw_binary_missing")
                    actionable_fixes.append("Installe OpenClaw depuis le registre npm ou via le script officiel, puis relance le bootstrap.")
        else:
            checks.append(self._blocked_check("openclaw_binaire", "OpenClaw n'est pas installe sur cette machine."))
            blocking_reasons.append("openclaw_binary_missing")
            actionable_fixes.append("Installe OpenClaw ou relance `project-os openclaw bootstrap --install-if-missing`.")

        if binary_path:
            install_result = self._run_openclaw_command(
                ["plugins", "install", "--link", str(self.plugin_source_path)],
                timeout_ms=self.config.openclaw_config.timeout_ms,
            )
            checks.append(
                self._ok_check("plugin_link", "Plugin Project OS lie dans OpenClaw.")
                if install_result["ok"]
                else self._warn_check("plugin_link", "Le lien du plugin OpenClaw a retourne une erreur, verification via doctor necessaire.")
            )
            enable_result = self._run_openclaw_command(
                ["plugins", "enable", self.config.openclaw_config.plugin_id],
                timeout_ms=self.config.openclaw_config.timeout_ms,
            )
            checks.append(
                self._ok_check("plugin_enable", "Plugin Project OS active.")
                if enable_result["ok"]
                else self._warn_check("plugin_enable", "L'activation du plugin a retourne une erreur, verification via doctor necessaire.")
            )
            plugin_visible, plugin_details = self._plugin_visible()
            if plugin_visible:
                plugin_status = "linked_and_visible"
                checks.append(self._ok_check("plugin_visible", "Le plugin Project OS est visible dans OpenClaw.", plugin_details))
            else:
                plugin_status = "linked_but_not_visible"
                checks.append(self._blocked_check("plugin_visible", "Le plugin n'apparait pas dans OpenClaw.", plugin_details))
                blocking_reasons.append("plugin_not_visible")
                actionable_fixes.append("Controle `openclaw plugins doctor` et la configuration du plugin.")
        else:
            plugin_status = "binary_missing"

        readiness = "ok" if not blocking_reasons else "bloque"
        report = OpenClawBootstrapReport(
            report_id=new_id("openclaw_bootstrap"),
            install_method=install_method,
            plugin_status=plugin_status,
            readiness=readiness,
            blocking_reasons=blocking_reasons,
            actionable_fixes=list(dict.fromkeys(actionable_fixes)),
            checks=checks,
            metadata={"runtime_roots": to_jsonable(runtime_roots)},
        )
        self._write_report(self.paths.openclaw_bootstrap_report_path, report)
        self.logger.log(
            "info",
            "openclaw_bootstrap_completed",
            readiness=report.readiness,
            install_method=report.install_method,
            plugin_status=report.plugin_status,
        )
        return report

    def doctor(self, *, with_system_doctor: bool = False) -> OpenClawDoctorReport:
        runtime_roots = self.runtime_roots()
        checks: list[dict[str, Any]] = []
        actionable_fixes: list[str] = []
        blocking = False

        binary_path = self._resolve_openclaw_binary()
        if binary_path:
            checks.append(self._ok_check("openclaw_binaire", f"OpenClaw est disponible: {binary_path}"))
        else:
            checks.append(self._blocked_check("openclaw_binaire", "OpenClaw n'est pas installe."))
            actionable_fixes.append("Installe OpenClaw pour activer le mode live.")
            blocking = True

        checks.extend(self._doctor_runtime_roots(runtime_roots, actionable_fixes))
        manifest_check = self._doctor_manifest()
        checks.append(manifest_check)
        blocking = blocking or manifest_check["status"] == "bloque"
        if manifest_check["status"] == "bloque":
            actionable_fixes.append("Le manifest OpenClaw doit rester valide et embarquer `configSchema`.")

        entrypoint_check = self._doctor_entrypoint()
        checks.append(entrypoint_check)
        blocking = blocking or entrypoint_check["status"] == "bloque"
        if entrypoint_check["status"] == "bloque":
            actionable_fixes.append("Repare l'entree Python `project_os_entry.py` ou sa config.")

        channels_check = self._doctor_channels()
        checks.append(channels_check)
        blocking = blocking or channels_check["status"] == "bloque"
        if channels_check["status"] == "bloque":
            actionable_fixes.append("Les canaux OpenClaw autorises doivent rester `discord` et/ou `webchat`.")

        speech_check = self._doctor_speech_policy()
        checks.append(speech_check)
        blocking = blocking or speech_check["status"] == "bloque"
        if speech_check["status"] == "bloque":
            actionable_fixes.append("Le plugin OpenClaw doit rester en mode reponse silencieuse pendant les runs.")

        if binary_path:
            plugin_visible, plugin_details = self._plugin_visible()
            plugin_check = (
                self._ok_check("plugin_visible", "Le plugin Project OS est visible dans OpenClaw.", plugin_details)
                if plugin_visible
                else self._blocked_check("plugin_visible", "Le plugin Project OS n'apparait pas dans OpenClaw.", plugin_details)
            )
            checks.append(plugin_check)
            blocking = blocking or plugin_check["status"] == "bloque"
            if plugin_check["status"] == "bloque":
                actionable_fixes.append("Relance `project-os openclaw bootstrap` pour relier le plugin Project OS dans OpenClaw.")

            plugin_doctor = self._run_openclaw_command(["plugins", "doctor"], timeout_ms=self.config.openclaw_config.timeout_ms)
            checks.append(
                self._ok_check("plugins_doctor", "OpenClaw signale un etat plugin sain.", plugin_doctor["parsed"] or plugin_doctor["stdout"])
                if plugin_doctor["ok"]
                else self._warn_check("plugins_doctor", "OpenClaw a remonte des alertes plugin.", plugin_doctor["stderr"] or plugin_doctor["stdout"])
            )
            config_validate = self._run_openclaw_command(["config", "validate", "--json"], timeout_ms=self.config.openclaw_config.timeout_ms)
            checks.append(
                self._ok_check("config_validate", "La configuration OpenClaw est valide.", config_validate["parsed"] or config_validate["stdout"])
                if config_validate["ok"]
                else self._warn_check("config_validate", "La configuration OpenClaw doit etre revue.", config_validate["stderr"] or config_validate["stdout"])
            )
            gateway_status = self._run_openclaw_command(["gateway", "status", "--json", "--no-probe"], timeout_ms=self.config.openclaw_config.timeout_ms)
            checks.append(
                self._ok_check("gateway_status", "Le statut gateway OpenClaw est lisible.", gateway_status["parsed"] or gateway_status["stdout"])
                if gateway_status["ok"]
                else self._warn_check("gateway_status", "Le statut gateway OpenClaw n'a pas pu etre lu.", gateway_status["stderr"] or gateway_status["stdout"])
            )
            if with_system_doctor:
                system_doctor = self._run_openclaw_command(["doctor", "--non-interactive"], timeout_ms=90000)
                checks.append(
                    self._ok_check("system_doctor", "Le doctor systeme OpenClaw s'est termine proprement.", system_doctor["stdout"])
                    if system_doctor["ok"]
                    else self._warn_check("system_doctor", "Le doctor systeme OpenClaw a besoin d'une verification humaine.", system_doctor["stderr"] or system_doctor["stdout"])
                )

        verdict = "OK" if not blocking else "bloque"
        summary = "OpenClaw est pret." if verdict == "OK" else "OpenClaw n'est pas encore pret pour le live."
        report = OpenClawDoctorReport(
            report_id=new_id("openclaw_doctor"),
            verdict=verdict,
            summary=summary,
            actionable_fixes=list(dict.fromkeys(actionable_fixes)),
            checks=checks,
            runtime_roots=runtime_roots,
            metadata={"with_system_doctor": with_system_doctor},
        )
        self._write_report(self.paths.openclaw_doctor_report_path, report)
        self.logger.log("info", "openclaw_doctor_completed", verdict=report.verdict)
        return report

    def replay(self, *, fixture_id: str | None = None, run_all: bool = False) -> dict[str, Any]:
        if fixture_id and run_all:
            raise ValueError("Choisis soit --fixture, soit --all.")
        fixtures = self._load_replay_fixtures()
        selected = fixtures if run_all or fixture_id is None else [item for item in fixtures if item["fixture_id"] == fixture_id]
        if not selected:
            raise KeyError(f"Fixture introuvable: {fixture_id}")

        results: list[OpenClawReplayResult] = []
        all_passed = True
        for raw_fixture in selected:
            fixture = self._fixture_from_payload(raw_fixture)
            replay_result = self._run_single_replay(raw_fixture, fixture)
            results.append(replay_result)
            all_passed = all_passed and replay_result.passed
            report_path = self.paths.openclaw_replay_root / f"{fixture.fixture_id}.json"
            self._write_json(report_path, replay_result)

        summary = {
            "report_id": new_id("openclaw_replay_report"),
            "verdict": "OK" if all_passed else "bloque",
            "total": len(results),
            "passed": sum(1 for item in results if item.passed),
            "failed": sum(1 for item in results if not item.passed),
            "results": [to_jsonable(item) for item in results],
        }
        self._write_json(self.paths.openclaw_replay_report_path, summary)
        self.logger.log("info", "openclaw_replay_completed", verdict=summary["verdict"], total=summary["total"])
        return summary

    def validate_live(self, *, channel: str, payload_file: str) -> OpenClawLiveValidationResult:
        normalized_channel = channel.strip().lower()
        report = self._load_json_if_exists(self.paths.openclaw_replay_report_path)
        if self.config.openclaw_config.require_replay_before_live and (not report or report.get("verdict") != "OK"):
            result = OpenClawLiveValidationResult(
                validation_id=new_id("openclaw_live"),
                channel=normalized_channel,
                success=False,
                failure_reason="Replay OpenClaw non valide. Le live reste bloque.",
                metadata={"replay_required": True},
            )
            self._write_report(self.paths.openclaw_live_validation_report_path, result)
            return result

        if normalized_channel not in {item.lower() for item in self.config.openclaw_config.enabled_channels}:
            result = OpenClawLiveValidationResult(
                validation_id=new_id("openclaw_live"),
                channel=normalized_channel,
                success=False,
                failure_reason="Canal non active dans la configuration OpenClaw.",
                metadata={"enabled_channels": self.config.openclaw_config.enabled_channels},
            )
            self._write_report(self.paths.openclaw_live_validation_report_path, result)
            return result

        binary_path = self._resolve_openclaw_binary()
        if not binary_path:
            result = OpenClawLiveValidationResult(
                validation_id=new_id("openclaw_live"),
                channel=normalized_channel,
                success=False,
                failure_reason="OpenClaw n'est pas installe sur ce poste. Validation live impossible.",
            )
            self._write_report(self.paths.openclaw_live_validation_report_path, result)
            return result

        payload_path = Path(payload_file)
        if not payload_path.exists():
            result = OpenClawLiveValidationResult(
                validation_id=new_id("openclaw_live"),
                channel=normalized_channel,
                success=False,
                failure_reason="Le payload live demande est introuvable.",
                metadata={"payload_file": str(payload_path)},
            )
            self._write_report(self.paths.openclaw_live_validation_report_path, result)
            return result

        doctor_report = self.doctor()
        if doctor_report.verdict != "OK":
            result = OpenClawLiveValidationResult(
                validation_id=new_id("openclaw_live"),
                channel=normalized_channel,
                success=False,
                failure_reason="Le doctor OpenClaw n'est pas vert. Le live reste bloque.",
                metadata={"doctor_verdict": doctor_report.verdict},
            )
            self._write_report(self.paths.openclaw_live_validation_report_path, result)
            return result

        result = OpenClawLiveValidationResult(
            validation_id=new_id("openclaw_live"),
            channel=normalized_channel,
            success=False,
            failure_reason="Le payload live est present, mais aucune validation reelle Discord/WebChat n'a encore ete jouee sur ce poste.",
            metadata={"payload_file": str(payload_path), "live_mode": "fail_closed"},
        )
        self._write_report(self.paths.openclaw_live_validation_report_path, result)
        return result

    def _resolve_plugin_source_path(self) -> Path:
        configured = self.config.openclaw_config.plugin_source_path
        if configured:
            return Path(configured).resolve(strict=False)
        return (self.repo_root / "integrations" / "openclaw" / "project-os-gateway-adapter").resolve(strict=False)

    def _run_single_replay(self, raw_fixture: dict[str, Any], fixture: OpenClawReplayFixture) -> OpenClawReplayResult:
        target_profile = str(raw_fixture.get("pluginConfig", {}).get("defaultTargetProfile") or raw_fixture.get("target_profile") or "core")
        self._prepare_ready_session(target_profile)
        harness_result = self._run_replay_harness(raw_fixture["payload_path"])
        dispatch_result = harness_result.get("dispatch_result")
        metadata: dict[str, Any] = {
            "warnings": harness_result.get("warnings", []),
            "infos": harness_result.get("infos", []),
            "ack_sent": harness_result.get("ack_sent", False),
            "expected_route": fixture.expected_route,
        }

        if not isinstance(dispatch_result, dict):
            return OpenClawReplayResult(
                replay_result_id=new_id("openclaw_replay"),
                fixture_id=fixture.fixture_id,
                dispatch_status="failed",
                router_verdict="missing_dispatch_result",
                policy_verdict="plugin_or_cli_failed",
                passed=False,
                metadata=metadata,
            )

        operator_reply = dispatch_result.get("operator_reply") or {}
        promoted_memory_ids = dispatch_result.get("promoted_memory_ids") or []
        metadata["dispatch_result"] = dispatch_result
        metadata["human_readable_summary"] = operator_reply.get("summary")

        dispatch_status = str(operator_reply.get("reply_kind") or "unknown")
        router_verdict = "allowed" if dispatch_status != "blocked" else "blocked"
        policy_verdict = str(operator_reply.get("summary") or dispatch_result.get("metadata", {}).get("reply_kind") or "unknown")
        artifact_refs = [str(item) for item in promoted_memory_ids]
        run_card = dispatch_result.get("discord_run_card") or {}
        expected_promoted = fixture.expected_route.get("promoted_memory_count")
        expected_reply_kind = fixture.expected_route.get("reply_kind")
        expected_allowed = fixture.expected_route.get("allowed")

        passed = True
        if isinstance(expected_promoted, int) and len(promoted_memory_ids) != expected_promoted:
            passed = False
        if isinstance(expected_reply_kind, str) and dispatch_status != expected_reply_kind:
            passed = False
        if isinstance(expected_allowed, bool) and ((router_verdict == "allowed") != expected_allowed):
            passed = False

        return OpenClawReplayResult(
            replay_result_id=new_id("openclaw_replay"),
            fixture_id=fixture.fixture_id,
            dispatch_status=dispatch_status,
            router_verdict=router_verdict,
            policy_verdict=policy_verdict,
            promoted_memory_count=len(promoted_memory_ids),
            artifact_count=len(artifact_refs),
            passed=passed,
            run_card=run_card if isinstance(run_card, dict) else {},
            evidence_refs=artifact_refs,
            metadata=metadata,
        )

    def _prepare_ready_session(self, profile_name: str) -> None:
        session_id = f"openclaw_{profile_name}_ready"
        self.runtime.open_session(
            profile_name=profile_name,
            owner="openclaw_replay",
            status="ready",
            metadata={"source": "openclaw_replay"},
            session_id=session_id,
        )
        self.runtime.record_runtime_state(
            RuntimeState(
                runtime_state_id=new_id("runtime_state"),
                session_id=session_id,
                verdict=RuntimeVerdict.READY,
                active_profile=profile_name,
                status_summary="Session de replay OpenClaw prete.",
                metadata={"source": "openclaw_replay"},
            )
        )

    def _run_replay_harness(self, payload_path: str) -> dict[str, Any]:
        node_command = shutil.which("node") or shutil.which("node.exe")
        if not node_command:
            raise RuntimeError("Node.js est requis pour le replay OpenClaw.")
        harness_path = self.plugin_source_path / "replay_harness.mjs"
        result = subprocess.run(
            [
                node_command,
                str(harness_path),
                "--fixture",
                payload_path,
                "--repo-root",
                str(self.repo_root),
                "--config-path",
                str(self.config.storage_config_path),
                "--policy-path",
                str(self.config.runtime_policy_path),
                "--python-command",
                self._python_command(),
                "--timeout-ms",
                str(self.config.openclaw_config.timeout_ms),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(self.plugin_source_path),
            env=self._openclaw_env(),
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Replay OpenClaw en echec.")
        return json.loads(result.stdout)

    def _doctor_runtime_roots(self, runtime_roots: OpenClawRuntimeRoots, actionable_fixes: list[str]) -> list[dict[str, Any]]:
        checks: list[dict[str, Any]] = []
        for name, path, fix in (
            ("runtime_root", Path(runtime_roots.runtime_root), "Cree la racine runtime OpenClaw."),
            ("state_root", Path(runtime_roots.state_root), "Cree la racine d'etat OpenClaw."),
            ("config_project_os", Path(runtime_roots.storage_config_path), "Ajoute la config storage_roots.local.json de Project OS."),
            ("policy_project_os", Path(runtime_roots.runtime_policy_path), "Ajoute la policy runtime Project OS."),
        ):
            if path.exists():
                checks.append(self._ok_check(name, f"{name} est pret.", str(path)))
            else:
                checks.append(self._blocked_check(name, f"{name} est introuvable.", str(path)))
                actionable_fixes.append(fix)
        return checks

    def _doctor_manifest(self) -> dict[str, Any]:
        if not self.plugin_manifest_path.exists():
            return self._blocked_check("plugin_manifest", "Le manifest OpenClaw est introuvable.")
        try:
            manifest = json.loads(self.plugin_manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return self._blocked_check("plugin_manifest", "Le manifest OpenClaw n'est pas lisible.", str(exc))
        if not isinstance(manifest, dict) or not isinstance(manifest.get("configSchema"), dict):
            return self._blocked_check("plugin_manifest", "Le manifest OpenClaw doit contenir `configSchema`.", manifest)
        return self._ok_check("plugin_manifest", "Le manifest OpenClaw est valide.", {"id": manifest.get("id")})

    def _doctor_entrypoint(self) -> dict[str, Any]:
        if not self.project_os_entrypoint.exists():
            return self._blocked_check("python_entrypoint", "L'entree Python Project OS est introuvable.")
        result = subprocess.run(
            [
                self._python_command(),
                str(self.project_os_entrypoint),
                "--config-path",
                str(self.config.storage_config_path),
                "--policy-path",
                str(self.config.runtime_policy_path),
                "doctor",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(self.repo_root),
            env=self._openclaw_env(),
            check=False,
        )
        if result.returncode != 0:
            return self._blocked_check("python_entrypoint", "Project OS ne repond pas correctement via l'entree Python.", result.stderr or result.stdout)
        return self._ok_check("python_entrypoint", "L'entree Python Project OS est callable.")

    def _doctor_channels(self) -> dict[str, Any]:
        enabled = [item.lower() for item in self.config.openclaw_config.enabled_channels]
        allowed = {"discord", "webchat"}
        if not enabled:
            return self._blocked_check("channels", "Aucun canal OpenClaw n'est active.")
        if not set(enabled).issubset(allowed):
            return self._blocked_check("channels", "Un canal OpenClaw non prevu est configure.", enabled)
        return self._ok_check("channels", "Les canaux OpenClaw sont coherents.", enabled)

    def _doctor_speech_policy(self) -> dict[str, Any]:
        if self.config.openclaw_config.send_ack_replies:
            return self._blocked_check("speech_policy", "Les reponses automatiques OpenClaw doivent rester desactivees.")
        if self.config.execution_policy.default_run_speech_policy.value != "silent_until_terminal_state":
            return self._blocked_check("speech_policy", "La policy de parole des runs doit rester en mode silence + fin.")
        return self._ok_check("speech_policy", "La policy de parole est compatible avec le mode silence + fin.")

    def _plugin_visible(self) -> tuple[bool, Any]:
        listed = self._run_openclaw_command(["plugins", "list", "--json"], timeout_ms=self.config.openclaw_config.timeout_ms)
        parsed = listed["parsed"]
        plugin_id = self.config.openclaw_config.plugin_id
        if isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, dict) and str(item.get("id")) == plugin_id:
                    return True, item
        if isinstance(parsed, dict):
            plugins = parsed.get("plugins")
            if isinstance(plugins, list):
                for item in plugins:
                    if isinstance(item, dict) and str(item.get("id")) == plugin_id:
                        return True, item
        text = f"{listed['stdout']}\n{listed['stderr']}"
        return (plugin_id in text, text.strip())

    def _install_openclaw_from_local_checkout(self) -> dict[str, Any]:
        npm_command = shutil.which("npm.cmd") or shutil.which("npm")
        if not npm_command:
            return {"ok": False, "check": self._blocked_check("openclaw_install", "npm est introuvable sur cette machine.")}
        source = self.repo_root / "third_party" / "openclaw"
        if not source.exists():
            return {"ok": False, "check": self._blocked_check("openclaw_install", "Le checkout local de OpenClaw est introuvable.")}
        if not self._local_checkout_is_build_ready(source):
            return {
                "ok": False,
                "check": self._blocked_check(
                    "openclaw_install",
                    "Le checkout local OpenClaw n'est pas build-ready (dist manquant).",
                    "Utilise l'installation depuis le registre npm ou build le checkout avant de le lier.",
                ),
            }
        result = subprocess.run(
            [npm_command, "install", "-g", str(source), "--no-fund", "--no-audit"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(source),
            env=self._openclaw_env(),
            check=False,
        )
        if result.returncode == 0:
            return {"ok": True, "check": self._ok_check("openclaw_install", "OpenClaw a ete installe depuis le checkout local.")}
        return {"ok": False, "check": self._blocked_check("openclaw_install", "L'installation locale OpenClaw a echoue.", result.stderr or result.stdout)}

    def _install_openclaw_from_registry(self) -> dict[str, Any]:
        npm_command = shutil.which("npm.cmd") or shutil.which("npm")
        if not npm_command:
            return {"ok": False, "check": self._blocked_check("openclaw_install", "npm est introuvable sur cette machine.")}
        result = subprocess.run(
            [npm_command, "install", "-g", "openclaw@latest", "--no-fund", "--no-audit"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(self.repo_root),
            env=self._openclaw_env(),
            check=False,
        )
        if result.returncode == 0:
            return {"ok": True, "check": self._ok_check("openclaw_install", "OpenClaw a ete installe depuis le registre npm.")}
        return {"ok": False, "check": self._blocked_check("openclaw_install", "L'installation OpenClaw depuis le registre npm a echoue.", result.stderr or result.stdout)}

    def _resolve_openclaw_binary(self) -> str | None:
        for candidate in (
            self.config.openclaw_config.binary_command,
            f"{self.config.openclaw_config.binary_command}.cmd",
            f"{self.config.openclaw_config.binary_command}.exe",
        ):
            resolved = shutil.which(candidate)
            if resolved:
                return resolved
        user_npm_root = Path(os.environ.get("APPDATA", "")) / "npm"
        for candidate in (
            user_npm_root / self.config.openclaw_config.binary_command,
            user_npm_root / f"{self.config.openclaw_config.binary_command}.cmd",
            user_npm_root / f"{self.config.openclaw_config.binary_command}.ps1",
        ):
            if candidate.exists():
                return str(candidate)
        npm_command = shutil.which("npm.cmd") or shutil.which("npm")
        if npm_command:
            prefix = subprocess.run(
                [npm_command, "prefix", "-g"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(self.repo_root),
                env=self._openclaw_env(),
                check=False,
            )
            npm_prefix = prefix.stdout.strip()
            if npm_prefix:
                prefix_root = Path(npm_prefix)
                for candidate in (
                    prefix_root / self.config.openclaw_config.binary_command,
                    prefix_root / f"{self.config.openclaw_config.binary_command}.cmd",
                    prefix_root / f"{self.config.openclaw_config.binary_command}.ps1",
                ):
                    if candidate.exists():
                        return str(candidate)
        return None

    def _smoke_check_openclaw_binary(self, binary_path: str) -> dict[str, Any]:
        result = subprocess.run(
            [binary_path, "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(self.repo_root),
            env=self._openclaw_env(),
            check=False,
        )
        return {
            "ok": result.returncode == 0,
            "details": (result.stderr or result.stdout).strip(),
        }

    def _ensure_openclaw_roots(self) -> None:
        for path in (
            self.paths.openclaw_runtime_root,
            self.paths.openclaw_state_root,
            self.paths.openclaw_reports_root,
            self.paths.openclaw_replay_root,
            self.paths.openclaw_live_root,
        ):
            self.path_policy.ensure_allowed_write(path)
            path.mkdir(parents=True, exist_ok=True)

    def _run_openclaw_command(self, args: list[str], *, timeout_ms: int) -> dict[str, Any]:
        binary_path = self._resolve_openclaw_binary()
        if not binary_path:
            return {"ok": False, "stdout": "", "stderr": "openclaw binary missing", "parsed": None}
        result = subprocess.run(
            [binary_path, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(self.paths.openclaw_runtime_root),
            env=self._openclaw_env(),
            timeout=max(5, int(timeout_ms / 1000)),
            check=False,
        )
        parsed = None
        stdout = result.stdout.strip()
        if stdout:
            try:
                parsed = json.loads(stdout)
            except Exception:
                parsed = None
        return {
            "ok": result.returncode == 0,
            "stdout": stdout,
            "stderr": result.stderr.strip(),
            "parsed": parsed,
            "returncode": result.returncode,
        }

    def _openclaw_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["OPENCLAW_STATE_DIR"] = str(self.paths.openclaw_state_root)
        return env

    def _python_command(self) -> str:
        return shutil.which("py") or sys.executable

    @staticmethod
    def _local_checkout_is_build_ready(source: Path) -> bool:
        return (source / "dist" / "entry.js").exists() or (source / "dist" / "index.js").exists()

    def _load_replay_fixtures(self) -> list[dict[str, Any]]:
        if not self.fixtures_root.exists():
            raise FileNotFoundError("Le dossier de fixtures OpenClaw est introuvable.")
        fixtures: list[dict[str, Any]] = []
        for path in sorted(self.fixtures_root.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["payload_path"] = str(path)
            fixtures.append(payload)
        return fixtures

    def _fixture_from_payload(self, payload: dict[str, Any]) -> OpenClawReplayFixture:
        return OpenClawReplayFixture(
            fixture_id=str(payload["fixture_id"]),
            channel=str(payload["channel"]),
            thread_ref=str(payload["thread_ref"]),
            message_type=str(payload["message_type"]),
            attachments=[str(item) for item in payload.get("attachments", [])],
            expected_route=dict(payload.get("expected_route", {})),
            payload_path=str(payload["payload_path"]),
            description=payload.get("description"),
        )

    def _check_exists(
        self,
        checks: list[dict[str, Any]],
        name: str,
        path: Path,
        blocking_reasons: list[str],
        blocking_reason: str,
        actionable_fixes: list[str],
        actionable_fix: str,
    ) -> None:
        if path.exists():
            checks.append(self._ok_check(name, f"{name} pret.", str(path)))
        else:
            checks.append(self._blocked_check(name, f"{name} introuvable.", str(path)))
            blocking_reasons.append(blocking_reason)
            actionable_fixes.append(actionable_fix)

    @staticmethod
    def _ok_check(name: str, message: str, details: Any | None = None) -> dict[str, Any]:
        payload = {"name": name, "status": "ok", "message": message}
        if details is not None:
            payload["details"] = details
        return payload

    @staticmethod
    def _warn_check(name: str, message: str, details: Any | None = None) -> dict[str, Any]:
        payload = {"name": name, "status": "a_corriger", "message": message}
        if details is not None:
            payload["details"] = details
        return payload

    @staticmethod
    def _blocked_check(name: str, message: str, details: Any | None = None) -> dict[str, Any]:
        payload = {"name": name, "status": "bloque", "message": message}
        if details is not None:
            payload["details"] = details
        return payload

    def _write_report(self, path: Path, payload: Any) -> None:
        self._write_json(path, payload)

    def _write_json(self, path: Path, payload: Any) -> None:
        target = self.path_policy.ensure_allowed_write(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(to_jsonable(payload), ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")

    @staticmethod
    def _load_json_if_exists(path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
