"""
app/core/llm.py — Single LLM access layer for the entire application.

DRY PRINCIPLE: Every agent imports from here.
No agent ever imports groq or openai directly.
Changing the provider = changing LLM_PROVIDER in .env.

PROVIDERS (Development Plan, Phase 1):
  - GroqProvider    llama-3.1-8b-instant via Groq (free tier, TPM-paced)
  - OpenAIProvider  gpt-4o-mini via OpenAI (primary for the benchmark)
  - FallbackLLMClient  OpenAI primary -> Groq on RETRYABLE failure only
    (rate limit, transient 5xx). Auth/config errors propagate immediately —
    falling back would mask a misconfiguration.

TENACITY: Automatic retry on rate limits and transient errors inside each
provider. The fallback wrapper only sees errors that survived the retries.

COST LOGGING: every call logs estimated USD cost and accumulates a running
per-process total (`client.total_cost_usd`) so a benchmark run can report
spend per paradigm.
"""

import logging
import threading
from functools import lru_cache
from typing import Any, Protocol, runtime_checkable

from groq import APIStatusError as GroqAPIStatusError
from groq import Groq
from groq import RateLimitError as GroqRateLimitError
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import settings
from app.core.rate_limiter import get_rate_limiter

logger = logging.getLogger(__name__)

DEFAULT_MAX_TOKENS = 2048

# English-with-JSON/code averages ~3.5 chars/token; close enough to pace the
# throttle. Corrected to the real count via update_actual_tokens after each call.
_CHARS_PER_TOKEN = 3.5

# USD per 1M tokens (prompt, completion). Groq free tier costs nothing but
# keeping an entry makes the cost report uniform across paradigms.
_COST_PER_MTOK_USD: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "llama-3.1-8b-instant": (0.0, 0.0),
    "llama-3.3-70b-versatile": (0.0, 0.0),
}


def estimate_message_tokens(messages: list[dict[str, str]], max_tokens: int = 0) -> int:
    """Estimate total tokens (prompt + reserved completion) for a chat request."""
    prompt_chars = sum(len(m.get("content", "") or "") for m in messages)
    return int(prompt_chars / _CHARS_PER_TOKEN) + max_tokens


