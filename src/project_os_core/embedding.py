from __future__ import annotations

import hashlib
import math
import os
from dataclasses import dataclass
from typing import Literal

from openai import OpenAI

from .config import EmbeddingPolicy, RuntimeConfig, load_runtime_config
from .secrets import SecretResolver


EmbeddingProvider = Literal["openai", "local_hash"]
EmbeddingMode = Literal["auto", "openai", "local_hash"]
EmbeddingQuality = Literal["budget", "balanced", "max"]


@dataclass(slots=True)
class EmbeddingStrategy:
    mode: EmbeddingMode
    provider: EmbeddingProvider
    model: str
    dimensions: int
    source: str
    quality: EmbeddingQuality

    @property
    def signature(self) -> str:
        return f"{self.provider}:{self.model}:{self.dimensions}:{self.quality}"


def choose_embedding_strategy(
    config: RuntimeConfig | None = None,
    secret_resolver: SecretResolver | None = None,
) -> EmbeddingStrategy:
    config = config or load_runtime_config()
    secret_resolver = secret_resolver or SecretResolver(config.secret_config, repo_root=config.repo_root)
    policy = config.embedding_policy

    mode = os.getenv("PROJECT_OS_EMBED_PROVIDER", policy.provider_mode).strip().lower() or policy.provider_mode
    quality = os.getenv("PROJECT_OS_EMBED_QUALITY", policy.quality).strip().lower() or policy.quality
    explicit_model = os.getenv("PROJECT_OS_EMBED_MODEL")
    explicit_dimensions = os.getenv("PROJECT_OS_EMBED_DIMENSIONS")
    openai_key = secret_resolver.get_optional("OPENAI_API_KEY")

    if quality not in {"budget", "balanced", "max"}:
        quality = "balanced"

    if mode not in {"auto", "openai", "local_hash"}:
        mode = "auto"

    if mode == "openai" and not openai_key:
        raise RuntimeError("PROJECT_OS_EMBED_PROVIDER=openai but OPENAI_API_KEY is missing")

    if mode == "auto" and openai_key:
        provider = "openai"
        source = "OPENAI_API_KEY"
    elif mode == "openai":
        provider = "openai"
        source = "PROJECT_OS_EMBED_PROVIDER"
    else:
        provider = "local_hash"
        source = "fallback"

    if provider == "openai":
        model = explicit_model or _choose_openai_model(policy, quality)
        if explicit_dimensions:
            dimensions = int(explicit_dimensions)
        else:
            dimensions = 3072 if model == "text-embedding-3-large" else 1536
        return EmbeddingStrategy(
            mode=mode, provider=provider, model=model, dimensions=dimensions, source=source, quality=quality
        )

    dimensions = int(explicit_dimensions) if explicit_dimensions else policy.local_dimensions
    return EmbeddingStrategy(
        mode=mode,
        provider="local_hash",
        model=explicit_model or policy.local_model,
        dimensions=dimensions,
        source=source,
        quality=quality,
    )


def _choose_openai_model(policy: EmbeddingPolicy, quality: EmbeddingQuality) -> str:
    if quality == "max":
        return policy.max_openai_model
    return policy.default_openai_model


class EmbeddingService:
    def __init__(self, strategy: EmbeddingStrategy, secret_resolver: SecretResolver | None = None):
        self.strategy = strategy
        api_key = secret_resolver.get_required("OPENAI_API_KEY") if strategy.provider == "openai" and secret_resolver else os.getenv("OPENAI_API_KEY")
        self._client = OpenAI(api_key=api_key) if strategy.provider == "openai" else None

    def embed_text(self, text: str) -> list[float]:
        if self.strategy.provider == "openai":
            response = self._client.embeddings.create(
                input=text,
                model=self.strategy.model,
                dimensions=self.strategy.dimensions,
            )
            return list(response.data[0].embedding)
        return self._local_hash_embedding(text, self.strategy.dimensions)

    @staticmethod
    def vector_literal(vector: list[float]) -> str:
        import json

        return json.dumps(vector, ensure_ascii=True)

    @staticmethod
    def _local_hash_embedding(text: str, dimensions: int) -> list[float]:
        vector = [0.0] * dimensions
        for token in text.lower().split():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            slot = int.from_bytes(digest[:4], "little") % dimensions
            vector[slot] += 1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]
