"""Unit tests for the LLM provider abstraction (single-provider, post-Phase-C).

Pins the contracts after Groq removal (ADR-002):
  1. build_llm_client returns a bare OpenAIProvider — no fallback wrapper.
  2. An unsupported LLM_PROVIDER raises.
  3. Missing OPENAI_API_KEY raises.
  4. Non-retryable OpenAI errors (auth, insufficient_quota) fail fast / propagate
     — there is no fallback to mask them.
  5. Model name + stop passthrough reaches the SDK call.
  6. Cost estimation math.

No live API calls anywhere — SDK clients are faked.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import openai
import pytest

from app.core import llm as llm_mod
from app.core.llm import (
    OpenAIProvider,
    UnknownModelCostError,
    build_llm_client,
    estimate_call_cost_usd,
)


def _openai_error(cls, status_code: int):
    """Construct an openai APIStatusError subclass with minimal plumbing."""
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(status_code, request=request)
    return cls("boom", response=response, body=None)


# -- 1 + 2. Provider selection (single provider) -------------------------------


def test_build_llm_client_returns_openai_provider():
    with patch.object(llm_mod.settings, "LLM_PROVIDER", "openai"), \
         patch.object(llm_mod.settings, "OPENAI_API_KEY", "sk-test"), \
         patch("openai.OpenAI", MagicMock()):
        client = build_llm_client()
    assert isinstance(client, OpenAIProvider)
    assert client.provider_name == "openai"


def test_build_llm_client_unsupported_provider_raises():
    # Groq removed (ADR-002): anything but "openai" is rejected.
    with patch.object(llm_mod.settings, "LLM_PROVIDER", "groq"):
        with pytest.raises(ValueError, match="Only 'openai' is supported"):
            build_llm_client()


def test_build_llm_client_openai_without_key_raises():
    with patch.object(llm_mod.settings, "LLM_PROVIDER", "openai"), \
         patch.object(llm_mod.settings, "OPENAI_API_KEY", ""):
        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            build_llm_client()


# -- 3. No fallback: there is no wrapper, and OpenAI failures surface -----------


def test_no_fallback_wrapper_built():
    """The client IS the provider — no FallbackLLMClient layer remains."""
    with patch.object(llm_mod.settings, "LLM_PROVIDER", "openai"), \
         patch.object(llm_mod.settings, "OPENAI_API_KEY", "sk-test"), \
         patch("openai.OpenAI", MagicMock()):
        client = build_llm_client()
    assert type(client) is OpenAIProvider
    assert not hasattr(client, "_fallback")


def test_authentication_error_propagates_without_retry():
    fake_sdk = MagicMock()
    fake_sdk.chat.completions.create.side_effect = _openai_error(
        openai.AuthenticationError, 401
    )
    with patch.object(llm_mod.settings, "OPENAI_API_KEY", "sk-test"), \
         patch("openai.OpenAI", MagicMock(return_value=fake_sdk)):
        provider = OpenAIProvider()
        with pytest.raises(openai.AuthenticationError):
            provider.complete([{"role": "user", "content": "hi"}])
    assert fake_sdk.chat.completions.create.call_count == 1, \
        "auth errors must surface immediately — no retry, no fallback to mask them"


# -- 4. insufficient_quota: never retry ----------------------------------------


def _quota_error() -> openai.RateLimitError:
    """A 429 whose code is insufficient_quota — waiting can never fix it."""
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(429, request=request)
    return openai.RateLimitError(
        "Error code: 429 - insufficient_quota",
        response=response,
        body={"code": "insufficient_quota", "type": "insufficient_quota"},
    )


def test_insufficient_quota_is_not_retryable():
    assert llm_mod._is_retryable_openai_error(_quota_error()) is False
    # A plain 429 (requests-per-minute) stays retryable.
    assert llm_mod._is_retryable_openai_error(_openai_error(openai.RateLimitError, 429)) is True


def test_openai_provider_does_not_retry_insufficient_quota():
    fake_sdk = MagicMock()
    fake_sdk.chat.completions.create.side_effect = _quota_error()

    with patch.object(llm_mod.settings, "OPENAI_API_KEY", "sk-test"), \
         patch("openai.OpenAI", MagicMock(return_value=fake_sdk)):
        provider = OpenAIProvider()
        with pytest.raises(openai.RateLimitError):
            provider.complete([{"role": "user", "content": "hi"}])

    assert fake_sdk.chat.completions.create.call_count == 1, \
        "insufficient_quota must fail fast — retrying cannot refill the quota"


# -- 5. Model name passthrough ---------------------------------------------------


def test_openai_provider_passes_model_and_stop_through():
    fake_completion = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="answer"))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )
    fake_sdk = MagicMock()
    fake_sdk.chat.completions.create.return_value = fake_completion

    with patch.object(llm_mod.settings, "OPENAI_API_KEY", "sk-test"), \
         patch("openai.OpenAI", MagicMock(return_value=fake_sdk)):
        provider = OpenAIProvider()
        out = provider.complete(
            [{"role": "user", "content": "hi"}],
            model="gpt-4o-mini-2024-07-18",
            stop=["\nObservation:"],
        )

    assert out == "answer"
    kwargs = fake_sdk.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "gpt-4o-mini-2024-07-18"
    assert kwargs["stop"] == ["\nObservation:"]


# -- 6. Cost estimation ----------------------------------------------------------


def test_cost_estimate_gpt4o_mini():
    # 1M prompt tokens at $0.15 + 1M completion at $0.60
    assert estimate_call_cost_usd("gpt-4o-mini", 1_000_000, 1_000_000) == pytest.approx(0.75)
    # Unknown models FAIL LOUD (Audit H) — no silent $0 that corrupts spend.
    with pytest.raises(UnknownModelCostError):
        estimate_call_cost_usd("mystery-model", 1000, 1000)
