"""Cost-table robustness tests (Audit H): exact + prefix match, loud failure
on unknown model, and the startup-guard predicate."""
import pytest

from app.core.llm import (
    UnknownModelCostError,
    estimate_call_cost_usd,
    model_cost_is_known,
    resolve_cost_rates,
)


def test_exact_match_returns_correct_price():
    # gpt-4o-mini: $0.15 prompt / $0.60 completion per 1M tokens
    assert resolve_cost_rates("gpt-4o-mini") == (0.15, 0.60)
    cost = estimate_call_cost_usd("gpt-4o-mini", 1_000_000, 1_000_000)
    assert cost == pytest.approx(0.75)


def test_pinned_snapshot_has_exact_entry():
    assert resolve_cost_rates("gpt-4o-mini-2024-07-18") == (0.15, 0.60)


def test_prefix_match_for_future_snapshot():
    # a dated snapshot not explicitly listed falls back to its family price
    assert resolve_cost_rates("gpt-4o-mini-2025-01-01") == (0.15, 0.60)
    assert model_cost_is_known("gpt-4o-mini-2099-12-31") is True


def test_unknown_model_raises_not_silent_zero():
    with pytest.raises(UnknownModelCostError):
        resolve_cost_rates("totally-made-up-model")
    with pytest.raises(UnknownModelCostError):
        estimate_call_cost_usd("totally-made-up-model", 1000, 1000)
    assert model_cost_is_known("totally-made-up-model") is False


def test_startup_guard_predicate():
    # the main.py startup assertion refuses to boot when this is False
    assert model_cost_is_known("gpt-4o-mini-2024-07-18") is True
    assert model_cost_is_known("gpt-4o") is False  # not a known family prefix


def test_groq_free_tier_is_zero_not_unknown():
    assert resolve_cost_rates("llama-3.1-8b-instant") == (0.0, 0.0)
    assert estimate_call_cost_usd("llama-3.1-8b-instant", 1_000_000, 1_000_000) == 0.0
