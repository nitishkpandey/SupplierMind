"""Provider egress policy for AI and embedding operations."""

from app.platform.ai.types import (
    AIOperation,
    AIPolicyDecision,
    AIRequestContext,
    DataClassification,
)


class AIDataEgressDenied(PermissionError):  # noqa: N818
    """Raised when a provider may not receive the classified request."""


class AIPolicyEngine:
    def __init__(
        self,
        allowed: dict[str, frozenset[DataClassification]],
    ) -> None:
        self._allowed = allowed

    def authorize(
        self,
        provider: str,
        operation: AIOperation,
        context: AIRequestContext,
    ) -> AIPolicyDecision:
        permitted = context.classification in self._allowed.get(
            provider,
            frozenset(),
        )
        return AIPolicyDecision(
            allowed=permitted,
            provider=provider,
            operation=operation,
            classification=context.classification,
            reason_code=(
                "allowed" if permitted else "classification_not_allowed"
            ),
        )

    def require_allowed(
        self,
        provider: str,
        operation: AIOperation,
        context: AIRequestContext,
    ) -> AIPolicyDecision:
        decision = self.authorize(provider, operation, context)
        if not decision.allowed:
            raise AIDataEgressDenied(
                f"{context.classification.value} data is not allowed for "
                f"{provider}:{operation.value}"
            )
        return decision
