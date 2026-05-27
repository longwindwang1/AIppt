"""Token 成本估算。

价格基于 Anthropic 2026-05 公开定价。Per-model dict 让升级时改一处。
可通过 env 覆盖：AIPPT_INPUT_USD_PER_MTOK / AIPPT_OUTPUT_USD_PER_MTOK
"""
from __future__ import annotations

import os

# {model_id: (input, output)} USD per million tokens
_PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-4-7": (15.00, 75.00),
    "claude-opus-4-6": (15.00, 75.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-sonnet-4-5": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
}

# Anthropic prompt caching multipliers (基于 input 单价)
CACHE_WRITE_MULTIPLIER = 1.25       # 写入缓存比正常 input 贵 25%
CACHE_READ_MULTIPLIER = 0.10        # 读缓存只要 10%


def _rates(model_id: str | None = None) -> tuple[float, float]:
    env_in = os.getenv("AIPPT_INPUT_USD_PER_MTOK")
    env_out = os.getenv("AIPPT_OUTPUT_USD_PER_MTOK")
    if env_in is not None and env_out is not None:
        return float(env_in), float(env_out)
    if model_id and model_id in _PRICING:
        return _PRICING[model_id]
    # 默认 Sonnet 4.6
    return _PRICING["claude-sonnet-4-6"]


def estimate_cost(
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    model_id: str | None = None,
) -> float:
    in_rate, out_rate = _rates(model_id)
    cost = (
        input_tokens / 1_000_000 * in_rate
        + output_tokens / 1_000_000 * out_rate
        + cache_read_tokens / 1_000_000 * in_rate * CACHE_READ_MULTIPLIER
        + cache_write_tokens / 1_000_000 * in_rate * CACHE_WRITE_MULTIPLIER
    )
    return round(cost, 4)
