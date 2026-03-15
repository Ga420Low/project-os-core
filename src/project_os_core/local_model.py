from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any
from urllib import error, request


@dataclass(slots=True)
class LocalModelResponse:
    content: str
    provider: str
    model: str
    latency_ms: int
    raw: dict[str, Any]


class LocalModelClient:
    def __init__(
        self,
        *,
        enabled: bool,
        provider: str,
        base_url: str,
        model: str,
        timeout_seconds: float = 90.0,
        health_timeout_seconds: float = 5.0,
    ) -> None:
        self.enabled = bool(enabled)
        self.provider = provider.strip().lower()
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = float(timeout_seconds)
        self.health_timeout_seconds = float(health_timeout_seconds)
        self._cached_health: dict[str, Any] | None = None
        self._cached_health_at = 0.0

    def health(self, *, force: bool = False) -> dict[str, Any]:
        if not self.enabled:
            return self._health_payload(status="absent", reason="not_configured")
        if self.provider != "ollama":
            return self._health_payload(status="blocked", reason="unsupported_provider")
        now = time.monotonic()
        if not force and self._cached_health is not None and now - self._cached_health_at < 5.0:
            return dict(self._cached_health)
        started = time.perf_counter()
        try:
            payload = self._request_json("/api/tags", timeout_seconds=self.health_timeout_seconds)
        except Exception as exc:
            health = self._health_payload(
                status="blocked",
                reason="service_unreachable",
                error_type=type(exc).__name__,
                error=str(exc),
                latency_ms=_elapsed_ms(started),
            )
            self._remember_health(health)
            return health
        models = payload.get("models")
        if not isinstance(models, list):
            health = self._health_payload(
                status="blocked",
                reason="invalid_health_payload",
                latency_ms=_elapsed_ms(started),
            )
            self._remember_health(health)
            return health
        available_models = [str(item.get("name")) for item in models if isinstance(item, dict) and item.get("name")]
        if self.model not in available_models:
            health = self._health_payload(
                status="blocked",
                reason="model_not_pulled",
                latency_ms=_elapsed_ms(started),
                available_models=available_models,
            )
            self._remember_health(health)
            return health
        health = self._health_payload(
            status="ready",
            reason="model_ready",
            latency_ms=_elapsed_ms(started),
            available_models=available_models,
        )
        self._remember_health(health)
        return health

    def chat(self, *, message: str, system: str, model: str | None = None) -> LocalModelResponse:
        if not self.enabled:
            raise RuntimeError("local_model_disabled")
        if self.provider != "ollama":
            raise RuntimeError(f"unsupported_local_provider:{self.provider}")
        model_name = model or self.model
        started = time.perf_counter()
        payload = self._request_json(
            "/api/chat",
            timeout_seconds=self.timeout_seconds,
            body={
                "model": model_name,
                "stream": False,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": message},
                ],
            },
        )
        message_payload = payload.get("message")
        if not isinstance(message_payload, dict):
            raise RuntimeError("local_chat_missing_message")
        content = str(message_payload.get("content") or "").strip()
        if not content:
            raise RuntimeError("local_chat_empty_response")
        return LocalModelResponse(
            content=content,
            provider=self.provider,
            model=str(payload.get("model") or model_name),
            latency_ms=_elapsed_ms(started),
            raw=payload,
        )

    def _health_payload(self, *, status: str, reason: str, **extra: Any) -> dict[str, Any]:
        return {
            "status": status,
            "reason": reason,
            "provider": self.provider if self.enabled else None,
            "model": self.model if self.enabled else None,
            "base_url": self.base_url if self.enabled else None,
            **extra,
        }

    def _remember_health(self, payload: dict[str, Any]) -> None:
        self._cached_health = dict(payload)
        self._cached_health_at = time.monotonic()

    def _request_json(self, path: str, *, timeout_seconds: float, body: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")
        req = request.Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
        try:
            with request.urlopen(req, timeout=timeout_seconds) as response:
                raw = response.read()
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"http_{exc.code}:{detail}") from exc
        except error.URLError as exc:
            raise RuntimeError(str(exc.reason)) from exc
        parsed = json.loads(raw.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise RuntimeError("invalid_json_payload")
        return parsed


def _elapsed_ms(started: float) -> int:
    return max(1, int((time.perf_counter() - started) * 1000))
