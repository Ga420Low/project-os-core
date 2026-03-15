from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    import winreg  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover - unavailable outside Windows
    winreg = None  # type: ignore[assignment]

from ..config import RuntimeConfig
from ..database import CanonicalDatabase
from ..local_model import LocalModelClient
from ..models import (
    OpenClawBootstrapReport,
    OpenClawDoctorReport,
    OpenClawLiveValidationResult,
    OpenClawReplayFixture,
    OpenClawReplayResult,
    OpenClawRuntimeRoots,
    OpenClawSelfHealReport,
    OpenClawTrustAuditReport,
    OpenClawTruthHealthReport,
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
        local_model_client: LocalModelClient | None = None,
    ) -> None:
        self.config = config
        self.paths = paths
        self.path_policy = path_policy
        self.runtime = runtime
        self.database = database
        self.logger = logger
        self.local_model_client = local_model_client
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
        runtime_config, runtime_config_check = self._doctor_runtime_config()
        checks.append(runtime_config_check)
        blocking = blocking or runtime_config_check["status"] == "bloque"
        if runtime_config_check["status"] == "bloque":
            actionable_fixes.append("Le runtime OpenClaw live doit exposer un openclaw.json lisible dans la state root.")

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

        channels_check = self._doctor_channels(runtime_config)
        checks.append(channels_check)
        blocking = blocking or channels_check["status"] == "bloque"
        if channels_check["status"] == "bloque":
            actionable_fixes.append("Les canaux OpenClaw autorises doivent rester `discord` et/ou `webchat`.")

        speech_check = self._doctor_speech_policy(runtime_config)
        checks.append(speech_check)
        blocking = blocking or speech_check["status"] == "bloque"
        if speech_check["status"] == "bloque":
            actionable_fixes.append("Le plugin OpenClaw doit rester en mode reponse silencieuse pendant les runs.")

        runtime_secrets_check = self._doctor_runtime_secret_handling(runtime_config)
        checks.append(runtime_secrets_check)
        blocking = blocking or runtime_secrets_check["status"] == "bloque"
        if runtime_secrets_check["status"] == "bloque":
            actionable_fixes.append("Les secrets live OpenClaw doivent sortir du snapshot runtime et passer par SecretRef ou variables d'environnement.")

        discord_policy_check = self._doctor_runtime_discord_policy(runtime_config)
        checks.append(discord_policy_check)
        blocking = blocking or discord_policy_check["status"] == "bloque"
        if discord_policy_check["status"] == "bloque":
            mention_requirement = "requireMention=true" if self.config.openclaw_config.discord_require_mention else "requireMention=false"
            actionable_fixes.append(
                f"La boucle Discord live doit rester en allowlist stricte avec {mention_requirement} selon la policy retenue."
            )

        discord_operations_check = self._doctor_discord_operations_ux(runtime_config)
        checks.append(discord_operations_check)
        blocking = blocking or discord_operations_check["status"] == "bloque"
        if discord_operations_check["status"] == "bloque":
            actionable_fixes.append("Active `threadBindings`, `autoPresence` et `execApprovals` Discord selon la policy Pack 2 retenue.")

        privacy_guard_check = self._doctor_privacy_guard_policy()
        checks.append(privacy_guard_check)
        blocking = blocking or privacy_guard_check["status"] == "bloque"
        if privacy_guard_check["status"] == "bloque":
            actionable_fixes.append("La privacy guard Pack 4 doit rester active avec blocage `S3` sans voie locale sure.")

        local_model_check = self._doctor_local_model_route()
        checks.append(local_model_check)
        blocking = blocking or local_model_check["status"] == "bloque"
        if local_model_check["status"] == "bloque":
            actionable_fixes.append("La voie locale Windows-first doit etre prete si `local_model_enabled=true`.")

        plugins_allowlist_check = self._doctor_plugins_allowlist(runtime_config)
        checks.append(plugins_allowlist_check)
        blocking = blocking or plugins_allowlist_check["status"] == "bloque"
        if plugins_allowlist_check["status"] == "bloque":
            actionable_fixes.append("Ajoute une allowlist explicite des plugins OpenClaw autorises dans openclaw.json.")

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
            plugin_doctor_check = (
                self._ok_check("plugins_doctor", "OpenClaw signale un etat plugin sain.", plugin_doctor["parsed"] or plugin_doctor["stdout"])
                if plugin_doctor["ok"]
                else self._blocked_check("plugins_doctor", "OpenClaw a remonte des alertes plugin.", plugin_doctor["stderr"] or plugin_doctor["stdout"])
            )
            checks.append(plugin_doctor_check)
            blocking = blocking or plugin_doctor_check["status"] == "bloque"
            if plugin_doctor_check["status"] == "bloque":
                actionable_fixes.append("Corrige les alertes de `openclaw plugins doctor` avant de declarer la boucle live saine.")

            config_validate = self._run_openclaw_command(["config", "validate", "--json"], timeout_ms=self.config.openclaw_config.timeout_ms)
            config_validate_check = (
                self._ok_check("config_validate", "La configuration OpenClaw est valide.", config_validate["parsed"] or config_validate["stdout"])
                if config_validate["ok"] and self._openclaw_config_is_valid(config_validate["parsed"])
                else self._blocked_check("config_validate", "La configuration OpenClaw doit etre revue.", config_validate["parsed"] or config_validate["stderr"] or config_validate["stdout"])
            )
            checks.append(config_validate_check)
            blocking = blocking or config_validate_check["status"] == "bloque"
            if config_validate_check["status"] == "bloque":
                actionable_fixes.append("Le `openclaw config validate --json` doit rester franchement valide sur le runtime live.")

            gateway_status = self._gateway_status_command(runtime_config)
            gateway_status_check = self._doctor_gateway_status(gateway_status)
            checks.append(gateway_status_check)
            blocking = blocking or gateway_status_check["status"] == "bloque"
            if gateway_status_check["status"] == "bloque":
                actionable_fixes.append("Le service gateway OpenClaw doit etre charge et son runtime doit remonter un statut sain.")
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

    def truth_health(self, *, channel: str = "discord", max_age_hours: int | None = None) -> OpenClawTruthHealthReport:
        normalized_channel = channel.strip().lower()
        effective_max_age_hours = max(1, int(max_age_hours or self.config.openclaw_config.live_validation_max_age_hours))
        checks: list[dict[str, Any]] = []
        actionable_fixes: list[str] = []
        evidence_refs: list[str] = []

        doctor_report = self.doctor()
        doctor_check = (
            self._ok_check("baseline_doctor", "Le doctor OpenClaw de base est vert.", {"doctor_report_id": doctor_report.report_id})
            if doctor_report.verdict == "OK"
            else self._blocked_check("baseline_doctor", "Le doctor OpenClaw n'est pas encore vert.", {"doctor_report_id": doctor_report.report_id, "summary": doctor_report.summary})
        )
        checks.append(doctor_check)
        if doctor_check["status"] == "bloque":
            actionable_fixes.append("Corrige d'abord `project-os openclaw doctor` avant de conclure sur la verite live.")

        replay_check = self._truth_health_replay_check()
        checks.append(replay_check)
        if replay_check["status"] != "ok":
            actionable_fixes.append("Relance `project-os openclaw replay --all` jusqu'a obtenir un verdict `OK`.")

        startup_check = self._truth_health_startup_fallback_check()
        checks.append(startup_check)
        if startup_check["status"] != "ok":
            actionable_fixes.append("Supprime le fallback `Startup` une fois la tache planifiee OpenClaw saine.")

        runtime_config, _ = self._doctor_runtime_config()
        gateway_check = self._doctor_gateway_status(self._gateway_status_command(runtime_config))
        checks.append(gateway_check)
        if gateway_check["status"] == "bloque":
            actionable_fixes.append("Le gateway doit rester charge, avec listener local ou RPC sain, avant toute conclusion live.")

        self._refresh_discord_thread_binding_projection()

        live_check, live_refs, live_fix = self._truth_health_live_proof_check(
            normalized_channel=normalized_channel,
            max_age_hours=effective_max_age_hours,
        )
        checks.append(live_check)
        evidence_refs.extend(live_refs)
        if live_fix:
            actionable_fixes.append(live_fix)

        binding_projection_check = self._truth_health_thread_binding_projection_check(
            normalized_channel=normalized_channel,
            max_age_hours=effective_max_age_hours,
        )
        checks.append(binding_projection_check)
        if binding_projection_check["status"] == "bloque":
            actionable_fixes.append("Le runtime doit projeter un binding durable `discord thread -> mission/session` avant de declarer Pack 2 termine.")
        elif binding_projection_check["status"] == "a_corriger":
            actionable_fixes.append("Produis au moins un event Discord recent pour prouver la projection des thread bindings.")

        statuses = {item["status"] for item in checks}
        if "bloque" in statuses:
            verdict = "bloque"
            summary = "OpenClaw n'est pas encore sain sur ce poste."
        elif "a_corriger" in statuses:
            verdict = "a_corriger"
            summary = "OpenClaw est sain cote machine, mais la preuve live finale manque encore."
        else:
            verdict = "OK"
            summary = "OpenClaw est sain sur Windows et une preuve live recente est presente."

        report = OpenClawTruthHealthReport(
            report_id=new_id("openclaw_truth_health"),
            verdict=verdict,
            summary=summary,
            channel=normalized_channel,
            actionable_fixes=list(dict.fromkeys(actionable_fixes)),
            checks=checks,
            evidence_refs=evidence_refs,
            metadata={
                "doctor_report_id": doctor_report.report_id,
                "max_age_hours": effective_max_age_hours,
            },
        )
        self._write_report(self.paths.openclaw_truth_health_report_path, report)
        self.logger.log("info", "openclaw_truth_health_completed", verdict=report.verdict, channel=normalized_channel)
        return report

    def trust_audit(self) -> OpenClawTrustAuditReport:
        checks: list[dict[str, Any]] = []
        actionable_fixes: list[str] = []

        runtime_config, runtime_config_check = self._doctor_runtime_config()
        checks.append(runtime_config_check)
        if runtime_config_check["status"] == "bloque":
            actionable_fixes.append("Le runtime OpenClaw doit exposer un `openclaw.json` lisible pour auditer le trust.")

        runtime_secret_check = self._doctor_runtime_secret_handling(runtime_config)
        checks.append(runtime_secret_check)
        if runtime_secret_check["status"] == "bloque":
            actionable_fixes.append("Les secrets longs doivent rester hors snapshot runtime et hors logs visibles.")

        plugins_allowlist_check = self._doctor_plugins_allowlist(runtime_config)
        checks.append(plugins_allowlist_check)
        if plugins_allowlist_check["status"] == "bloque":
            actionable_fixes.append("La trust boundary plugin doit rester bornee a une allowlist explicite.")

        plugin_catalog_check = self._trust_audit_plugin_catalog(runtime_config)
        checks.append(plugin_catalog_check)
        if plugin_catalog_check["status"] == "bloque":
            actionable_fixes.append("Les plugins actifs doivent correspondre aux ids et origines explicitement approuves.")

        plugin_install_check = self._trust_audit_plugin_install_policy(runtime_config)
        checks.append(plugin_install_check)
        if plugin_install_check["status"] == "bloque":
            actionable_fixes.append("La provenance d'installation du plugin doit rester bornee, explicite et reproductible.")

        pairing_state_check, pairing_state = self._trust_audit_pairing_store()
        checks.append(pairing_state_check)
        if pairing_state_check["status"] == "bloque":
            actionable_fixes.append("Le store de pairing doit rester coherent, local et scope par device.")
        elif pairing_state_check["status"] == "a_corriger":
            actionable_fixes.append("Approuve, rejette ou laisse expirer les pairings en attente avant de refermer le lot.")

        rotation_check = self._trust_audit_pairing_token_rotation(pairing_state)
        checks.append(rotation_check)
        if rotation_check["status"] == "a_corriger":
            actionable_fixes.append("Tourne ou re-pair les devices dont le token operateur depasse la fenetre retenue.")

        secret_exposure_check = self._trust_audit_pairing_secret_exposure(pairing_state)
        checks.append(secret_exposure_check)
        if secret_exposure_check["status"] == "bloque":
            actionable_fixes.append("Revoque le token fuite, nettoie les traces chat/log et re-pair avec un bootstrap court.")

        statuses = {item["status"] for item in checks}
        if "bloque" in statuses:
            verdict = "bloque"
            summary = "Le trust plugin/pairing OpenClaw n'est pas encore assez dur."
        elif "a_corriger" in statuses:
            verdict = "a_corriger"
            summary = "Le trust plugin/pairing est globalement sain, mais il reste de l'hygiene a refermer."
        else:
            verdict = "OK"
            summary = "Le trust plugin/pairing OpenClaw est borne et prouvable localement."

        report = OpenClawTrustAuditReport(
            report_id=new_id("openclaw_trust_audit"),
            verdict=verdict,
            summary=summary,
            actionable_fixes=list(dict.fromkeys(actionable_fixes)),
            checks=checks,
            metadata={
                "trusted_plugin_ids": sorted(set(self.config.openclaw_config.trusted_plugin_ids)),
                "pairing_rotation_max_age_days": int(self.config.openclaw_config.pairing_rotation_max_age_days),
            },
        )
        self._write_report(self.paths.openclaw_trust_audit_report_path, report)
        self.logger.log("info", "openclaw_trust_audit_completed", verdict=report.verdict)
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

    def validate_live(self, *, channel: str, payload_file: str | None = None, max_age_hours: int | None = None) -> OpenClawLiveValidationResult:
        normalized_channel = channel.strip().lower()
        effective_max_age_hours = max(1, int(max_age_hours or self.config.openclaw_config.live_validation_max_age_hours))
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

        payload_path: Path | None = None
        if payload_file:
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

        live_check, evidence_refs, _ = self._truth_health_live_proof_check(
            normalized_channel=normalized_channel,
            max_age_hours=effective_max_age_hours,
        )
        if live_check["status"] != "ok":
            result = OpenClawLiveValidationResult(
                validation_id=new_id("openclaw_live"),
                channel=normalized_channel,
                success=False,
                failure_reason=str(live_check["message"]),
                evidence_refs=evidence_refs,
                metadata={
                    "payload_file": str(payload_path) if payload_path else None,
                    "max_age_hours": effective_max_age_hours,
                    "live_mode": "truth_proof_required",
                },
            )
            self._write_report(self.paths.openclaw_live_validation_report_path, result)
            return result

        result = OpenClawLiveValidationResult(
            validation_id=new_id("openclaw_live"),
            channel=normalized_channel,
            success=True,
            evidence_refs=evidence_refs,
            metadata={
                "payload_file": str(payload_path) if payload_path else None,
                "max_age_hours": effective_max_age_hours,
                "live_mode": "proof_recorded",
            },
        )
        self._write_report(self.paths.openclaw_live_validation_report_path, result)
        return result

    def self_heal(self, *, ignore_cooldown: bool = False) -> OpenClawSelfHealReport:
        checks: list[dict[str, Any]] = []
        actions: list[str] = []
        metadata: dict[str, Any] = {
            "cooldown_seconds": int(self.config.openclaw_config.self_heal_cooldown_seconds),
            "ignore_cooldown": bool(ignore_cooldown),
        }

        binary_path = self._resolve_openclaw_binary()
        if not binary_path:
            report = OpenClawSelfHealReport(
                report_id=new_id("openclaw_self_heal"),
                status="failed",
                summary="OpenClaw est introuvable. Auto-reparation impossible.",
                checks=[self._blocked_check("openclaw_binaire", "OpenClaw est introuvable sur ce poste.")],
                metadata=metadata,
            )
            self._write_report(self.paths.openclaw_self_heal_report_path, report)
            return report

        runtime_config = self._load_json_payload(self.paths.openclaw_state_root / "openclaw.json")
        if not isinstance(runtime_config, dict):
            report = OpenClawSelfHealReport(
                report_id=new_id("openclaw_self_heal"),
                status="failed",
                summary="openclaw.json est introuvable ou invalide. Auto-reparation impossible.",
                checks=[self._blocked_check("runtime_config", "Le snapshot runtime OpenClaw est introuvable ou invalide.")],
                metadata=metadata,
            )
            self._write_report(self.paths.openclaw_self_heal_report_path, report)
            return report

        before_result = self._gateway_status_command(runtime_config)
        before_details = self._gateway_truth_details_from_command(before_result)
        if before_details["healthy"]:
            checks.append(self._ok_check("gateway_before", "Le gateway est deja sain.", before_details))
            report = OpenClawSelfHealReport(
                report_id=new_id("openclaw_self_heal"),
                status="healthy",
                summary="Le gateway OpenClaw etait deja sain. Aucune action necessaire.",
                checks=checks,
                metadata={**metadata, "before": before_details, "final": before_details},
            )
            self._write_report(self.paths.openclaw_self_heal_report_path, report)
            self.logger.log("info", "openclaw_self_heal_completed", status=report.status)
            return report

        checks.append(self._warn_check("gateway_before", "Le gateway OpenClaw a besoin d'une reparation.", before_details))
        metadata["before"] = before_details

        cooldown = self._self_heal_cooldown_state(ignore_cooldown=ignore_cooldown)
        if cooldown["active"]:
            checks.append(self._warn_check("cooldown", "Une tentative recente existe deja. Cooldown actif.", cooldown))
            report = OpenClawSelfHealReport(
                report_id=new_id("openclaw_self_heal"),
                status="cooldown_skip",
                summary="Le gateway reste degrade, mais une tentative recente existe deja. Nouvelle relance differee.",
                actions=actions,
                checks=checks,
                metadata={**metadata, "cooldown": cooldown, "final": before_details},
            )
            self._write_report(self.paths.openclaw_self_heal_report_path, report)
            self.logger.log("warning", "openclaw_self_heal_completed", status=report.status)
            return report

        restart_result = self._run_openclaw_command(["gateway", "restart"], timeout_ms=self.config.openclaw_config.timeout_ms)
        actions.append("gateway_restart")
        checks.append(self._command_check("gateway_restart", "Tentative de restart du gateway.", restart_result))
        after_restart_result = self._gateway_status_command(runtime_config)
        after_restart_details = self._gateway_truth_details_from_command(after_restart_result)
        checks.append(self._status_check("gateway_after_restart", after_restart_details, "Le gateway est sain apres restart.", "Le gateway reste degrade apres restart."))
        if after_restart_details["healthy"]:
            report = OpenClawSelfHealReport(
                report_id=new_id("openclaw_self_heal"),
                status="restarted",
                summary="Le gateway OpenClaw a ete repare par restart.",
                actions=actions,
                checks=checks,
                metadata={
                    **metadata,
                    "before": before_details,
                    "after_restart": after_restart_details,
                    "final": after_restart_details,
                    "last_repair_attempt_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            self._write_report(self.paths.openclaw_self_heal_report_path, report)
            self.logger.log("warning", "openclaw_self_heal_completed", status=report.status)
            return report

        start_result = self._run_openclaw_command(["gateway", "start"], timeout_ms=self.config.openclaw_config.timeout_ms)
        actions.append("gateway_start")
        checks.append(self._command_check("gateway_start", "Tentative de demarrage du gateway.", start_result))
        after_start_result = self._gateway_status_command(runtime_config)
        after_start_details = self._gateway_truth_details_from_command(after_start_result)
        checks.append(self._status_check("gateway_after_start", after_start_details, "Le gateway est sain apres demarrage.", "Le gateway reste degrade apres demarrage."))

        repaired = after_start_details["healthy"]
        report = OpenClawSelfHealReport(
            report_id=new_id("openclaw_self_heal"),
            status="started" if repaired else "failed",
            summary=(
                "Le gateway OpenClaw a ete repare par demarrage explicite."
                if repaired
                else "Le gateway OpenClaw reste degrade apres restart + start. Intervention humaine requise."
            ),
            actions=actions,
            checks=checks,
            metadata={
                **metadata,
                "before": before_details,
                "after_restart": after_restart_details,
                "after_start": after_start_details,
                "final": after_start_details,
                "last_repair_attempt_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        self._write_report(self.paths.openclaw_self_heal_report_path, report)
        self.logger.log("warning" if repaired else "error", "openclaw_self_heal_completed", status=report.status)
        return report

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

    def _doctor_channels(self, runtime_config: dict[str, Any] | None) -> dict[str, Any]:
        enabled = self._runtime_enabled_channels(runtime_config)
        allowed = {"discord", "webchat"}
        if not enabled:
            return self._blocked_check("channels", "Aucun canal OpenClaw n'est active.")
        if not set(enabled).issubset(allowed):
            return self._blocked_check("channels", "Un canal OpenClaw non prevu est configure.", enabled)
        return self._ok_check("channels", "Les canaux OpenClaw sont coherents.", enabled)

    def _doctor_speech_policy(self, runtime_config: dict[str, Any] | None) -> dict[str, Any]:
        if self._runtime_send_ack_replies(runtime_config):
            return self._blocked_check("speech_policy", "Les reponses automatiques OpenClaw doivent rester desactivees.", {"sendAckReplies": True})
        if self.config.execution_policy.default_run_speech_policy.value != "silent_until_terminal_state":
            return self._blocked_check("speech_policy", "La policy de parole des runs doit rester en mode silence + fin.")
        return self._ok_check("speech_policy", "La policy de parole est compatible avec le mode silence + fin.")

    def _doctor_runtime_config(self) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        config_path = self.paths.openclaw_state_root / "openclaw.json"
        if not config_path.exists():
            return None, self._blocked_check("runtime_config", "Le snapshot runtime OpenClaw est introuvable.", str(config_path))
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            return None, self._blocked_check("runtime_config", "Le snapshot runtime OpenClaw n'est pas lisible.", str(exc))
        if not isinstance(payload, dict):
            return None, self._blocked_check("runtime_config", "Le snapshot runtime OpenClaw doit etre un objet JSON.", str(config_path))
        return payload, self._ok_check("runtime_config", "Le snapshot runtime OpenClaw est lisible.", str(config_path))

    def _doctor_runtime_secret_handling(self, runtime_config: dict[str, Any] | None) -> dict[str, Any]:
        if runtime_config is None:
            return self._blocked_check("runtime_secrets", "Impossible de verifier les secrets sans snapshot runtime OpenClaw.")

        issues: list[dict[str, str]] = []
        active_discord_account = None
        plugins = runtime_config.get("plugins")
        entries = plugins.get("entries") if isinstance(plugins, dict) else None
        adapter = entries.get(self.config.openclaw_config.plugin_id) if isinstance(entries, dict) else None
        adapter_config = adapter.get("config") if isinstance(adapter, dict) else None
        if isinstance(adapter_config, dict):
            candidate_account = adapter_config.get("discordAccountId")
            if isinstance(candidate_account, str) and candidate_account.strip():
                active_discord_account = candidate_account.strip()
        channels = runtime_config.get("channels")
        if isinstance(channels, dict):
            discord = channels.get("discord")
            if isinstance(discord, dict):
                accounts = discord.get("accounts")
                if isinstance(accounts, dict):
                    for account_id, account in accounts.items():
                        if not isinstance(account, dict) or account.get("enabled") is False:
                            continue
                        has_token = account.get("token") is not None
                        explicitly_enabled = account.get("enabled") is True
                        is_active_account = str(account_id) == active_discord_account
                        if not (has_token or explicitly_enabled or is_active_account):
                            continue
                        token_mode = self._secret_input_mode(account.get("token"), env_var_names=("DISCORD_BOT_TOKEN",))
                        if token_mode == "plaintext":
                            issues.append({"path": f"channels.discord.accounts.{account_id}.token", "reason": "plaintext"})
                        elif token_mode == "missing":
                            issues.append({"path": f"channels.discord.accounts.{account_id}.token", "reason": "missing"})

        gateway = runtime_config.get("gateway")
        auth = gateway.get("auth") if isinstance(gateway, dict) else None
        if isinstance(auth, dict):
            token_mode = self._secret_input_mode(auth.get("token"), env_var_names=("OPENCLAW_GATEWAY_TOKEN",))
            if token_mode == "plaintext":
                issues.append({"path": "gateway.auth.token", "reason": "plaintext"})
            elif token_mode == "missing":
                issues.append({"path": "gateway.auth.token", "reason": "missing"})

        if issues:
            return self._blocked_check(
                "runtime_secrets",
                "Le runtime OpenClaw expose encore des secrets live en clair ou non resolus.",
                issues,
            )
        return self._ok_check("runtime_secrets", "Les secrets live OpenClaw passent par SecretRef ou variables d'environnement.")

    def _doctor_runtime_discord_policy(self, runtime_config: dict[str, Any] | None) -> dict[str, Any]:
        if runtime_config is None:
            return self._blocked_check("discord_policy", "Impossible de verifier la policy Discord sans snapshot runtime OpenClaw.")

        channels = runtime_config.get("channels")
        discord = channels.get("discord") if isinstance(channels, dict) else None
        if not isinstance(discord, dict) or discord.get("enabled") is False:
            return self._ok_check("discord_policy", "Le canal Discord live n'est pas actif.")

        issues: list[dict[str, Any]] = []
        expected_require_mention = bool(self.config.openclaw_config.discord_require_mention)
        if str(discord.get("groupPolicy") or "").strip().lower() == "open":
            issues.append({"path": "channels.discord.groupPolicy", "value": "open"})

        accounts = discord.get("accounts")
        if isinstance(accounts, dict):
            for account_id, account in accounts.items():
                if not isinstance(account, dict) or account.get("enabled", True) is False:
                    continue
                if str(account.get("groupPolicy") or "").strip().lower() == "open":
                    issues.append({"path": f"channels.discord.accounts.{account_id}.groupPolicy", "value": "open"})

        guilds = discord.get("guilds")
        if isinstance(guilds, dict):
            for guild_id, guild_payload in guilds.items():
                if not isinstance(guild_payload, dict):
                    continue
                guild_channels = guild_payload.get("channels")
                guild_level_require_mention = guild_payload.get("requireMention")
                if isinstance(guild_channels, dict) and guild_channels:
                    for channel_id, channel_payload in guild_channels.items():
                        if not isinstance(channel_payload, dict):
                            continue
                        effective_require_mention = channel_payload.get("requireMention", guild_level_require_mention)
                        if effective_require_mention is not expected_require_mention:
                            issues.append(
                                {
                                    "path": f"channels.discord.guilds.{guild_id}.channels.{channel_id}.requireMention",
                                    "value": effective_require_mention,
                                    "expected": expected_require_mention,
                                }
                            )
                elif guild_level_require_mention is not expected_require_mention:
                    issues.append(
                        {
                            "path": f"channels.discord.guilds.{guild_id}.requireMention",
                            "value": guild_level_require_mention,
                            "expected": expected_require_mention,
                        }
                    )

        if issues:
            expectation = "mention obligatoire" if expected_require_mention else "ecoute sans mention sur les salons allowlistes"
            return self._blocked_check(
                "discord_policy",
                f"La boucle Discord live doit rester en allowlist stricte avec {expectation}.",
                issues,
            )
        if expected_require_mention:
            return self._ok_check("discord_policy", "La policy Discord live est durcie.")
        return self._ok_check("discord_policy", "La policy Discord live est durcie avec ecoute sans mention sur le serveur prive.")

    def _doctor_discord_operations_ux(self, runtime_config: dict[str, Any] | None) -> dict[str, Any]:
        if runtime_config is None:
            return self._blocked_check(
                "discord_operations_ux",
                "Impossible de verifier les features Discord Pack 2 sans snapshot runtime OpenClaw.",
            )

        if "discord" not in self._runtime_enabled_channels(runtime_config):
            return self._ok_check("discord_operations_ux", "Discord n'est pas actif: controle Pack 2 non applicable.")

        session_config = runtime_config.get("session")
        session_thread_bindings = (
            session_config.get("threadBindings") if isinstance(session_config, dict) else None
        )
        channels = runtime_config.get("channels")
        discord = channels.get("discord") if isinstance(channels, dict) else None
        if not isinstance(discord, dict):
            return self._blocked_check("discord_operations_ux", "La section `channels.discord` est absente du runtime OpenClaw.")

        issues: list[dict[str, Any]] = []

        if self.config.openclaw_config.discord_thread_bindings_required:
            if not (isinstance(session_thread_bindings, dict) and session_thread_bindings.get("enabled") is True):
                issues.append({"path": "session.threadBindings.enabled", "reason": "missing_or_disabled"})
            channel_thread_bindings = discord.get("threadBindings")
            if not (isinstance(channel_thread_bindings, dict) and channel_thread_bindings.get("enabled") is True):
                issues.append({"path": "channels.discord.threadBindings.enabled", "reason": "missing_or_disabled"})
            elif channel_thread_bindings.get("spawnSubagentSessions") is True:
                issues.append({"path": "channels.discord.threadBindings.spawnSubagentSessions", "reason": "must_remain_false"})

        if self.config.openclaw_config.discord_auto_presence_required:
            auto_presence = discord.get("autoPresence")
            if not (isinstance(auto_presence, dict) and auto_presence.get("enabled") is True):
                issues.append({"path": "channels.discord.autoPresence.enabled", "reason": "missing_or_disabled"})

        if self.config.openclaw_config.discord_exec_approvals_required:
            exec_approvals = discord.get("execApprovals")
            if not (isinstance(exec_approvals, dict) and exec_approvals.get("enabled") is True):
                issues.append({"path": "channels.discord.execApprovals.enabled", "reason": "missing_or_disabled"})
            else:
                approvers = exec_approvals.get("approvers")
                normalized_approvers = {
                    str(item).strip()
                    for item in (approvers if isinstance(approvers, list) else [])
                    if str(item).strip()
                }
                expected_approvers = {
                    str(item).strip()
                    for item in self.config.openclaw_config.discord_exec_approver_ids
                    if str(item).strip()
                }
                if not normalized_approvers:
                    issues.append({"path": "channels.discord.execApprovals.approvers", "reason": "empty"})
                elif expected_approvers and not expected_approvers.issubset(normalized_approvers):
                    issues.append(
                        {
                            "path": "channels.discord.execApprovals.approvers",
                            "reason": "missing_expected_approvers",
                            "expected": sorted(expected_approvers),
                            "actual": sorted(normalized_approvers),
                        }
                    )
                target = str(exec_approvals.get("target") or "").strip().lower()
                expected_target = self.config.openclaw_config.discord_exec_target.strip().lower()
                if target != expected_target:
                    issues.append(
                        {
                            "path": "channels.discord.execApprovals.target",
                            "reason": "unexpected_target",
                            "expected": expected_target,
                            "actual": target or None,
                        }
                    )

        if issues:
            return self._blocked_check(
                "discord_operations_ux",
                "Le runtime Discord OpenClaw n'embarque pas encore le socle UX retenu pour Pack 2.",
                issues,
            )
        return self._ok_check(
            "discord_operations_ux",
            "Le socle Discord Pack 2 est actif: thread bindings, auto presence et exec approvals.",
        )

    def _doctor_plugins_allowlist(self, runtime_config: dict[str, Any] | None) -> dict[str, Any]:
        if runtime_config is None:
            return self._blocked_check("plugins_allowlist", "Impossible de verifier l'allowlist plugin sans snapshot runtime OpenClaw.")

        plugins = runtime_config.get("plugins")
        if not isinstance(plugins, dict):
            return self._blocked_check("plugins_allowlist", "La section plugins du runtime OpenClaw est absente.")

        allow = plugins.get("allow")
        if not isinstance(allow, list) or not [item for item in allow if str(item).strip()]:
            return self._blocked_check("plugins_allowlist", "L'allowlist plugin OpenClaw doit etre explicite et non vide.", allow)

        allow_ids = {str(item).strip() for item in allow if str(item).strip()}
        enabled_entries: list[str] = []
        entries = plugins.get("entries")
        if isinstance(entries, dict):
            for plugin_id, plugin_payload in entries.items():
                if isinstance(plugin_payload, dict) and plugin_payload.get("enabled") is True:
                    enabled_entries.append(str(plugin_id))

        missing = [plugin_id for plugin_id in enabled_entries if plugin_id not in allow_ids]
        if self.config.openclaw_config.plugin_id not in allow_ids:
            missing.append(self.config.openclaw_config.plugin_id)
        missing = sorted(set(missing))
        if missing:
            return self._blocked_check(
                "plugins_allowlist",
                "Tous les plugins actifs doivent etre explicitement allowlistes.",
                {"allow": sorted(allow_ids), "missing": missing},
            )
        return self._ok_check("plugins_allowlist", "L'allowlist plugin OpenClaw est explicite.", sorted(allow_ids))

    def _doctor_privacy_guard_policy(self) -> dict[str, Any]:
        issues: list[dict[str, Any]] = []
        if self.config.execution_policy.privacy_guard_enabled is not True:
            issues.append({"path": "execution_policy.privacy_guard_enabled", "value": self.config.execution_policy.privacy_guard_enabled})
        if self.config.execution_policy.s3_requires_local_model is not True:
            issues.append({"path": "execution_policy.s3_requires_local_model", "value": self.config.execution_policy.s3_requires_local_model})
        if issues:
            return self._blocked_check(
                "privacy_guard_policy",
                "La policy privacy guard Pack 4 n'est pas assez stricte.",
                issues,
            )
        return self._ok_check(
            "privacy_guard_policy",
            "La privacy guard Pack 4 est active avec blocage S3 sans fallback cloud.",
        )

    def _doctor_local_model_route(self) -> dict[str, Any]:
        if not self.config.execution_policy.local_model_enabled:
            return self._ok_check(
                "local_model_route",
                "La voie locale dediee est desactivee; S3 repose sur le blocage strict.",
            )
        if self.local_model_client is None:
            return self._blocked_check(
                "local_model_route",
                "La voie locale est activee mais aucun client local n'est branche.",
            )
        health = self.local_model_client.health(force=True)
        if health.get("status") != "ready":
            return self._blocked_check(
                "local_model_route",
                "La voie locale est activee mais pas encore prete.",
                health,
            )
        return self._ok_check(
            "local_model_route",
            "La voie locale Windows-first est prete pour le routage sensible.",
            health,
        )

    def _doctor_gateway_status(self, gateway_status: dict[str, Any]) -> dict[str, Any]:
        if not gateway_status.get("ok"):
            return self._blocked_check(
                "gateway_status",
                "Le statut gateway OpenClaw n'a pas pu etre lu.",
                gateway_status.get("stderr") or gateway_status.get("stdout"),
            )

        parsed = gateway_status.get("parsed")
        if not isinstance(parsed, dict):
            return self._blocked_check("gateway_status", "Le statut gateway OpenClaw doit etre parse en JSON.", gateway_status.get("stdout"))

        truth = self._gateway_truth_details(parsed)
        if not truth["healthy"]:
            return self._blocked_check(
                "gateway_status",
                "Le gateway OpenClaw n'est pas charge ou sa verite live reste insuffisante.",
                truth,
            )
        return self._ok_check("gateway_status", "Le statut gateway OpenClaw est sain.", truth)

    @staticmethod
    def _openclaw_config_is_valid(parsed: Any) -> bool:
        if not isinstance(parsed, dict):
            return False
        if "valid" in parsed:
            return bool(parsed.get("valid"))
        if "ok" in parsed:
            return bool(parsed.get("ok"))
        return False

    def _runtime_enabled_channels(self, runtime_config: dict[str, Any] | None) -> list[str]:
        if runtime_config is not None:
            plugins = runtime_config.get("plugins")
            entries = plugins.get("entries") if isinstance(plugins, dict) else None
            adapter = entries.get(self.config.openclaw_config.plugin_id) if isinstance(entries, dict) else None
            adapter_config = adapter.get("config") if isinstance(adapter, dict) else None
            enabled = adapter_config.get("enabledChannels") if isinstance(adapter_config, dict) else None
            if isinstance(enabled, list):
                return [str(item).strip().lower() for item in enabled if str(item).strip()]
        return [item.lower() for item in self.config.openclaw_config.enabled_channels]

    def _runtime_send_ack_replies(self, runtime_config: dict[str, Any] | None) -> bool:
        if runtime_config is not None:
            plugins = runtime_config.get("plugins")
            entries = plugins.get("entries") if isinstance(plugins, dict) else None
            adapter = entries.get(self.config.openclaw_config.plugin_id) if isinstance(entries, dict) else None
            adapter_config = adapter.get("config") if isinstance(adapter, dict) else None
            if isinstance(adapter_config, dict) and isinstance(adapter_config.get("sendAckReplies"), bool):
                return bool(adapter_config.get("sendAckReplies"))
        return bool(self.config.openclaw_config.send_ack_replies)

    @staticmethod
    def _secret_input_mode(value: Any, *, env_var_names: tuple[str, ...] = ()) -> str:
        if isinstance(value, dict) and any(key in value for key in ("source", "provider", "id", "path", "pointer", "env", "name", "command")):
            return "secretref"
        if isinstance(value, str) and value.strip():
            return "plaintext"
        if any(os.environ.get(name) for name in env_var_names):
            return "env"
        return "missing"

    def _truth_health_replay_check(self) -> dict[str, Any]:
        report = self._load_json_if_exists(self.paths.openclaw_replay_report_path)
        if report and report.get("verdict") == "OK":
            return self._ok_check(
                "replay_report",
                "Le replay OpenClaw est vert.",
                {
                    "report_id": report.get("report_id"),
                    "passed": report.get("passed"),
                    "failed": report.get("failed"),
                },
            )
        return self._warn_check(
            "replay_report",
            "Le replay OpenClaw n'est pas encore prouve comme vert.",
            report or {"reason": "missing_report"},
        )

    def _truth_health_startup_fallback_check(self) -> dict[str, Any]:
        if os.name != "nt":
            return self._ok_check("startup_fallback", "Controle du fallback Startup non applicable hors Windows.")
        startup_path = self._startup_fallback_path()
        if startup_path.exists():
            return self._warn_check(
                "startup_fallback",
                "Le fallback Startup existe encore. La tache planifiee n'est pas encore l'unique verite.",
                str(startup_path),
            )
        return self._ok_check("startup_fallback", "Le fallback Startup a disparu.", str(startup_path))

    def _truth_health_thread_binding_projection_check(
        self,
        *,
        normalized_channel: str,
        max_age_hours: int,
    ) -> dict[str, Any]:
        if normalized_channel != "discord":
            return self._ok_check("thread_binding_projection", "Controle des thread bindings reserve au canal Discord.")

        cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).isoformat()
        recent_events_row = self.database.fetchone(
            """
            SELECT COUNT(*) AS count
            FROM channel_events
            WHERE surface = ? AND created_at >= ?
            """,
            ("discord", cutoff),
        )
        recent_events = int(recent_events_row["count"] or 0) if recent_events_row else 0
        if recent_events == 0:
            return self._warn_check(
                "thread_binding_projection",
                "Aucun event Discord recent: projection thread binding non prouvable sur cette fenetre.",
                {"max_age_hours": max_age_hours},
            )

        recent_bindings_row = self.database.fetchone(
            """
            SELECT COUNT(*) AS count
            FROM discord_thread_bindings
            WHERE surface = ? AND updated_at >= ?
            """,
            ("discord", cutoff),
        )
        recent_bindings = int(recent_bindings_row["count"] or 0) if recent_bindings_row else 0
        if recent_bindings <= 0:
            return self._blocked_check(
                "thread_binding_projection",
                "Des events Discord recents existent, mais aucun binding thread durable n'a ete projete.",
                {"recent_events": recent_events, "recent_bindings": recent_bindings},
            )
        return self._ok_check(
            "thread_binding_projection",
            "La projection durable `discord thread -> mission/session` est visible dans le runtime.",
            {"recent_events": recent_events, "recent_bindings": recent_bindings},
        )

    def _refresh_discord_thread_binding_projection(self) -> int:
        rows = self.database.fetchall(
            """
            SELECT
                ce.event_id,
                ce.surface,
                ce.channel,
                ce.source_message_id,
                ce.thread_ref_json,
                ce.created_at,
                gdr.dispatch_id,
                gdr.envelope_id,
                gdr.decision_id,
                gdr.mission_run_id,
                gdr.reply_json
            FROM channel_events AS ce
            LEFT JOIN gateway_dispatch_results AS gdr
                ON gdr.channel_event_id = ce.event_id
            WHERE ce.surface = ?
            ORDER BY ce.created_at ASC
            """,
            ("discord",),
        )
        refreshed = 0
        for row in rows:
            thread_ref = self._json_loads_or_empty(row["thread_ref_json"])
            if not isinstance(thread_ref, dict):
                continue
            thread_id = str(thread_ref.get("thread_id") or "").strip()
            external_thread_id = str(thread_ref.get("external_thread_id") or "").strip() or None
            parent_thread_id = str(thread_ref.get("parent_thread_id") or "").strip() or None
            conversation_key = external_thread_id or thread_id
            if not thread_id or not conversation_key:
                continue

            binding_key = hashlib.sha256(
                f"discord|{str(row['channel'])}|{conversation_key}".encode("utf-8")
            ).hexdigest()
            existing = self.database.fetchone(
                "SELECT binding_id, created_at FROM discord_thread_bindings WHERE binding_key = ?",
                (binding_key,),
            )
            reply_payload = self._json_loads_or_empty(row["reply_json"])
            reply_kind = (
                str(reply_payload.get("reply_kind") or "").strip()
                if isinstance(reply_payload, dict)
                else ""
            )
            binding_kind = self._binding_kind_for_projection(
                channel=str(row["channel"] or ""),
                parent_thread_id=parent_thread_id,
                mission_run_id=row["mission_run_id"],
            )
            metadata = {
                "channel_class": self._channel_class_name_for_projection(
                    channel=str(row["channel"] or ""),
                    parent_thread_id=parent_thread_id,
                ),
                "reply_kind": reply_kind or None,
                "source_message_id": row["source_message_id"],
                "conversation_key": conversation_key,
                "projection_source": "truth_health_backfill",
            }
            self.database.upsert(
                "discord_thread_bindings",
                {
                    "binding_id": str(existing["binding_id"]) if existing else new_id("discord_binding"),
                    "binding_key": binding_key,
                    "surface": "discord",
                    "channel": str(row["channel"] or ""),
                    "thread_id": thread_id,
                    "external_thread_id": external_thread_id,
                    "parent_thread_id": parent_thread_id,
                    "channel_event_id": row["event_id"],
                    "dispatch_id": row["dispatch_id"],
                    "envelope_id": row["envelope_id"],
                    "decision_id": row["decision_id"],
                    "mission_run_id": row["mission_run_id"],
                    "binding_kind": binding_kind,
                    "status": "blocked" if reply_kind == "blocked" else "active",
                    "metadata_json": json.dumps(metadata, ensure_ascii=True, sort_keys=True),
                    "created_at": str(existing["created_at"]) if existing else str(row["created_at"]),
                    "updated_at": str(row["created_at"]),
                },
                conflict_columns="binding_key",
                immutable_columns=["binding_id", "created_at"],
            )
            refreshed += 1
        return refreshed

    @staticmethod
    def _binding_kind_for_projection(
        *,
        channel: str,
        parent_thread_id: str | None,
        mission_run_id: Any,
    ) -> str:
        lowered = channel.strip().lower().lstrip("#")
        if lowered == "incidents":
            return "incident"
        if lowered == "approvals":
            return "approval"
        if mission_run_id:
            return "run"
        if parent_thread_id:
            return "run"
        return "discussion"

    @staticmethod
    def _channel_class_name_for_projection(*, channel: str, parent_thread_id: str | None) -> str:
        lowered = channel.strip().lower().lstrip("#")
        if parent_thread_id:
            return "mission_thread"
        if lowered == "pilotage":
            return "pilotage"
        if lowered == "runs-live":
            return "runs_live"
        if lowered == "approvals":
            return "approvals"
        if lowered == "incidents":
            return "incidents"
        return "unknown"

    def _trust_audit_plugin_catalog(self, runtime_config: dict[str, Any] | None) -> dict[str, Any]:
        plugin_list = self._run_openclaw_command(["plugins", "list", "--json"], timeout_ms=self.config.openclaw_config.timeout_ms)
        parsed = plugin_list.get("parsed")
        if not isinstance(parsed, dict):
            parsed = self._json_loads_or_empty(plugin_list.get("stdout"))
        plugins = parsed.get("plugins") if isinstance(parsed, dict) else None
        if not plugin_list.get("ok") or not isinstance(plugins, list):
            return self._blocked_check(
                "plugin_catalog",
                "Le catalogue plugin OpenClaw n'a pas pu etre lu proprement.",
                plugin_list.get("stderr") or plugin_list.get("stdout"),
            )

        trusted_ids = {item.strip() for item in self.config.openclaw_config.trusted_plugin_ids if item.strip()}
        runtime_plugins = runtime_config.get("plugins") if isinstance(runtime_config, dict) else {}
        allow_ids = {
            str(item).strip()
            for item in (runtime_plugins.get("allow") if isinstance(runtime_plugins, dict) else []) or []
            if str(item).strip()
        }
        entries = runtime_plugins.get("entries") if isinstance(runtime_plugins, dict) and isinstance(runtime_plugins.get("entries"), dict) else {}
        installs = runtime_plugins.get("installs") if isinstance(runtime_plugins, dict) and isinstance(runtime_plugins.get("installs"), dict) else {}
        active_plugins: list[dict[str, Any]] = []
        issues: list[dict[str, Any]] = []

        for plugin in plugins:
            if not isinstance(plugin, dict):
                continue
            plugin_id = str(plugin.get("id") or "").strip()
            if not plugin_id:
                continue
            enabled = plugin.get("enabled") is True
            status = str(plugin.get("status") or "").strip().lower()
            if not enabled and status != "loaded":
                continue
            origin = str(plugin.get("origin") or "").strip().lower() or None
            source = str(plugin.get("source") or "").strip() or None
            version = str(plugin.get("version") or "").strip() or None
            active_plugins.append(
                {
                    "id": plugin_id,
                    "origin": origin,
                    "status": status or None,
                    "source": source,
                    "version": version,
                }
            )
            if plugin_id not in trusted_ids:
                issues.append({"plugin_id": plugin_id, "reason": "not_trusted"})
                continue
            if plugin_id not in allow_ids:
                issues.append({"plugin_id": plugin_id, "reason": "not_allowlisted"})
            if plugin_id == self.config.openclaw_config.plugin_id:
                expected_source = str((self.plugin_source_path / "index.js").resolve(strict=False))
                if origin != "config":
                    issues.append({"plugin_id": plugin_id, "reason": "unexpected_origin", "origin": origin})
                if source and str(Path(source).resolve(strict=False)) != expected_source:
                    issues.append({"plugin_id": plugin_id, "reason": "unexpected_source", "source": source})
            elif plugin_id not in installs and origin != "bundled":
                issues.append({"plugin_id": plugin_id, "reason": "expected_bundled_origin", "origin": origin})

        extra_allow_ids = sorted(item for item in allow_ids if item not in trusted_ids)
        if extra_allow_ids:
            issues.append({"reason": "allowlist_outside_policy", "plugin_ids": extra_allow_ids})

        if issues:
            return self._blocked_check(
                "plugin_catalog",
                "Les plugins actifs ou allowlistes sortent du catalogue de confiance retenu.",
                {
                    "trusted_plugin_ids": sorted(trusted_ids),
                    "active_plugins": active_plugins,
                    "issues": issues,
                },
            )
        return self._ok_check(
            "plugin_catalog",
            "Le catalogue plugin actif reste borne aux ids et origines attendus.",
            {
                "trusted_plugin_ids": sorted(trusted_ids),
                "active_plugins": active_plugins,
            },
        )

    def _trust_audit_plugin_install_policy(self, runtime_config: dict[str, Any] | None) -> dict[str, Any]:
        plugins = runtime_config.get("plugins") if isinstance(runtime_config, dict) else {}
        load = plugins.get("load") if isinstance(plugins, dict) else {}
        installs = plugins.get("installs") if isinstance(plugins, dict) and isinstance(plugins.get("installs"), dict) else {}
        load_paths = load.get("paths") if isinstance(load, dict) else None
        expected_load_path = str(self.plugin_source_path.resolve(strict=False))
        issues: list[dict[str, Any]] = []

        normalized_load_paths = []
        if isinstance(load_paths, list):
            for item in load_paths:
                candidate = str(item).strip()
                if not candidate:
                    continue
                normalized_load_paths.append(str(Path(candidate).resolve(strict=False)))
        if expected_load_path not in normalized_load_paths:
            issues.append({"reason": "project_plugin_load_path_missing", "paths": normalized_load_paths, "expected": expected_load_path})
        if any(path != expected_load_path for path in normalized_load_paths):
            issues.append({"reason": "unexpected_load_path", "paths": normalized_load_paths, "expected": expected_load_path})

        expected_version = self._local_plugin_version()
        install_payload = installs.get(self.config.openclaw_config.plugin_id) if isinstance(installs, dict) else None
        if not isinstance(install_payload, dict):
            issues.append({"reason": "project_plugin_install_record_missing"})
        else:
            source_kind = str(install_payload.get("source") or "").strip().lower()
            source_path = str(install_payload.get("sourcePath") or "").strip()
            install_path = str(install_payload.get("installPath") or "").strip()
            version = str(install_payload.get("version") or "").strip()
            if source_kind != "path":
                issues.append({"plugin_id": self.config.openclaw_config.plugin_id, "reason": "project_plugin_not_path_install", "source": source_kind})
            if source_path and str(Path(source_path).resolve(strict=False)) != expected_load_path:
                issues.append({"plugin_id": self.config.openclaw_config.plugin_id, "reason": "project_plugin_source_path_mismatch", "sourcePath": source_path})
            if install_path and str(Path(install_path).resolve(strict=False)) != expected_load_path:
                issues.append({"plugin_id": self.config.openclaw_config.plugin_id, "reason": "project_plugin_install_path_mismatch", "installPath": install_path})
            if expected_version and version and version != expected_version:
                issues.append({"plugin_id": self.config.openclaw_config.plugin_id, "reason": "project_plugin_version_mismatch", "version": version, "expected": expected_version})

        trusted_ids = {item.strip() for item in self.config.openclaw_config.trusted_plugin_ids if item.strip()}
        install_summary: list[dict[str, Any]] = []
        if isinstance(installs, dict):
            for plugin_id, payload in installs.items():
                if not isinstance(payload, dict):
                    continue
                source_kind = str(payload.get("source") or "").strip().lower()
                version = str(payload.get("version") or "").strip() or None
                install_summary.append({"plugin_id": str(plugin_id), "source": source_kind or None, "version": version})
                if str(plugin_id) not in trusted_ids:
                    issues.append({"plugin_id": str(plugin_id), "reason": "install_record_outside_policy"})
                if source_kind not in {"path", "npm"}:
                    issues.append({"plugin_id": str(plugin_id), "reason": "unsupported_install_source", "source": source_kind})
                if source_kind == "npm" and version and not self._is_exact_version(version):
                    issues.append({"plugin_id": str(plugin_id), "reason": "npm_version_not_pinned", "version": version})

        if issues:
            return self._blocked_check(
                "plugin_install_policy",
                "La provenance d'installation plugin n'est pas assez borne.",
                {
                    "load_paths": normalized_load_paths,
                    "installs": install_summary,
                    "issues": issues,
                },
            )
        return self._ok_check(
            "plugin_install_policy",
            "La provenance d'installation plugin reste explicite et reproductible.",
            {
                "load_paths": normalized_load_paths,
                "installs": install_summary,
                "project_plugin_expected_version": expected_version,
            },
        )

    def _trust_audit_pairing_store(self) -> tuple[dict[str, Any], dict[str, Any]]:
        devices_root = self.paths.openclaw_state_root / "devices"
        identity_root = self.paths.openclaw_state_root / "identity"
        paired_path = devices_root / "paired.json"
        pending_path = devices_root / "pending.json"
        auth_path = identity_root / "device-auth.json"
        paired_payload = self._load_json_payload(paired_path)
        pending_payload = self._load_json_payload(pending_path)
        auth_payload = self._load_json_payload(auth_path)
        issues: list[dict[str, Any]] = []
        device_tokens: list[dict[str, Any]] = []

        if not isinstance(paired_payload, dict):
            issues.append({"reason": "paired_store_invalid", "path": str(paired_path)})
            paired_payload = {}
        if pending_payload is None:
            pending_payload = {}
        pending_count = len(pending_payload) if isinstance(pending_payload, (dict, list)) else 0
        if pending_payload is not None and not isinstance(pending_payload, (dict, list)):
            issues.append({"reason": "pending_store_invalid", "path": str(pending_path)})
        if auth_payload is not None and not isinstance(auth_payload, dict):
            issues.append({"reason": "device_auth_invalid", "path": str(auth_path)})
            auth_payload = {}

        for device_id, device_payload in paired_payload.items():
            if not isinstance(device_payload, dict):
                issues.append({"reason": "paired_device_invalid", "device_id": str(device_id)})
                continue
            approved_scopes = {
                str(item).strip()
                for item in device_payload.get("approvedScopes", []) or []
                if str(item).strip()
            }
            fallback_scopes = {
                str(item).strip()
                for item in device_payload.get("scopes", []) or []
                if str(item).strip()
            }
            approved_baseline = approved_scopes or fallback_scopes
            token_entries = device_payload.get("tokens")
            if not isinstance(token_entries, dict):
                continue
            for role_name, token_payload in token_entries.items():
                if not isinstance(token_payload, dict):
                    continue
                scopes = {
                    str(item).strip()
                    for item in token_payload.get("scopes", []) or []
                    if str(item).strip()
                }
                if approved_baseline and not scopes.issubset(approved_baseline):
                    issues.append(
                        {
                            "reason": "token_scope_exceeds_approved_baseline",
                            "device_id": str(device_id),
                            "role": str(role_name),
                            "scopes": sorted(scopes),
                            "approved_baseline": sorted(approved_baseline),
                        }
                    )
                device_tokens.append(
                    {
                        "device_id": str(device_id),
                        "role": str(role_name),
                        "token": str(token_payload.get("token") or ""),
                        "scopes": sorted(scopes),
                        "created_at_ms": token_payload.get("createdAtMs"),
                        "updated_at_ms": token_payload.get("updatedAtMs"),
                    }
                )

        auth_device_id = str(auth_payload.get("deviceId") or "").strip() if isinstance(auth_payload, dict) else ""
        auth_tokens = auth_payload.get("tokens") if isinstance(auth_payload, dict) else None
        if auth_device_id and auth_device_id not in paired_payload:
            issues.append({"reason": "device_auth_device_missing_from_paired_store", "device_id": auth_device_id})
        if isinstance(auth_tokens, dict):
            paired_tokens = paired_payload.get(auth_device_id, {}).get("tokens", {}) if auth_device_id else {}
            for role_name, token_payload in auth_tokens.items():
                if not isinstance(token_payload, dict):
                    continue
                token_value = str(token_payload.get("token") or "")
                paired_role_payload = paired_tokens.get(role_name) if isinstance(paired_tokens, dict) else None
                paired_token_value = str(paired_role_payload.get("token") or "") if isinstance(paired_role_payload, dict) else ""
                if paired_token_value and token_value and token_value != paired_token_value:
                    issues.append(
                        {
                            "reason": "device_auth_token_mismatch",
                            "device_id": auth_device_id,
                            "role": str(role_name),
                        }
                    )

        details = {
            "paired_device_count": len(paired_payload),
            "pending_request_count": pending_count,
            "sensitive_paths": [str(paired_path), str(auth_path)],
            "identity_device_id": auth_device_id or None,
        }
        state = {
            "paired_payload": paired_payload,
            "pending_payload": pending_payload,
            "auth_payload": auth_payload or {},
            "device_tokens": device_tokens,
            "allowed_secret_paths": {str(paired_path.resolve(strict=False)), str(auth_path.resolve(strict=False))},
        }
        if issues:
            return (
                self._blocked_check(
                    "pairing_store",
                    "Le store local de pairing n'est pas coherent ou depasse sa baseline de scopes.",
                    {**details, "issues": issues},
                ),
                state,
            )
        if pending_count > 0:
            return (
                self._warn_check(
                    "pairing_store",
                    "Des pairings restent en attente dans le store local.",
                    details,
                ),
                state,
            )
        return (
            self._ok_check(
                "pairing_store",
                "Le store local de pairing reste coherent et borne.",
                details,
            ),
            state,
        )

    def _trust_audit_pairing_token_rotation(self, pairing_state: dict[str, Any]) -> dict[str, Any]:
        max_age_days = max(1, int(self.config.openclaw_config.pairing_rotation_max_age_days))
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        stale_tokens: list[dict[str, Any]] = []
        total_tokens = 0
        for token_entry in pairing_state.get("device_tokens", []):
            if not isinstance(token_entry, dict):
                continue
            total_tokens += 1
            timestamp_ms = token_entry.get("updated_at_ms") or token_entry.get("created_at_ms")
            if not isinstance(timestamp_ms, (int, float)):
                continue
            created_at = datetime.fromtimestamp(float(timestamp_ms) / 1000.0, tz=timezone.utc)
            if created_at < cutoff:
                stale_tokens.append(
                    {
                        "device_id": token_entry.get("device_id"),
                        "role": token_entry.get("role"),
                        "age_days": round((datetime.now(timezone.utc) - created_at).total_seconds() / 86400, 1),
                    }
                )
        details = {"max_age_days": max_age_days, "total_tokens": total_tokens, "stale_tokens": stale_tokens}
        if stale_tokens:
            return self._warn_check(
                "pairing_rotation",
                "Des tokens device depassent la fenetre de rotation retenue.",
                details,
            )
        return self._ok_check(
            "pairing_rotation",
            "Les tokens device restent dans la fenetre de rotation retenue.",
            details,
        )

    def _trust_audit_pairing_secret_exposure(self, pairing_state: dict[str, Any]) -> dict[str, Any]:
        allowed_secret_paths = {str(Path(path).resolve(strict=False)) for path in pairing_state.get("allowed_secret_paths", set())}
        secret_targets: list[tuple[str, str]] = []
        for env_name, label in (("OPENCLAW_GATEWAY_TOKEN", "gateway_shared_token"), ("DISCORD_BOT_TOKEN", "discord_bot_token")):
            value = self._lookup_process_or_windows_env(env_name)
            if value:
                secret_targets.append((label, value))
        for token_entry in pairing_state.get("device_tokens", []):
            if not isinstance(token_entry, dict):
                continue
            value = str(token_entry.get("token") or "")
            if value:
                secret_targets.append((f"device_token:{token_entry.get('device_id')}:{token_entry.get('role')}", value))

        findings: list[dict[str, Any]] = []
        scanned_file_count = 0
        for path in self._pairing_leak_scan_paths():
            try:
                resolved = str(path.resolve(strict=False))
            except OSError:
                resolved = str(path)
            if resolved in allowed_secret_paths:
                continue
            text = self._read_text_for_scan(path)
            if not text:
                continue
            scanned_file_count += 1
            lowered = text.lower()
            if "bootstraptoken" in lowered:
                findings.append({"path": resolved, "kind": "bootstrap_token_marker"})
            for label, value in secret_targets:
                if value and value in text:
                    findings.append({"path": resolved, "kind": label})

        if findings:
            return self._blocked_check(
                "pairing_secret_exposure",
                "Des secrets plugin/pairing ont fuite hors des emplacements sensibles attendus.",
                {"scanned_file_count": scanned_file_count, "findings": findings},
            )
        return self._ok_check(
            "pairing_secret_exposure",
            "Aucune fuite de secret plugin/pairing n'a ete trouvee dans les surfaces visibles scannees.",
            {
                "scanned_file_count": scanned_file_count,
                "checked_secret_kinds": [label for label, _ in secret_targets],
            },
        )

    def _truth_health_live_proof_check(
        self,
        *,
        normalized_channel: str,
        max_age_hours: int,
    ) -> tuple[dict[str, Any], list[str], str | None]:
        evidence = self._latest_live_bridge_evidence(normalized_channel=normalized_channel, max_age_hours=max_age_hours)
        if evidence is None:
            return (
                self._warn_check(
                    "live_bridge_proof",
                    "Aucune preuve recente n'etablit encore un message OpenClaw reel jusqu'au Mission Router.",
                    {"channel": normalized_channel, "max_age_hours": max_age_hours},
                ),
                [],
                f"Envoie un vrai message {normalized_channel} puis relance `project-os openclaw validate-live --channel {normalized_channel}`.",
            )
        evidence_refs = [
            str(evidence.get("event_id")),
            str(evidence.get("dispatch_id")),
        ]
        if evidence.get("decision_id"):
            evidence_refs.append(str(evidence.get("decision_id")))
        if evidence.get("mission_run_id"):
            evidence_refs.append(str(evidence.get("mission_run_id")))
        return (
            self._ok_check("live_bridge_proof", "Une preuve live recente OpenClaw -> Mission Router est presente.", evidence),
            [item for item in evidence_refs if item],
            None,
        )

    def _latest_live_bridge_evidence(self, *, normalized_channel: str, max_age_hours: int) -> dict[str, Any] | None:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).isoformat()
        rows = self.database.fetchall(
            """
            SELECT
                ce.event_id,
                ce.surface,
                ce.channel,
                ce.source_message_id,
                ce.conversation_key,
                ce.thread_ref_json,
                ce.message_json,
                ce.raw_payload_json,
                ce.created_at,
                gdr.dispatch_id,
                gdr.decision_id,
                gdr.mission_run_id,
                gdr.reply_json,
                gdr.metadata_json
            FROM channel_events AS ce
            JOIN gateway_dispatch_results AS gdr
              ON gdr.channel_event_id = ce.event_id
            WHERE ce.created_at >= ?
            ORDER BY ce.created_at DESC
            LIMIT 64
            """,
            (cutoff,),
        )
        for row in rows:
            raw_payload = self._json_loads_or_empty(row["raw_payload_json"])
            message_payload = self._json_loads_or_empty(row["message_json"])
            dispatch_metadata = self._json_loads_or_empty(row["metadata_json"])
            if str(raw_payload.get("source") or message_payload.get("metadata", {}).get("source") or "").strip().lower() != "openclaw":
                continue
            if not self._live_evidence_matches_channel(
                normalized_channel=normalized_channel,
                row=row,
                raw_payload=raw_payload,
                message_payload=message_payload,
            ):
                continue
            if not row["decision_id"] and not row["mission_run_id"] and not dispatch_metadata.get("routing_trace_id"):
                continue
            reply_payload = self._json_loads_or_empty(row["reply_json"])
            thread_payload = self._json_loads_or_empty(row["thread_ref_json"])
            return {
                "event_id": row["event_id"],
                "dispatch_id": row["dispatch_id"],
                "decision_id": row["decision_id"],
                "mission_run_id": row["mission_run_id"],
                "surface": row["surface"],
                "channel": row["channel"],
                "source_message_id": row["source_message_id"],
                "conversation_key": row["conversation_key"],
                "reply_kind": reply_payload.get("reply_kind"),
                "summary": reply_payload.get("summary"),
                "thread_id": thread_payload.get("thread_id"),
                "created_at": row["created_at"],
            }
        return None

    def _live_evidence_matches_channel(
        self,
        *,
        normalized_channel: str,
        row: Any,
        raw_payload: dict[str, Any],
        message_payload: dict[str, Any],
    ) -> bool:
        context = raw_payload.get("context")
        metadata = message_payload.get("metadata") if isinstance(message_payload.get("metadata"), dict) else {}
        candidates = {
            str(row["surface"] or "").strip().lower(),
            str(row["channel"] or "").strip().lower(),
            str(raw_payload.get("surface") or "").strip().lower(),
            str(metadata.get("surface") or "").strip().lower(),
            str(metadata.get("originating_channel") or "").strip().lower(),
            str(metadata.get("channel_name") or "").strip().lower(),
        }
        if isinstance(context, dict):
            candidates.add(str(context.get("channelId") or "").strip().lower())
        candidates.discard("")
        return normalized_channel in candidates

    def _gateway_status_command(self, runtime_config: dict[str, Any] | None) -> dict[str, Any]:
        token_value = self._gateway_status_token(runtime_config)
        if token_value:
            result = self._run_openclaw_command(
                ["gateway", "status", "--json", "--token", token_value],
                timeout_ms=self.config.openclaw_config.timeout_ms,
            )
            if result.get("ok") and isinstance(result.get("parsed"), dict):
                return result
        return self._run_openclaw_command(
            ["gateway", "status", "--json", "--no-probe"],
            timeout_ms=self.config.openclaw_config.timeout_ms,
        )

    def _gateway_status_token(self, runtime_config: dict[str, Any] | None) -> str | None:
        gateway = runtime_config.get("gateway") if isinstance(runtime_config, dict) else None
        auth = gateway.get("auth") if isinstance(gateway, dict) else None
        token = auth.get("token") if isinstance(auth, dict) else None
        if isinstance(token, dict):
            for key in ("id", "env", "name"):
                candidate = str(token.get(key) or "").strip()
                if candidate:
                    resolved = self._lookup_process_or_windows_env(candidate)
                    if resolved:
                        return resolved
        return self._lookup_process_or_windows_env("OPENCLAW_GATEWAY_TOKEN")

    def _gateway_truth_details(self, parsed: dict[str, Any]) -> dict[str, Any]:
        service = parsed.get("service") if isinstance(parsed.get("service"), dict) else {}
        top_runtime = parsed.get("runtime") if isinstance(parsed.get("runtime"), dict) else {}
        service_runtime = service.get("runtime") if isinstance(service.get("runtime"), dict) else {}
        runtime_status = str(service_runtime.get("status") or top_runtime.get("status") or "").strip().lower()
        port = parsed.get("port") if isinstance(parsed.get("port"), dict) else {}
        port_status = str(port.get("status") or "").strip().lower()
        listeners = port.get("listeners") if isinstance(port.get("listeners"), list) else []
        has_live_listener = port_status == "busy" and len(listeners) > 0
        rpc = parsed.get("rpc") if isinstance(parsed.get("rpc"), dict) else {}
        rpc_ok = rpc.get("ok") is True
        loaded = service.get("loaded") is True
        runtime_missing = runtime_status in {"missing", "error", "failed"}
        unknown_runtime_accepted = os.name == "nt" and runtime_status in {"", "unknown"} and (has_live_listener or rpc_ok)
        healthy = loaded and not runtime_missing and (has_live_listener or rpc_ok or runtime_status == "running")
        if runtime_status in {"", "unknown"} and not unknown_runtime_accepted:
            healthy = False
        return {
            "loaded": loaded,
            "runtime_status": runtime_status or None,
            "port_status": port_status or None,
            "listener_count": len(listeners),
            "has_live_listener": has_live_listener,
            "rpc_ok": rpc_ok,
            "unknown_runtime_accepted": unknown_runtime_accepted,
            "healthy": healthy,
            "raw": parsed,
        }

    def _gateway_truth_details_from_command(self, result: dict[str, Any]) -> dict[str, Any]:
        parsed = result.get("parsed")
        if isinstance(parsed, dict):
            details = self._gateway_truth_details(parsed)
            details["command_ok"] = bool(result.get("ok"))
            return details
        return {
            "loaded": False,
            "runtime_status": None,
            "port_status": None,
            "listener_count": 0,
            "has_live_listener": False,
            "rpc_ok": False,
            "unknown_runtime_accepted": False,
            "healthy": False,
            "command_ok": bool(result.get("ok")),
            "raw": {
                "stdout": result.get("stdout"),
                "stderr": result.get("stderr"),
                "returncode": result.get("returncode"),
            },
        }

    def _command_check(self, name: str, message: str, result: dict[str, Any]) -> dict[str, Any]:
        details = {
            "ok": bool(result.get("ok")),
            "returncode": result.get("returncode"),
            "stdout": result.get("stdout"),
            "stderr": result.get("stderr"),
        }
        if result.get("ok"):
            return self._ok_check(name, message, details)
        return self._warn_check(name, f"{message} La commande a retourne une erreur.", details)

    def _status_check(self, name: str, details: dict[str, Any], ok_message: str, warn_message: str) -> dict[str, Any]:
        if details.get("healthy"):
            return self._ok_check(name, ok_message, details)
        return self._warn_check(name, warn_message, details)

    def _self_heal_cooldown_state(self, *, ignore_cooldown: bool) -> dict[str, Any]:
        cooldown_seconds = max(0, int(self.config.openclaw_config.self_heal_cooldown_seconds))
        if ignore_cooldown or cooldown_seconds <= 0:
            return {"active": False, "cooldown_seconds": cooldown_seconds}
        previous = self._load_json_if_exists(self.paths.openclaw_self_heal_report_path)
        if not previous:
            return {"active": False, "cooldown_seconds": cooldown_seconds}
        previous_status = str(previous.get("status") or "").strip().lower()
        if previous_status not in {"restarted", "started", "failed"}:
            return {"active": False, "cooldown_seconds": cooldown_seconds}
        last_attempt_at = str(previous.get("metadata", {}).get("last_repair_attempt_at") or previous.get("created_at") or "").strip()
        last_dt = self._parse_iso_datetime(last_attempt_at)
        if last_dt is None:
            return {"active": False, "cooldown_seconds": cooldown_seconds}
        elapsed_seconds = max(0, int((datetime.now(timezone.utc) - last_dt).total_seconds()))
        active = elapsed_seconds < cooldown_seconds
        return {
            "active": active,
            "cooldown_seconds": cooldown_seconds,
            "elapsed_seconds": elapsed_seconds,
            "remaining_seconds": max(0, cooldown_seconds - elapsed_seconds),
            "previous_status": previous_status,
            "last_repair_attempt_at": last_dt.isoformat(),
        }

    def _startup_fallback_path(self) -> Path:
        startup_root = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        return startup_root / f"{self.config.openclaw_config.windows_gateway_task_name}.cmd"

    def _local_plugin_version(self) -> str | None:
        package_path = self.plugin_source_path / "package.json"
        payload = self._load_json_payload(package_path)
        version = payload.get("version") if isinstance(payload, dict) else None
        if isinstance(version, str) and version.strip():
            return version.strip()
        return None

    def _pairing_leak_scan_paths(self) -> list[Path]:
        scan_paths: list[Path] = []
        include_roots = [
            self.paths.openclaw_state_root / "agents",
            self.paths.openclaw_state_root / "logs",
            self.paths.openclaw_state_root,
        ]
        allowed_suffixes = {".json", ".jsonl", ".log", ".txt", ".md"}
        excluded_roots = {
            str((self.paths.openclaw_state_root / "devices").resolve(strict=False)),
            str((self.paths.openclaw_state_root / "identity").resolve(strict=False)),
            str((self.paths.openclaw_state_root / "memory").resolve(strict=False)),
        }
        seen: set[str] = set()
        for root in include_roots:
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                resolved = str(path.resolve(strict=False))
                if any(resolved.startswith(prefix) for prefix in excluded_roots):
                    continue
                if path.suffix.lower() not in allowed_suffixes:
                    continue
                if resolved in seen:
                    continue
                seen.add(resolved)
                scan_paths.append(path)
        for extra in (self.paths.journal_file_path,):
            if extra.exists():
                resolved = str(extra.resolve(strict=False))
                if resolved not in seen:
                    seen.add(resolved)
                    scan_paths.append(extra)
        return scan_paths

    @staticmethod
    def _read_text_for_scan(path: Path, *, max_bytes: int = 2_000_000) -> str:
        try:
            if path.stat().st_size > max_bytes:
                return ""
            return path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return ""

    @staticmethod
    def _is_exact_version(version: str) -> bool:
        normalized = version.strip()
        if not normalized:
            return False
        if any(marker in normalized for marker in ("^", "~", ">", "<", "*", " ", "||")):
            return False
        parts = normalized.split("@")
        candidate = parts[-1] if len(parts) > 1 else normalized
        return candidate[0].isdigit()

    @staticmethod
    def _lookup_process_or_windows_env(name: str) -> str | None:
        direct_value = os.environ.get(name)
        if direct_value:
            return direct_value
        if winreg is None:
            return None
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment")
            try:
                value, _ = winreg.QueryValueEx(key, name)
            finally:
                winreg.CloseKey(key)
            if value:
                return str(value)
        except FileNotFoundError:
            pass
        except OSError:
            pass
        return None

    @staticmethod
    def _json_loads_or_empty(raw: Any) -> dict[str, Any]:
        if isinstance(raw, dict):
            return raw
        if not isinstance(raw, str) or not raw.strip():
            return {}
        payload = OpenClawLiveService._parse_json_output(raw)
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _load_json_payload(path: Path) -> Any | None:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, OSError):
            return None

    @staticmethod
    def _parse_json_output(raw: str) -> Any | None:
        stripped = raw.strip()
        if not stripped:
            return None
        try:
            return json.loads(stripped)
        except Exception:
            pass
        for marker in ("{", "["):
            index = stripped.find(marker)
            if index == -1:
                continue
            try:
                return json.loads(stripped[index:])
            except Exception:
                continue
        return None

    @staticmethod
    def _parse_iso_datetime(value: str) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

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
            parsed = self._parse_json_output(stdout)
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
        return json.loads(path.read_text(encoding="utf-8-sig"))