def estimate_call_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimated USD cost of one call. Unknown models cost 0 (logged once)."""
    rates = _COST_PER_MTOK_USD.get(model)
    if rates is None:
        return 0.0
    return (prompt_tokens * rates[0] + completion_tokens * rates[1]) / 1_000_000


@runtime_checkable
class LLMProvider(Protocol):
    """The provider contract every backend implements.

    Matches the original LLMClient surface exactly so agents and tests that
    inject fakes with `complete()` / `complete_json()` keep working.
    """

    provider_name: str

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = 0.1,
        stop: list[str] | None = None,
    ) -> str: ...

    def complete_json(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = 0.0,
    ) -> str: ...


class _UsageTracking:
    """Shared cost/usage bookkeeping for providers."""

    def __init__(self) -> None:
        self.total_cost_usd: float = 0.0
        self.total_calls: int = 0
        self._usage_lock = threading.Lock()

    def _track(self, model: str, response: Any) -> None:
        usage = getattr(response, "usage", None)
        prompt_t = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_t = int(getattr(usage, "completion_tokens", 0) or 0)
        cost = estimate_call_cost_usd(model, prompt_t, completion_t)
        with self._usage_lock:
            self.total_calls += 1
            self.total_cost_usd += cost
        if cost:
            logger.info(
                "[llm-cost] model=%s prompt=%d completion=%d est=$%.6f total=$%.4f",
                model, prompt_t, completion_t, cost, self.total_cost_usd,
            )


class GroqProvider(_UsageTracking):
    """Groq backend (llama-3.1-8b-instant) with retry + free-tier TPM pacing."""

    provider_name = "groq"

    def __init__(self, model: str | None = None) -> None:
        super().__init__()
        if not settings.GROQ_API_KEY:
            raise ValueError(
                "GROQ_API_KEY is not set. "
                "Get your free key at https://console.groq.com"
            )
        self._client = Groq(api_key=settings.GROQ_API_KEY)
        self._model = model or settings.LLM_MODEL_NAME
        self._rate_limiter = get_rate_limiter()
        logger.info("LLM client initialized (provider=groq, model=%s)", self._model)

    @retry(
        retry=retry_if_exception_type((GroqRateLimitError, GroqAPIStatusError)),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=2, max=15),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = 0.1,
        stop: list[str] | None = None,
    ) -> str:
        """Send messages to the LLM and return the response as a string.

        temperature=0.1 means near-deterministic responses.
        For agent reasoning tasks, we want consistent output, not creativity.
        """
        resolved_model = model or self._model
        ts = self._rate_limiter.acquire(
            resolved_model, estimate_message_tokens(messages, max_tokens)
        )
        response = self._client.chat.completions.create(
            model=resolved_model,
            messages=messages,  # type: ignore[arg-type]
            max_tokens=max_tokens,
            temperature=temperature,
            stop=stop,
        )
        self._record_usage(resolved_model, ts, response)
        return response.choices[0].message.content or ""

    @retry(
        retry=retry_if_exception_type((GroqRateLimitError, GroqAPIStatusError)),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=2, max=15),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def complete_json(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = 0.0,
    ) -> str:
        """Like complete() but forces the model to return valid JSON.

        Uses response_format={"type": "json_object"}. IMPORTANT: the prompt
        must instruct the model to return JSON (OpenAI enforces the word
        "json" appearing in a message; Groq merely recommends it).
        """
        resolved_model = model or self._model
        ts = self._rate_limiter.acquire(
            resolved_model, estimate_message_tokens(messages, max_tokens)
        )
        response = self._client.chat.completions.create(
            model=resolved_model,
            messages=messages,  # type: ignore[arg-type]
            max_tokens=max_tokens,
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        self._record_usage(resolved_model, ts, response)
        return response.choices[0].message.content or "{}"

    def _record_usage(self, model: str, ts: float, response: Any) -> None:
        """Feed the real token count back to the throttle window + cost log."""
        usage = getattr(response, "usage", None)
        total = getattr(usage, "total_tokens", None)
        if total is not None:
            self._rate_limiter.update_actual_tokens(model, ts, int(total))
        self._track(model, response)

    def count_tokens_estimate(self, text: str) -> int:
        """Rough token count estimate (1 token ~= 4 chars of English)."""
        return len(text) // 4


def _is_retryable_openai_error(exc: BaseException) -> bool:
    """Retry on rate limits and transient 5xx — NEVER on auth/config errors.

    openai.AuthenticationError subclasses APIStatusError, so a plain
    exception-type filter would retry (and later fall back on) a bad API key.
    """
    import openai

    if isinstance(exc, openai.RateLimitError):
        # insufficient_quota is a 429 only by status code: the account is out
        # of credits, so no amount of waiting helps. Fail fast (and let the
        # fallback wrapper take over).
        return getattr(exc, "code", None) != "insufficient_quota"
    if isinstance(exc, openai.APIStatusError):
        return exc.status_code >= 500
    if isinstance(exc, (openai.APIConnectionError, openai.APITimeoutError)):
        return True
    return False


class OpenAIProvider(_UsageTracking):
    """OpenAI backend (gpt-4o-mini) — primary provider for the benchmark."""

    provider_name = "openai"

    def __init__(self, model: str | None = None) -> None:
        super().__init__()
        if not settings.OPENAI_API_KEY:
            raise ValueError(
                "OPENAI_API_KEY is not set but LLM_PROVIDER=openai. "
                "Add the key to backend/.env (or switch LLM_PROVIDER back to groq)."
            )
        import openai

        self._client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
        self._model = model or settings.OPENAI_MODEL_NAME
        self._rate_limiter = get_rate_limiter()
        logger.info("LLM client initialized (provider=openai, model=%s)", self._model)

    @retry(
        retry=retry_if_exception(_is_retryable_openai_error),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=2, max=15),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = 0.1,
        stop: list[str] | None = None,
    ) -> str:
        resolved_model = model or self._model
        ts = self._rate_limiter.acquire(
            resolved_model, estimate_message_tokens(messages, max_tokens)
        )
        response = self._client.chat.completions.create(
            model=resolved_model,
            messages=messages,  # type: ignore[arg-type]
            max_tokens=max_tokens,
            temperature=temperature,
            stop=stop,
        )
        self._record_usage(resolved_model, ts, response)
        return response.choices[0].message.content or ""

    @retry(
        retry=retry_if_exception(_is_retryable_openai_error),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=2, max=15),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def complete_json(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = 0.0,
    ) -> str:
        resolved_model = model or self._model
        ts = self._rate_limiter.acquire(
            resolved_model, estimate_message_tokens(messages, max_tokens)
        )
        response = self._client.chat.completions.create(
            model=resolved_model,
            messages=messages,  # type: ignore[arg-type]
            max_tokens=max_tokens,
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        self._record_usage(resolved_model, ts, response)
        return response.choices[0].message.content or "{}"

    def _record_usage(self, model: str, ts: float, response: Any) -> None:
        usage = getattr(response, "usage", None)
        total = getattr(usage, "total_tokens", None)
        if total is not None:
            self._rate_limiter.update_actual_tokens(model, ts, int(total))
        self._track(model, response)

    def count_tokens_estimate(self, text: str) -> int:
        return len(text) // 4


def _should_fall_back(exc: BaseException) -> bool:
    """Fallback policy: only errors that a different provider could survive.

    Rate limits and transient server errors -> yes. Authentication, invalid
    request, etc. -> no; surfacing those immediately is a feature.

    insufficient_quota is the one split case: not retryable (waiting cannot
    refill the quota) but absolutely fallback-eligible — another provider
    can serve the request.
    """
    try:
        import openai

        if isinstance(exc, openai.RateLimitError):
            return True
        return _is_retryable_openai_error(exc)
    except ImportError:  # openai not installed — nothing to classify
        return False


class FallbackLLMClient:
    """Primary provider with automatic fallback on retryable failure.

    The primary's own tenacity retries run first; only an error that
    SURVIVED them reaches this wrapper. `provider_name` reflects the
    primary so metrics show intent; each call logs which provider served it.
    """

    def __init__(self, primary: Any, fallback: Any) -> None:
        self._primary = primary
        self._fallback = fallback
        self.provider_name = f"{primary.provider_name}+{fallback.provider_name}-fallback"
        self.last_provider_used: str | None = None

    @property
    def total_cost_usd(self) -> float:
        return self._primary.total_cost_usd + self._fallback.total_cost_usd

    def _dispatch(self, method: str, *args: Any, **kwargs: Any) -> str:
        try:
            result = getattr(self._primary, method)(*args, **kwargs)
            self.last_provider_used = self._primary.provider_name
            return result
        except Exception as exc:  # noqa: BLE001 — classified right below
            if not _should_fall_back(exc):
                raise
            logger.warning(
                "[llm-fallback] %s failed on %s (%s: %s) — falling back to %s",
                self._primary.provider_name, method, type(exc).__name__,
                str(exc)[:160], self._fallback.provider_name,
            )
            result = getattr(self._fallback, method)(*args, **kwargs)
            self.last_provider_used = self._fallback.provider_name
            return result

    def complete(self, *args: Any, **kwargs: Any) -> str:
        return self._dispatch("complete", *args, **kwargs)

    def complete_json(self, *args: Any, **kwargs: Any) -> str:
        return self._dispatch("complete_json", *args, **kwargs)

    def count_tokens_estimate(self, text: str) -> int:
        return self._primary.count_tokens_estimate(text)


# Backwards-compatible alias: BaseAgent and the tools type-annotate against
# LLMClient. The Groq implementation IS the historical LLMClient.
LLMClient = GroqProvider


def build_llm_client() -> Any:
    """Provider selection per settings (uncached — used by tests)."""
    if settings.LLM_PROVIDER == "openai":
        primary = OpenAIProvider()
        if settings.GROQ_API_KEY:
            fallback = GroqProvider(model=settings.GROQ_FALLBACK_MODEL_NAME)
            return FallbackLLMClient(primary, fallback)
        logger.warning(
            "LLM_PROVIDER=openai with no GROQ_API_KEY — running without fallback"
        )
        return primary
    if settings.LLM_PROVIDER == "groq":
        return GroqProvider()
    raise ValueError(
        f"Unsupported LLM_PROVIDER={settings.LLM_PROVIDER!r}. "
        "Supported: groq, openai."
    )


@lru_cache(maxsize=1)
def get_llm_client() -> Any:
    """Returns a cached LLM client instance — one for the whole process."""
    return build_llm_client()
