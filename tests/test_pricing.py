"""测价格表 + caching 成本计算。"""
from __future__ import annotations

import pytest

from app.services import pricing


def test_estimate_cost_basic_sonnet():
    # Sonnet 4.6: 3 / 15 per MTok
    # 1M input + 1M output = 3 + 15 = 18
    assert pricing.estimate_cost(1_000_000, 1_000_000) == 18.0


def test_estimate_cost_with_cache():
    # 1M input + 1M cache read + 1M cache write + 1M output
    # = 3 + 0.30 + 3.75 + 15 = 22.05
    cost = pricing.estimate_cost(
        input_tokens=1_000_000, output_tokens=1_000_000,
        cache_read_tokens=1_000_000, cache_write_tokens=1_000_000,
    )
    assert cost == pytest.approx(22.05, rel=1e-3)


def test_per_model_rates():
    # Opus 4.7: 15 / 75
    assert pricing.estimate_cost(1_000_000, 0, model_id="claude-opus-4-7") == 15.0
    # Sonnet 4.6: 3 / 15
    assert pricing.estimate_cost(1_000_000, 0, model_id="claude-sonnet-4-6") == 3.0
    # Haiku 4.5: 1 / 5
    assert pricing.estimate_cost(1_000_000, 0, model_id="claude-haiku-4-5") == 1.0


def test_unknown_model_defaults_to_sonnet():
    assert pricing.estimate_cost(1_000_000, 0, model_id="claude-future-99") == 3.0


def test_env_override(monkeypatch):
    monkeypatch.setenv("AIPPT_INPUT_USD_PER_MTOK", "10.0")
    monkeypatch.setenv("AIPPT_OUTPUT_USD_PER_MTOK", "50.0")
    # need to reload module-level get_rates… simplest is to call internal helper
    assert pricing.estimate_cost(1_000_000, 1_000_000) == 60.0
