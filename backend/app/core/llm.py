"""
app/core/llm.py — Single LLM access layer for the entire application.

DRY PRINCIPLE: Every agent imports from here.
No agent ever imports openai directly.

PROVIDER (single-provider deployment, see docs/adr/ADR-002):
  - OpenAIProvider  gpt-4o-mini-2024-07-18 via OpenAI — the only provider.
    The LLMProvider Protocol is retained so a future OpenAI-compatible
    provider (Azure OpenAI, etc.) can be swapped in without touching agents.
    Groq was removed in Phase C; there is no fallback. An OpenAI failure that
    survives the per-provider tenacity retries propagates as a clear error.

TENACITY: Automatic retry on rate limits and transient 5xx inside the provider;
auth/config errors propagate immediately (a fallback would mask them).

COST LOGGING: every call logs estimated USD cost and accumulates a running
per-process total (`client.total_cost_usd`) so a benchmark run can report
spend per paradigm.
"""

import logging
import re
import threading
from functools import lru_cache
from typing import Any, Protocol, runtime_checkable

from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
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

# USD per 1M tokens (prompt, completion). Pinned OpenAI snapshots are listed
# explicitly; the prefix fallback in resolve_cost_rates also catches future
# dated snapshots of a known family.
_COST_PER_MTOK_USD: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o-mini-2024-07-18": (0.15, 0.60),
}


class UnknownModelCostError(KeyError):
    """Raised when a model has no cost-table entry (exact or prefix).

    Loud by design: a missing entry must NOT silently bill $0, which would
    corrupt the benchmark spend numbers (Audit H).
    """


def resolve_cost_rates(model: str) -> tuple[float, float]:
    """Return (prompt, completion) $/1M-token rates for a model.

    Exact match first, then a prefix fallback so a dated snapshot
    (``gpt-4o-mini-2024-07-18``) resolves to its family (``gpt-4o-mini``).
    Raises UnknownModelCostError if neither matches — never returns a silent 0.
    """
    if model in _COST_PER_MTOK_USD:
        return _COST_PER_MTOK_USD[model]
    for family, rates in _COST_PER_MTOK_USD.items():
        if model.startswith(family):
            return rates
    raise UnknownModelCostError(
        f"No cost-table entry for model {model!r} (no exact or prefix match). "
        f"Add it to _COST_PER_MTOK_USD in app/core/llm.py."
    )


def model_cost_is_known(model: str) -> bool:
    """True iff `model` resolves in the cost table (exact or prefix)."""
    try:
        resolve_cost_rates(model)
        return True
    except UnknownModelCostError:
        return False


# A pinned snapshot ends in a dated suffix, e.g. gpt-4o-mini-2024-07-18.
# Floating aliases (gpt-4o-mini) are rejected for the primary model so the
# benchmark is reproducible against an exact model build (Audit H / ADR-001).
_SNAPSHOT_RE = re.compile(r"-\d{4}-\d{2}-\d{2}$")


def is_pinned_snapshot(model: str) -> bool:
    """True iff `model` names a dated snapshot, not a floating alias."""
    return bool(_SNAPSHOT_RE.search(model or ""))


def estimate_message_tokens(messages: list[dict[str, str]], max_tokens: int = 0) -> int:
    """Estimate total tokens (prompt + reserved completion) for a chat request."""
    prompt_chars = sum(len(m.get("content", "") or "") for m in messages)
    return int(prompt_chars / _CHARS_PER_TOKEN) + max_tokens


def estimate_call_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimated USD cost of one call. Raises UnknownModelCostError on an
    unknown model rather than silently returning 0 (Audit H)."""
    rates = resolve_cost_rates(model)
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


def _is_retryable_openai_error(exc: BaseException) -> bool:
    """Retry on rate limits and transient 5xx — NEVER on auth/config errors.

    openai.AuthenticationError subclasses APIStatusError, so a plain
    exception-type filter would retry (and later fall back on) a bad API key.
    """
    import openai

    if isinstance(exc, openai.RateLimitError):
        # insufficient_quota is a 429 only by status code: the account is out
        # of credits, so no amount of waiting helps — fail fast.
        return getattr(exc, "code", None) != "insufficient_quota"
    if isinstance(exc, openai.APIStatusError):
        return exc.status_code >= 500
    if isinstance(exc, (openai.APIConnectionError, openai.APITimeoutError)):
        return True
    return False


class OpenAIProvider(_UsageTracking):
    """OpenAI backend (gpt-4o-mini-2024-07-18) — the only provider (ADR-002)."""

    provider_name = "openai"

    def __init__(self, model: str | None = None) -> None:
        super().__init__()
        if not settings.OPENAI_API_KEY:
            raise ValueError(
                "OPENAI_API_KEY is not set. Add the key to backend/.env."
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


# Backwards-compatible alias: BaseAgent and the tools type-annotate against
# LLMClient. Post-Phase-C the single provider is OpenAI.
LLMClient = OpenAIProvider


def build_llm_client() -> Any:
    """Build the single OpenAI provider (uncached — used by tests).

    Single-provider deployment (ADR-002): OpenAI is the only backend. The
    LLMProvider Protocol is kept so a future OpenAI-compatible provider can be
    swapped in, but there is no runtime fallback — an OpenAI failure surfaces.
    """
    if settings.LLM_PROVIDER != "openai":
        raise ValueError(
            f"Unsupported LLM_PROVIDER={settings.LLM_PROVIDER!r}. "
            "Only 'openai' is supported (Groq was removed in Phase C, ADR-002)."
        )
    return OpenAIProvider()


@lru_cache(maxsize=1)
def get_llm_client() -> Any:
    """Returns a cached LLM client instance — one for the whole process."""
    return build_llm_client()
