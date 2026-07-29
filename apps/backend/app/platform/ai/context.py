"""Context-variable binding for privacy-aware AI requests."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import replace
from decimal import Decimal
from typing import Any

from app.core.config import settings
from app.platform.ai.budget import AIBudgetLedger
from app.platform.ai.types import AIRequestContext, DataClassification

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


def new_query_ai_context(
    *,
    purpose: str,
    classification: DataClassification,
    user_id: str | None,
    query_id: str | None,
    correlation_id: str | None = None,
    job_id: str | None = None,
    source_document_id: str | None = None,
    redaction_applied: bool = False,
    excerpted: bool = False,
    initial_spent_usd: Decimal = Decimal("0"),
) -> AIRequestContext:
    """Create a root query context with configured call and query limits."""
    return AIRequestContext(
        purpose=purpose,
        classification=classification,
        user_id=user_id,
        query_id=query_id,
        correlation_id=correlation_id,
        job_id=job_id,
        source_document_id=source_document_id,
        redaction_applied=redaction_applied,
        excerpted=excerpted,
        budget=AIBudgetLedger(
            Decimal(str(settings.AI_MAX_QUERY_COST_USD)),
            initial_spent_usd=initial_spent_usd,
        ),
        max_call_tokens=settings.AI_MAX_CALL_TOKENS,
        max_call_cost_usd=Decimal(str(settings.AI_MAX_CALL_COST_USD)),
    )
