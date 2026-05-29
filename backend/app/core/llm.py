"""
app/core/llm.py — Single LLM client for the entire application.

DRY PRINCIPLE: Every agent imports from here.
No agent ever imports groq directly.
Changing the model = changing ONE line in this file.

TENACITY: Automatic retry on rate limits and transient errors.
Without this, one API hiccup fails the entire 30-second pipeline.
"""

import logging
from functools import lru_cache
from typing import Any

from groq import APIStatusError, Groq, RateLimitError
from tenacity import (
    before_sleep_log,
    retry,
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


def estimate_message_tokens(messages: list[dict[str, str]], max_tokens: int = 0) -> int:
    """Estimate total tokens (prompt + reserved completion) for a chat request."""
    prompt_chars = sum(len(m.get("content", "") or "") for m in messages)
    return int(prompt_chars / _CHARS_PER_TOKEN) + max_tokens


class LLMClient:
    """
    Wrapper around Groq API with retry logic and structured output support.

    USAGE:
        from app.core.llm import get_llm_client
        client = get_llm_client()

        # Simple completion
        response = await client.complete([
            {"role": "user", "content": "What is 2+2?"}
        ])

        # Structured JSON output (used by all agents)
        data = await client.complete_json([
            {"role": "system", "content": "Return JSON only."},
            {"role": "user", "content": "Extract constraints from: ..."}
        ])
    """

    def __init__(self) -> None:
        if not settings.GROQ_API_KEY:
            raise ValueError(
                "GROQ_API_KEY is not set. "
                "Get your free key at https://console.groq.com"
            )
        self._client = Groq(api_key=settings.GROQ_API_KEY)
        self._model = settings.LLM_MODEL_NAME
        self._rate_limiter = get_rate_limiter()
        logger.info("LLM client initialized (provider=groq, model=%s)", self._model)

    @retry(
        retry=retry_if_exception_type((RateLimitError, APIStatusError)),
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
    ) -> str:
        """
        Send messages to the LLM and return the response as a string.

        temperature=0.1 means near-deterministic responses.
        For agent reasoning tasks, we want consistent output, not creativity.

        Args:
            messages: OpenAI-format message list
                [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]
            model: Which LLM to use
            max_tokens: Maximum response length
            temperature: 0.0 = deterministic, 1.0 = creative

        Returns:
            The model's text response as a string.

        Raises:
            RateLimitError: After 3 retries with exponential backoff
            APIStatusError: On non-retryable API errors
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
        )
        self._record_usage(resolved_model, ts, response)
        return response.choices[0].message.content or ""

    @retry(
        retry=retry_if_exception_type((RateLimitError, APIStatusError)),
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
        """
        Like complete() but forces the model to return valid JSON.

        Uses Groq's response_format={"type": "json_object"} feature.
        The model WILL return valid JSON — no parsing failures from
        partial JSON or markdown code blocks.

        IMPORTANT: Your system prompt MUST instruct the model to return JSON.
        Groq requires this — it enables JSON mode based on system prompt content.

        temperature=0.0 for structured outputs: we want exact, predictable JSON.
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
        """Feed the real token count back to the throttle window."""
        usage = getattr(response, "usage", None)
        total = getattr(usage, "total_tokens", None)
        if total is not None:
            self._rate_limiter.update_actual_tokens(model, ts, int(total))

    def count_tokens_estimate(self, text: str) -> int:
        """
        Rough token count estimate.
        Rule of thumb: 1 token ≈ 4 characters for English text.
        Used to avoid hitting context window limits.
        """
        return len(text) // 4


@lru_cache(maxsize=1)
def get_llm_client() -> LLMClient:
    """
    Returns a cached LLM client instance.
    One client for the entire application lifecycle.

    @lru_cache ensures the Groq client is only created once,
    not on every agent call.
    """
    return LLMClient()
