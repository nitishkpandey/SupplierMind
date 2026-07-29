"""Context-variable binding for privacy-aware AI requests."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import replace
from typing import Any

from app.platform.ai.types import AIRequestContext

_UNCLASSIFIED = AIRequestContext(purpose="unclassified")
_CURRENT_AI_CONTEXT: ContextVar[AIRequestContext] = ContextVar(
    "suppliermind_ai_request_context",
    default=_UNCLASSIFIED,
)


def current_ai_request_context() -> AIRequestContext:
    return _CURRENT_AI_CONTEXT.get()


@contextmanager
def ai_request_scope(
    context: AIRequestContext,
) -> Iterator[AIRequestContext]:
    token = _CURRENT_AI_CONTEXT.set(context)
    try:
        yield context
    finally:
        _CURRENT_AI_CONTEXT.reset(token)


def derive_ai_request_context(**changes: Any) -> AIRequestContext:
    return replace(current_ai_request_context(), **changes)
