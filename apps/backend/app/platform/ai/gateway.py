"""Policy-enforcing facades around text and embedding transports."""

from __future__ import annotations

import time
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.platform.ai.budget import (
    AIBudgetExceeded,
    BudgetReservation,
)
from app.platform.ai.context import current_ai_request_context
from app.platform.ai.policy import AIPolicyEngine
from app.platform.ai.types import (
    AIOperation,
    AIOutcome,
    AIRequestContext,
    AIUsageMeasurement,
    ProviderUsage,
)
from app.platform.ai.usage import AIUsageRecorder


class ProviderUsageContractError(RuntimeError):
    """Raised when a transport fails its usage-reporting contract."""


@dataclass(slots=True)
class _ActiveAICall:
    context: AIRequestContext
    started_at: float
    operation: AIOperation
    reservation: BudgetReservation | None = None


def _elapsed_ms(started_at: float) -> int:
    return max(0, int((time.monotonic() - started_at) * 1000))


class _ProviderGateway:
    def __init__(
        self,
        transport: Any,
        policy: AIPolicyEngine,
        recorder: AIUsageRecorder,
    ) -> None:
        self._transport = transport
        self._policy = policy
        self._recorder = recorder
        self._active_call: ContextVar[_ActiveAICall | None] = ContextVar(
            f"{type(self).__name__}_active_call_{id(self)}",
            default=None,
        )
        self._transport.set_usage_callback(self._record_provider_usage)

    @property
    def transport(self) -> Any:
        return self._transport

    @property
    def provider_name(self) -> str:
        return str(self._transport.provider_name)

    @property
    def model_name(self) -> str:
        return str(self._transport.model_name)

    def _measurement(
        self,
        active: _ActiveAICall,
        *,
        input_units: int,
        output_units: int,
        cost_usd: Decimal | None,
        latency_ms: int,
        outcome: AIOutcome,
        provider: str | None = None,
        model: str | None = None,
        error_code: str | None = None,
    ) -> AIUsageMeasurement:
        context = active.context
        return AIUsageMeasurement(
            purpose=context.purpose,
            classification=context.classification,
            operation=active.operation,
            provider=provider or self.provider_name,
            model=model or self.model_name,
            input_units=input_units,
            output_units=output_units,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            outcome=outcome,
            query_id=context.query_id,
            user_id=context.user_id,
            job_id=context.job_id,
            source_document_id=context.source_document_id,
            correlation_id=context.correlation_id,
            redaction_applied=context.redaction_applied,
            excerpted=context.excerpted,
            error_code=error_code,
        )

    def _record_provider_usage(self, usage: ProviderUsage) -> None:
        active = self._active_call.get()
        if active is None:
            raise ProviderUsageContractError(
                "AI transport emitted usage outside an active gateway call"
            )
        if usage.provider != self.provider_name:
            raise ProviderUsageContractError(
                "AI transport emitted usage for a different provider"
            )
        if usage.operation is not active.operation:
            raise ProviderUsageContractError(
                "AI transport emitted usage for a different operation"
            )
        if active.reservation is not None:
            if usage.cost_usd is None or active.context.budget is None:
                raise ProviderUsageContractError(
                    "AI transport omitted cost for a reserved call"
                )
            active.context.budget.settle(
                active.reservation,
                usage.cost_usd,
            )
            active.reservation = None
        self._recorder.record(
            self._measurement(
                active,
                provider=usage.provider,
                model=usage.model,
                input_units=usage.input_units,
                output_units=usage.output_units,
                cost_usd=usage.cost_usd,
                latency_ms=usage.latency_ms,
                outcome=AIOutcome.success,
            )
        )

    def _invoke(
        self,
        operation: AIOperation,
        invoke_transport: Callable[[], Any],
        reserve_call: (
            Callable[[AIRequestContext], BudgetReservation | None] | None
        ) = None,
    ) -> Any:
        context = current_ai_request_context()
        active = _ActiveAICall(
            context=context,
            started_at=time.monotonic(),
            operation=operation,
        )
        decision = self._policy.authorize(
            self.provider_name,
            operation,
            context,
        )
        if not decision.allowed:
            self._recorder.record(
                self._measurement(
                    active,
                    input_units=0,
                    output_units=0,
                    cost_usd=Decimal("0"),
                    latency_ms=_elapsed_ms(active.started_at),
                    outcome=AIOutcome.denied,
                    error_code=decision.reason_code,
                )
            )
            self._policy.require_allowed(
                self.provider_name,
                operation,
                context,
            )

        if reserve_call is not None:
            try:
                active.reservation = reserve_call(context)
            except AIBudgetExceeded:
                self._recorder.record(
                    self._measurement(
                        active,
                        input_units=0,
                        output_units=0,
                        cost_usd=Decimal("0"),
                        latency_ms=_elapsed_ms(active.started_at),
                        outcome=AIOutcome.budget_exceeded,
                        error_code="AIBudgetExceeded",
                    )
                )
                raise

        token = self._active_call.set(active)
        try:
            try:
                result = invoke_transport()
            except BaseException as exc:
                if (
                    active.reservation is not None
                    and active.context.budget is not None
                ):
                    active.context.budget.release(active.reservation)
                    active.reservation = None
                self._recorder.record(
                    self._measurement(
                        active,
                        input_units=0,
                        output_units=0,
                        cost_usd=None,
                        latency_ms=_elapsed_ms(active.started_at),
                        outcome=AIOutcome.error,
                        error_code=type(exc).__name__,
                    )
                )
                raise

            if active.reservation is not None:
                if active.context.budget is not None:
                    active.context.budget.release(active.reservation)
                active.reservation = None
                contract_error = ProviderUsageContractError(
                    "AI transport returned without reporting usage"
                )
                self._recorder.record(
                    self._measurement(
                        active,
                        input_units=0,
                        output_units=0,
                        cost_usd=None,
                        latency_ms=_elapsed_ms(active.started_at),
                        outcome=AIOutcome.error,
                        error_code=type(contract_error).__name__,
                    )
                )
                raise contract_error
            return result
        finally:
            self._active_call.reset(token)


