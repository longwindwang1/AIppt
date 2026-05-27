"""Token 成本估算。

价格基于 Anthropic 2026-05 公开定价（claude-sonnet-4-6）。
若价格变动，改这里的常量即可。可通过 env 覆盖。
"""
from __future__ import annotations

import os

INPUT_USD_PER_MTOK = float(os.getenv("AIPPT_INPUT_USD_PER_MTOK", "3.00"))
OUTPUT_USD_PER_MTOK = float(os.getenv("AIPPT_OUTPUT_USD_PER_MTOK", "15.00"))


def estimate_cost(input_tokens: int, output_tokens: int) -> float:
    return round(
        input_tokens / 1_000_000 * INPUT_USD_PER_MTOK
        + output_tokens / 1_000_000 * OUTPUT_USD_PER_MTOK,
        4,
    )
