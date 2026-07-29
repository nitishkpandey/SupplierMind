"""Policy tests for external AI data egress."""

from dataclasses import replace

import pytest

from app.platform.ai.policy import AIDataEgressDenied, AIPolicyEngine
from app.platform.ai.types import AIOperation, AIRequestContext, DataClassification


def _context(classification: DataClassification) -> AIRequestContext:
    return AIRequestContext(
        purpose="agent.parser",
        classification=classification,
        user_id="11111111-1111-1111-1111-111111111111",
        query_id="22222222-2222-2222-2222-222222222222",
    )


def test_policy_allows_public_and_internal_for_openai() -> None:
    engine = AIPolicyEngine(
        {
            "openai": frozenset(
                {DataClassification.public, DataClassification.internal}
            )
        }
    )

    assert engine.authorize(
        "openai",
        AIOperation.chat,
        _context(DataClassification.public),
    ).allowed
    assert engine.authorize(
        "openai",
        AIOperation.chat,
        _context(DataClassification.internal),
    ).allowed


@pytest.mark.parametrize(
    "classification",
    [DataClassification.confidential, DataClassification.restricted],
)
def test_policy_denies_sensitive_external_egress(
    classification: DataClassification,
) -> None:
    engine = AIPolicyEngine(
        {"openai": frozenset({DataClassification.public})}
    )

    with pytest.raises(AIDataEgressDenied, match=classification.value):
        engine.require_allowed(
            "openai",
            AIOperation.chat,
            _context(classification),
        )


def test_unclassified_context_is_restricted() -> None:
    context = AIRequestContext(purpose="unclassified")

    assert context.classification is DataClassification.restricted
    assert (
        replace(context, purpose="agent.compliance").classification
        is DataClassification.restricted
    )


def test_unknown_provider_is_denied() -> None:
    engine = AIPolicyEngine(
        {"openai": frozenset({DataClassification.public})}
    )

    with pytest.raises(AIDataEgressDenied, match="unknown-provider"):
        engine.require_allowed(
            "unknown-provider",
            AIOperation.chat,
            _context(DataClassification.public),
        )