class AIGateway(_ProviderGateway):
    @property
    def total_cost_usd(self) -> float:
        return float(getattr(self._transport, "total_cost_usd", 0.0))

    @property
    def last_provider_used(self) -> str:
        return self.provider_name

    def _reserve_text_call(
        self,
        context: AIRequestContext,
        messages: list[dict[str, str]],
        kwargs: dict[str, Any],
    ) -> BudgetReservation | None:
        from app.core.llm import (
            DEFAULT_MAX_TOKENS,
            estimate_call_cost_usd,
            estimate_message_tokens,
        )

        max_tokens = int(kwargs.get("max_tokens", DEFAULT_MAX_TOKENS))
        model = str(kwargs.get("model") or self.model_name)
        estimated_tokens = estimate_message_tokens(messages, max_tokens)
        if estimated_tokens > context.max_call_tokens:
            raise AIBudgetExceeded(
                f"AI call token limit exceeded: {estimated_tokens} "
                f"> {context.max_call_tokens}"
            )
        estimated_cost = Decimal(
            str(
                estimate_call_cost_usd(
                    model,
                    estimated_tokens - max_tokens,
                    max_tokens,
                )
            )
        )
        if estimated_cost > context.max_call_cost_usd:
            raise AIBudgetExceeded(
                f"AI call cost limit exceeded: ${estimated_cost} "
                f"> ${context.max_call_cost_usd}"
            )
        if context.budget is None:
            return None
        return context.budget.reserve(estimated_cost)

    def complete(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> str:
        return str(
            self._invoke(
                AIOperation.chat,
                lambda: self._transport.complete(messages, **kwargs),
                lambda context: self._reserve_text_call(
                    context,
                    messages,
                    kwargs,
                ),
            )
        )

    def complete_json(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> str:
        return str(
            self._invoke(
                AIOperation.chat_json,
                lambda: self._transport.complete_json(messages, **kwargs),
                lambda context: self._reserve_text_call(
                    context,
                    messages,
                    kwargs,
                ),
            )
        )


class EmbeddingGateway(_ProviderGateway):
    @staticmethod
    def _enforce_embedding_token_limit(
        context: AIRequestContext,
        texts: list[str],
    ) -> None:
        estimated_tokens = sum(
            max(1, (len(text) + 3) // 4) for text in texts
        )
        if estimated_tokens > context.max_call_tokens:
            raise AIBudgetExceeded(
                f"AI call token limit exceeded: {estimated_tokens} "
                f"> {context.max_call_tokens}"
            )

    def embed_batch(
        self,
        texts: list[str],
        input_type: str = "document",
    ) -> list[list[float]]:
        return self._invoke(
            AIOperation.embedding,
            lambda: self._transport.embed_batch(
                texts,
                input_type=input_type,
            ),
            lambda context: self._enforce_embedding_token_limit(
                context,
                texts,
            ),
        )

    def embed_one(
        self,
        text: str,
        input_type: str = "document",
    ) -> list[float]:
        values = self.embed_batch([text], input_type=input_type)
        return values[0]

    def embed_supplier_text(self, supplier: dict[str, Any]) -> str:
        return str(self._transport.embed_supplier_text(supplier))
