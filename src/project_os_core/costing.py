from __future__ import annotations

import math
import re
from dataclasses import dataclass

USD_TO_EUR = 0.92

PRICING_PER_MILLION_USD: dict[str, dict[str, float]] = {
    "gpt-5": {"input": 1.25, "output": 10.0},
    "gpt-5-mini": {"input": 0.25, "output": 2.0},
    "gpt-5.4": {"input": 2.5, "output": 15.0},
    "gpt-5.4-pro": {"input": 30.0, "output": 180.0},
    "claude-haiku-4-5-20251001": {"input": 0.8, "output": 4.0},
    "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
    "claude-opus-4-1": {"input": 15.0, "output": 75.0},
}

_MODEL_PREFIX_ALIASES: tuple[tuple[str, str], ...] = (
    ("gpt-5.4-pro", "gpt-5.4-pro"),
    ("gpt-5.4", "gpt-5.4"),
    ("gpt-5-mini", "gpt-5-mini"),
    ("gpt-5", "gpt-5"),
    ("claude-opus-4-1", "claude-opus-4-1"),
    ("claude-sonnet-4", "claude-sonnet-4-20250514"),
    ("claude-haiku-4-5", "claude-haiku-4-5-20251001"),
)


@dataclass(slots=True)
class UsageCostEstimate:
    input_tokens: int
    output_tokens: int
    estimated_cost_eur: float


def pricing_for_model(model: str | None) -> dict[str, float] | None:
    normalized = str(model or "").strip().lower()
    if not normalized:
        return None
    if normalized in PRICING_PER_MILLION_USD:
        return PRICING_PER_MILLION_USD[normalized]
    for prefix, alias in _MODEL_PREFIX_ALIASES:
        if normalized.startswith(prefix):
            return PRICING_PER_MILLION_USD.get(alias)
    return None


def estimate_usage_cost_eur(*, model: str | None, input_tokens: int, output_tokens: int) -> float:
    pricing = pricing_for_model(model)
    if not pricing:
        return 0.0
    usd = ((max(int(input_tokens), 0) / 1_000_000) * pricing["input"]) + (
        (max(int(output_tokens), 0) / 1_000_000) * pricing["output"]
    )
    return round(usd * USD_TO_EUR, 6)


def estimate_text_tokens(text: str) -> int:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return 0
    words = re.findall(r"\S+", normalized)
    char_estimate = math.ceil(len(normalized) / 4)
    word_estimate = math.ceil(len(words) * 1.35)
    structure_bonus = min(len(re.findall(r"[`{}\\[\\]()#*_:/-]", normalized)), 160)
    return max(char_estimate, word_estimate) + structure_bonus


def estimate_discussion_usage(
    *,
    message: str,
    mode: str,
    score: int,
    explicit_longform: bool = False,
    recent_turn_count: int = 0,
    base_input_tokens: int | None = None,
) -> UsageCostEstimate:
    normalized_mode = str(mode or "avance").strip().lower()
    prompt_tokens = max(int(base_input_tokens or 0), 0)
    if prompt_tokens <= 0:
        prompt_tokens = estimate_text_tokens(message) + 260
    prompt_tokens += min(max(int(recent_turn_count), 0), 8) * 110

    extra = max(int(score) - 3, 0)
    length_bonus = min(max(prompt_tokens - 400, 0) // 4, 320)
    if normalized_mode == "simple":
        output_tokens = 220 + (35 * extra) + min(length_bonus, 120)
        if explicit_longform:
            output_tokens += 60
    elif normalized_mode == "extreme":
        output_tokens = 1100 + (140 * extra) + min(length_bonus, 320)
        if explicit_longform:
            output_tokens += 500
        output_tokens = int(output_tokens * 1.2)
    else:
        output_tokens = 650 + (80 * extra) + min(length_bonus, 220)
        if explicit_longform:
            output_tokens += 220
        output_tokens = int(output_tokens * 1.1)

    return UsageCostEstimate(
        input_tokens=prompt_tokens,
        output_tokens=output_tokens,
        estimated_cost_eur=0.0,
    )


def estimate_router_usage(
    *,
    objective: str,
    mission_cost_class: str,
    channel: str,
) -> UsageCostEstimate:
    objective_tokens = estimate_text_tokens(objective)
    normalized_class = str(mission_cost_class or "standard").strip().lower()
    normalized_channel = str(channel or "").strip().lower()

    if normalized_class == "cheap":
        if normalized_channel == "discord":
            return UsageCostEstimate(
                input_tokens=objective_tokens + 420,
                output_tokens=260,
                estimated_cost_eur=0.0,
            )
        return UsageCostEstimate(input_tokens=0, output_tokens=0, estimated_cost_eur=0.0)
    if normalized_class == "hard":
        return UsageCostEstimate(
            input_tokens=objective_tokens + 3200,
            output_tokens=1300,
            estimated_cost_eur=0.0,
        )
    if normalized_class == "exceptional":
        return UsageCostEstimate(
            input_tokens=objective_tokens + 5200,
            output_tokens=2200,
            estimated_cost_eur=0.0,
        )
    return UsageCostEstimate(
        input_tokens=objective_tokens + 1800,
        output_tokens=650,
        estimated_cost_eur=0.0,
    )
