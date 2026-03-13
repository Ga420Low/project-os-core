from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import SecretConfig

try:
    import winreg  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover - not reached on Windows
    winreg = None  # type: ignore[assignment]


@dataclass(slots=True)
class SecretLookup:
    value: str | None
    source: str
    available: bool


class SecretResolver:
    def __init__(self, config: SecretConfig, repo_root: Path | None = None):
        self.config = config
        self.repo_root = repo_root
        self.local_fallback_path = Path(config.local_fallback_path)
        self._infisical_cache: dict[str, str] | None = None
        self._infisical_access_token_cache: str | None = None
        self._infisical_access_token_source: str | None = None

    def get_required(self, name: str, *, allow_infisical: bool = True) -> str:
        lookup = self.lookup(name, allow_infisical=allow_infisical)
        if not lookup.available or not lookup.value:
            raise RuntimeError(f"Required secret is missing: {name}")
        return lookup.value

    def get_optional(self, name: str, *, allow_infisical: bool = True) -> str | None:
        lookup = self.lookup(name, allow_infisical=allow_infisical)
        return lookup.value if lookup.available else None

    def lookup(self, name: str, *, allow_infisical: bool = True) -> SecretLookup:
        infisical = self._from_infisical(name) if allow_infisical else SecretLookup(value=None, source="infisical_skipped", available=False)
        if infisical.available:
            return infisical

        env_value = os.getenv(name)
        if env_value:
            return SecretLookup(value=env_value, source="process_env", available=True)

        user_value = self._from_windows_user_env(name)
        if user_value.available:
            return user_value

        local_value = self._from_local_file(name)
        if local_value.available:
            return local_value

        return SecretLookup(value=None, source="missing", available=False)

    def source_report(self) -> dict[str, Any]:
        infisical_ready = self.infisical_resolution_ready()
        auth_mode = self._infisical_auth_mode()
        token_source = self._resolved_infisical_access_token_source()
        effective_project_id = self._effective_infisical_project_id()
        client_id_lookup = self._lookup_process_or_windows_env(self.config.infisical_universal_auth_client_id_env)
        client_secret_lookup = self._lookup_process_or_windows_env(self.config.infisical_universal_auth_client_secret_env)
        return {
            "mode": self.config.mode,
            "local_fallback_path": str(self.local_fallback_path),
            "infisical": {
                "binary_present": bool(self._infisical_binary()),
                "binary_path": self._infisical_binary(),
                "project_id_configured": bool(self.config.infisical_project_id),
                "effective_project_id_present": bool(effective_project_id),
                "environment_configured": bool(self.config.infisical_environment),
                "path": self.config.infisical_path,
                "token_env": self.config.infisical_token_env,
                "token_present": self._lookup_process_or_windows_env(self.config.infisical_token_env).available,
                "project_link_present": self._infisical_project_link_present(),
                "universal_auth_client_id_env": self.config.infisical_universal_auth_client_id_env,
                "universal_auth_client_id_present": client_id_lookup.available,
                "universal_auth_client_secret_env": self.config.infisical_universal_auth_client_secret_env,
                "universal_auth_client_secret_present": client_secret_lookup.available,
                "machine_auth_ready": self._machine_auth_ready(),
                "auth_mode": auth_mode,
                "active_token_source": token_source,
                "user_session_fallback_allowed": self.config.mode != "infisical_required",
                "resolution_ready": infisical_ready,
            },
            "required": {
                name: {
                    "available": self.lookup(name).available,
                    "source": self.lookup(name).source,
                    "masked_value": self.mask(self.lookup(name).value),
                }
                for name in self.config.required_secret_names
            },
        }

    def ensure_local_fallback(self) -> Path:
        self.local_fallback_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.local_fallback_path.exists():
            self.local_fallback_path.write_text("{}", encoding="utf-8")
        return self.local_fallback_path

    def write_local_fallback(self, name: str, value: str) -> Path:
        path = self.ensure_local_fallback()
        payload = self._read_local_json()
        payload[name] = value
        path.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
        return path

    def push_to_infisical(self, name: str) -> dict[str, Any]:
        executable = self._infisical_binary()
        if not executable:
            raise RuntimeError("Infisical CLI is not installed")
        if not self.config.infisical_environment:
            raise RuntimeError("Infisical environment is not configured")
        if not self.config.infisical_project_id and not os.getenv(self.config.infisical_token_env) and not self._infisical_project_link_present():
            raise RuntimeError("Infisical project ID, token, or linked project is required to push secrets")

        value = self.get_required(name, allow_infisical=False)
        command = [
            executable,
            "secrets",
            "set",
            f"{name}={value}",
            "--env",
            self.config.infisical_environment,
            "--path",
            self.config.infisical_path,
            "--silent",
            "--output",
            "json",
        ]
        token = self._resolved_infisical_access_token()
        if token and self._effective_infisical_project_id():
            command.extend(["--projectId", self._effective_infisical_project_id()])
        elif self.config.infisical_project_id:
            command.extend(["--projectId", self.config.infisical_project_id])
        if token:
            command.extend(["--token", token])
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            timeout=20,
        )
        return {
            "status": "pushed",
            "name": name,
            "cli_acknowledged": bool(completed.stdout.strip()),
            "environment": self.config.infisical_environment,
            "project_id": self.config.infisical_project_id,
            "path": self.config.infisical_path,
        }

    def infisical_resolution_ready(self) -> bool:
        if not self._infisical_binary() or not self.config.infisical_environment:
            return False
        has_project_target = bool(self._effective_infisical_project_id())
        if not has_project_target:
            return False
        auth_mode = self._infisical_auth_mode()
        if self.config.mode == "infisical_required":
            if auth_mode == "token_env":
                return True
            if auth_mode == "universal_auth":
                return bool(self._resolved_infisical_access_token())
            return False
        return auth_mode in {"token_env", "universal_auth", "user_session_fallback"}

    def migrate_repo_dotenv(self) -> dict[str, Any]:
        if not self.repo_root:
            return {"migrated": False, "reason": "repo_root_unavailable"}

        dotenv_path = self.repo_root / ".env"
        if not dotenv_path.exists():
            return {"migrated": False, "reason": "repo_env_missing"}

        migrated: list[str] = []
        for line in dotenv_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if not key or not value:
                continue
            existing = self.lookup(key)
            if not existing.available:
                self.write_local_fallback(key, value)
                migrated.append(key)

        dotenv_path.unlink(missing_ok=True)
        return {
            "migrated": bool(migrated),
            "keys": migrated,
            "target": str(self.local_fallback_path),
        }

    @staticmethod
    def mask(value: str | None) -> str | None:
        if not value:
            return None
        if len(value) <= 8:
            return "*" * len(value)
        return f"{value[:4]}...{value[-4:]}"

    def _from_infisical(self, name: str) -> SecretLookup:
        executable = self._infisical_binary()
        if not executable:
            return SecretLookup(value=None, source="infisical_missing", available=False)
        if not self.config.infisical_environment:
            return SecretLookup(value=None, source="infisical_unconfigured", available=False)
        if not self.infisical_resolution_ready():
            return SecretLookup(value=None, source="infisical_not_ready", available=False)

        if self._infisical_cache is None:
            command = [
                executable,
                "export",
                "--format",
                "json",
                "--env",
                self.config.infisical_environment,
                "--path",
                self.config.infisical_path,
                "--silent",
            ]
            token = self._resolved_infisical_access_token()
            effective_project_id = self._effective_infisical_project_id()
            if token and effective_project_id:
                command.extend(["--projectId", effective_project_id])
            elif self.config.infisical_project_id:
                command.extend(["--projectId", self.config.infisical_project_id])
            if token:
                command.extend(["--token", token])
            elif self.config.mode == "infisical_required":
                return SecretLookup(value=None, source="infisical_machine_auth_missing", available=False)
            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=10,
                )
                loaded = json.loads(completed.stdout or "[]")
                if isinstance(loaded, list):
                    self._infisical_cache = {
                        str(item.get("key")): str(item.get("value"))
                        for item in loaded
                        if isinstance(item, dict) and item.get("key") is not None
                    }
                elif isinstance(loaded, dict):
                    self._infisical_cache = {str(key): str(value) for key, value in loaded.items()}
                else:
                    self._infisical_cache = {}
            except Exception:
                self._infisical_cache = {}

        value = self._infisical_cache.get(name) if self._infisical_cache is not None else None
        if value:
            return SecretLookup(value=value, source="infisical", available=True)
        return SecretLookup(value=None, source="infisical_unresolved", available=False)

    def _infisical_binary(self) -> str | None:
        executable = shutil.which("infisical")
        if executable:
            return executable

        user_local = Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Packages"
        if user_local.exists():
            matches = sorted(user_local.glob("infisical.infisical_*\\infisical.exe"))
            if matches:
                return str(matches[-1])
        return None

    def _resolved_infisical_access_token(self) -> str | None:
        if self._infisical_access_token_cache:
            return self._infisical_access_token_cache

        explicit_lookup = self._lookup_process_or_windows_env(self.config.infisical_token_env)
        if explicit_lookup.available and explicit_lookup.value:
            self._infisical_access_token_cache = explicit_lookup.value
            self._infisical_access_token_source = "token_env"
            return self._infisical_access_token_cache

        if not self._machine_auth_ready():
            return None

        executable = self._infisical_binary()
        if not executable:
            return None

        client_id = self._lookup_process_or_windows_env(self.config.infisical_universal_auth_client_id_env).value
        client_secret = self._lookup_process_or_windows_env(self.config.infisical_universal_auth_client_secret_env).value
        if not client_id or not client_secret:
            return None

        command = [
            executable,
            "login",
            "--method",
            "universal-auth",
            "--client-id",
            client_id,
            "--client-secret",
            client_secret,
            "--domain",
            "https://app.infisical.com/api",
            "--silent",
            "--plain",
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=True,
                timeout=15,
            )
        except Exception:
            return None
        token = completed.stdout.strip()
        if not token:
            return None
        self._infisical_access_token_cache = token
        self._infisical_access_token_source = "universal_auth"
        return token

    def _resolved_infisical_access_token_source(self) -> str | None:
        self._resolved_infisical_access_token()
        return self._infisical_access_token_source

    def _machine_auth_ready(self) -> bool:
        client_id = self._lookup_process_or_windows_env(self.config.infisical_universal_auth_client_id_env)
        client_secret = self._lookup_process_or_windows_env(self.config.infisical_universal_auth_client_secret_env)
        return client_id.available and client_secret.available

    def _infisical_auth_mode(self) -> str:
        if self._lookup_process_or_windows_env(self.config.infisical_token_env).available:
            return "token_env"
        if self._machine_auth_ready():
            return "universal_auth"
        if self._infisical_project_link_present() and self._infisical_binary():
            return "user_session_fallback"
        return "unavailable"

    def _infisical_project_link_present(self) -> bool:
        if not self.repo_root:
            return False
        return (self.repo_root / ".infisical.json").exists()

    def _effective_infisical_project_id(self) -> str | None:
        if self.config.infisical_project_id:
            return self.config.infisical_project_id
        if not self.repo_root:
            return None
        link_path = self.repo_root / ".infisical.json"
        if not link_path.exists():
            return None
        try:
            payload = json.loads(link_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        workspace_id = payload.get("workspaceId")
        return str(workspace_id) if workspace_id else None

    def _lookup_process_or_windows_env(self, name: str) -> SecretLookup:
        env_value = os.getenv(name)
        if env_value:
            return SecretLookup(value=env_value, source="process_env", available=True)
        return self._from_windows_user_env(name)

    def _from_windows_user_env(self, name: str) -> SecretLookup:
        if winreg is None:
            return SecretLookup(value=None, source="windows_user_env_unavailable", available=False)
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment")
            try:
                value, _ = winreg.QueryValueEx(key, name)
            finally:
                winreg.CloseKey(key)
            if value:
                return SecretLookup(value=str(value), source="windows_user_env", available=True)
        except FileNotFoundError:
            pass
        except OSError:
            pass
        return SecretLookup(value=None, source="windows_user_env_missing", available=False)

    def _from_local_file(self, name: str) -> SecretLookup:
        payload = self._read_local_json()
        value = payload.get(name)
        if value:
            return SecretLookup(value=str(value), source="local_fallback", available=True)
        return SecretLookup(value=None, source="local_fallback_missing", available=False)

    def _read_local_json(self) -> dict[str, Any]:
        if not self.local_fallback_path.exists():
            return {}
        try:
            return json.loads(self.local_fallback_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
