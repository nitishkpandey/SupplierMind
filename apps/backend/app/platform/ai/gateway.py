"""Policy-enforcing facades around text and embedding transports."""

from __future__ import annotations

import time
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

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


@dataclass(frozen=True, slots=True)
class _ActiveAICall:
    context: AIRequestContext
    started_at: float
    operation: AIOperation


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
            raise RuntimeError(
                "AI transport emitted usage outside an active gateway call"
            )
        if usage.provider != self.provider_name:
            raise RuntimeError(
                "AI transport emitted usage for a different provider"
            )
        if usage.operation is not active.operation:
            raise RuntimeError(
                "AI transport emitted usage for a different operation"
            )
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
                    cost_usd=None,
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

        token = self._active_call.set(active)
        try:
            return invoke_transport()
        except BaseException as exc:
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
        finally:
            self._active_call.reset(token)


class AIGateway(_ProviderGateway):
    @property
    def total_cost_usd(self) -> float:
        return float(getattr(self._transport, "total_cost_usd", 0.0))

    @property
    def last_provider_used(self) -> str:
        return self.provider_name

    def complete(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> str:
        return str(
            self._invoke(
                AIOperation.chat,
                lambda: self._transport.complete(messages, **kwargs),
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
            )
        )


class EmbeddingGateway(_ProviderGateway):
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
