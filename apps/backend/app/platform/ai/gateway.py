"""Policy-enforcing facades around text and embedding transports."""

from __future__ import annotations

from typing import Any

from app.platform.ai.context import current_ai_request_context
from app.platform.ai.policy import AIPolicyEngine
from app.platform.ai.types import AIOperation


class AIGateway:
    def __init__(self, transport: Any, policy: AIPolicyEngine) -> None:
        self._transport = transport
        self._policy = policy

    @property
    def transport(self) -> Any:
        return self._transport

    @property
    def provider_name(self) -> str:
        return str(self._transport.provider_name)

    @property
    def model_name(self) -> str:
        return str(self._transport.model_name)

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
        self._policy.require_allowed(
            self.provider_name,
            AIOperation.chat,
            current_ai_request_context(),
        )
        return str(self._transport.complete(messages, **kwargs))

    def complete_json(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> str:
        self._policy.require_allowed(
            self.provider_name,
            AIOperation.chat_json,
            current_ai_request_context(),
        )
        return str(self._transport.complete_json(messages, **kwargs))


class EmbeddingGateway:
    def __init__(self, transport: Any, policy: AIPolicyEngine) -> None:
        self._transport = transport
        self._policy = policy

    @property
    def transport(self) -> Any:
        return self._transport

    @property
    def provider_name(self) -> str:
        return str(self._transport.provider_name)

    @property
    def model_name(self) -> str:
        return str(self._transport.model_name)

    def embed_batch(
        self,
        texts: list[str],
        input_type: str = "document",
    ) -> list[list[float]]:
        self._policy.require_allowed(
            self.provider_name,
            AIOperation.embedding,
            current_ai_request_context(),
        )
        return self._transport.embed_batch(texts, input_type=input_type)

    def embed_one(
        self,
        text: str,
        input_type: str = "document",
    ) -> list[float]:
        values = self.embed_batch([text], input_type=input_type)
        return values[0]

    def embed_supplier_text(self, supplier: dict[str, Any]) -> str:
        return str(self._transport.embed_supplier_text(supplier))
