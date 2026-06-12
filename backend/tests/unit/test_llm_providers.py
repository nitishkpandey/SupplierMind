"""Unit tests for the LLM provider abstraction (Development Plan, Phase 1).

Pins the contracts the provider migration depends on:
  1. Provider selection follows settings.LLM_PROVIDER.
  2. OpenAI primary + Groq fallback wrapper is built when both keys exist.
  3. Fallback fires on retryable errors (rate limit, 5xx) ...
  4. ... and does NOT fire on auth errors (a bad key must surface).
  5. Model name passthrough reaches the SDK call.
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
    FallbackLLMClient,
    GroqProvider,
    OpenAIProvider,
    build_llm_client,
    estimate_call_cost_usd,
)


def _openai_error(cls, status_code: int):
    """Construct an openai APIStatusError subclass with minimal plumbing."""
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(status_code, request=request)
    return cls("boom", response=response, body=None)


class _FakeProvider:
    """Stands in for a real provider inside FallbackLLMClient tests."""

    def __init__(self, name: str, result: str | None = None, error: Exception | None = None):
        self.provider_name = name
        self.result = result
        self.error = error
        self.calls: list[tuple[str, dict]] = []
        self.total_cost_usd = 0.0

    def complete(self, messages, **kwargs):
        self.calls.append(("complete", kwargs))
        if self.error is not None:
            raise self.error
        return self.result or "ok"

    def complete_json(self, messages, **kwargs):
        self.calls.append(("complete_json", kwargs))
        if self.error is not None:
            raise self.error
        return self.result or "{}"


# -- 1 + 2. Provider selection -------------------------------------------------


def test_build_llm_client_groq_by_default():
    with patch.object(llm_mod.settings, "LLM_PROVIDER", "groq"), \
         patch.object(llm_mod.settings, "GROQ_API_KEY", "gsk-test"), \
         patch.object(llm_mod, "Groq", MagicMock()):
        client = build_llm_client()
    assert isinstance(client, GroqProvider)
    assert client.provider_name == "groq"


def test_build_llm_client_openai_with_groq_fallback():
    with patch.object(llm_mod.settings, "LLM_PROVIDER", "openai"), \
         patch.object(llm_mod.settings, "OPENAI_API_KEY", "sk-test"), \
         patch.object(llm_mod.settings, "GROQ_API_KEY", "gsk-test"), \
         patch.object(llm_mod, "Groq", MagicMock()), \
         patch("openai.OpenAI", MagicMock()):
        client = build_llm_client()
    assert isinstance(client, FallbackLLMClient)
    assert client.provider_name == "openai+groq-fallback"


def test_build_llm_client_openai_without_key_raises():
    with patch.object(llm_mod.settings, "LLM_PROVIDER", "openai"), \
         patch.object(llm_mod.settings, "OPENAI_API_KEY", ""):
        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            build_llm_client()


# -- 3. Fallback fires on retryable failure ------------------------------------


def test_fallback_fires_on_rate_limit():
    primary = _FakeProvider("openai", error=_openai_error(openai.RateLimitError, 429))
    fallback = _FakeProvider("groq", result="served-by-groq")
    client = FallbackLLMClient(primary, fallback)

    out = client.complete([{"role": "user", "content": "hi"}])

    assert out == "served-by-groq"
    assert client.last_provider_used == "groq"
    assert fallback.calls, "fallback provider must have been called"


def test_fallback_fires_on_server_error():
    primary = _FakeProvider("openai", error=_openai_error(openai.InternalServerError, 500))
    fallback = _FakeProvider("groq", result="{}")
    client = FallbackLLMClient(primary, fallback)

    out = client.complete_json([{"role": "user", "content": "json please"}])

    assert out == "{}"
    assert client.last_provider_used == "groq"


# -- 4. No fallback on auth error ----------------------------------------------


def test_no_fallback_on_authentication_error():
    primary = _FakeProvider("openai", error=_openai_error(openai.AuthenticationError, 401))
    fallback = _FakeProvider("groq", result="should-never-be-returned")
    client = FallbackLLMClient(primary, fallback)

    with pytest.raises(openai.AuthenticationError):
        client.complete([{"role": "user", "content": "hi"}])

    assert fallback.calls == [], "auth errors must surface, not silently fall back"


# -- 4b. insufficient_quota: never retry, still fall back -----------------------


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


def test_fallback_fires_on_insufficient_quota():
    primary = _FakeProvider("openai", error=_quota_error())
    fallback = _FakeProvider("groq", result="served-by-groq")
    client = FallbackLLMClient(primary, fallback)

    out = client.complete([{"role": "user", "content": "hi"}])

    assert out == "served-by-groq"
    assert client.last_provider_used == "groq"


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
    # Groq free tier costs nothing
    assert estimate_call_cost_usd("llama-3.1-8b-instant", 50_000, 10_000) == 0.0
    # Unknown models cost 0 rather than crashing
    assert estimate_call_cost_usd("mystery-model", 1000, 1000) == 0.0
