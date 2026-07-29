"""Static and executable guards for every non-API AI entry point."""

from __future__ import annotations

import ast
import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.core.llm import OpenAIProvider
from app.platform.ai.context import current_ai_request_context
from app.platform.ai.gateway import AIGateway, EmbeddingGateway
from app.platform.ai.policy import AIPolicyEngine
from app.platform.ai.types import (
    AIOperation,
    DataClassification,
    ProviderUsage,
)
from app.platform.ai.usage import InMemoryAIUsageRecorder

BACKEND = Path(__file__).resolve().parents[2]
SCANNED_ROOTS = ("app", "experiments", "scripts")


def test_provider_sdks_are_confined_to_transports() -> None:
    allowed = {
        BACKEND / "app/core/llm.py",
        BACKEND / "app/core/embeddings.py",
    }
    violations = []
    for root in SCANNED_ROOTS:
        for path in (BACKEND / root).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if (
                "import openai" in text
                or "from openai" in text
                or "import voyageai" in text
                or "from voyageai" in text
            ) and path not in allowed:
                violations.append(path.relative_to(BACKEND).as_posix())

    assert violations == []


def test_provider_transports_are_only_constructed_by_factories() -> None:
    allowed = {
        BACKEND / "app/core/llm.py",
        BACKEND / "app/core/embeddings.py",
    }
    violations = []
    for root in SCANNED_ROOTS:
        for path in (BACKEND / root).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = getattr(node.func, "id", None)
                if (
                    name in {"OpenAIProvider", "EmbeddingClient"}
                    and path not in allowed
                ):
                    violations.append(path.relative_to(BACKEND).as_posix())

    assert violations == []


class _FakeOpenAITransport(OpenAIProvider):
    provider_name = "openai"
    model_name = "gpt-4o-mini-2024-07-18"
    total_cost_usd = 0.0

    def __init__(self) -> None:
        self.contexts = []
        self._usage_callback = None

    def set_usage_callback(self, callback) -> None:
        self._usage_callback = callback

    def complete(self, messages, **kwargs):
        self.contexts.append(current_ai_request_context())
        self._usage_callback(
            ProviderUsage(
                provider=self.provider_name,
                model=self.model_name,
                operation=AIOperation.chat,
                input_units=3,
                output_units=1,
                cost_usd=Decimal("0.00000105"),
                latency_ms=1,
            )
        )
        return "provider-ok"

    def complete_json(self, messages, **kwargs):
        self.contexts.append(current_ai_request_context())
        self._usage_callback(
            ProviderUsage(
                provider=self.provider_name,
                model=self.model_name,
                operation=AIOperation.chat_json,
                input_units=10,
                output_units=4,
                cost_usd=Decimal("0.00000390"),
                latency_ms=1,
            )
        )
        return json.dumps(
            {
                "suppliers": [
                    {
                        "name": "Acme",
                        "index": 1,
                        "reasoning": "match",
                    }
                ]
            }
        )


def _gateway(transport) -> AIGateway:
    allowed = frozenset(
        {DataClassification.public, DataClassification.internal}
    )
    return AIGateway(
        transport,
        AIPolicyEngine({"openai": allowed}),
        InMemoryAIUsageRecorder(),
    )


def test_p1_calls_through_gateway_with_internal_context() -> None:
    from experiments.paradigm1_singleprompt import run_paradigm1

    transport = _FakeOpenAITransport()

    result = run_paradigm1(
        "Find packaging suppliers",
        llm=_gateway(transport),
    )

    assert result.supplier_names == ["Acme"]
    assert transport.contexts[0].purpose == "evaluation.p1"
    assert (
        transport.contexts[0].classification
        is DataClassification.internal
    )


async def _fetch_one_supplier(_ids):
    return [
        {
            "id": "22222222-2222-2222-2222-222222222222",
            "name": "Acme",
            "city": "Berlin",
            "country": "Germany",
            "certifications": ["ISO 9001"],
            "capacity_value": 100,
            "capacity_unit": "units/month",
            "description": "Packaging supplier",
        }
    ]


def _p2_vector_store(observed):
    class FakeVectorStore:
        def search(self, query, top_k, **kwargs):
            observed.append(current_ai_request_context())
            return [
                SimpleNamespace(
                    supplier_id="22222222-2222-2222-2222-222222222222"
                )
            ]

    return FakeVectorStore()


async def test_p2_calls_retrieval_and_llm_inside_internal_context() -> None:
    from experiments.paradigm2_rag import run_paradigm2

    transport = _FakeOpenAITransport()
    retrieval_contexts = []

    result = await run_paradigm2(
        "Find packaging suppliers",
        llm=_gateway(transport),
        vector_store=_p2_vector_store(retrieval_contexts),
        fetch_suppliers=_fetch_one_supplier,
    )

    assert result.supplier_ids == [
        "22222222-2222-2222-2222-222222222222"
    ]
    assert retrieval_contexts[0].purpose == "evaluation.p2"
    assert transport.contexts[0].purpose == "evaluation.p2"
    assert (
        transport.contexts[0].classification
        is DataClassification.internal
    )


def test_provider_check_binds_public_smoke_context(monkeypatch) -> None:
    from app.core import llm as llm_module
    from scripts import provider_integration_check

    transport = _FakeOpenAITransport()
    gateway = _gateway(transport)
    monkeypatch.setattr(
        llm_module,
        "get_llm_client",
        lambda: gateway,
    )
    monkeypatch.setattr(
        provider_integration_check,
        "_find_usage_event",
        lambda correlation_id: next(
            event
            for event in gateway._recorder.snapshot()
            if event.correlation_id == correlation_id
        ),
    )

    provider_integration_check.check_provider()

    assert transport.contexts[0].purpose == "provider.smoke_check"
    assert (
        transport.contexts[0].classification
        is DataClassification.public
    )


def test_vector_sync_binds_internal_indexing_context(monkeypatch) -> None:
    from scripts import sync_active_supplier_vectors as sync_script

    observed = []
    supplier = SimpleNamespace(
        id="22222222-2222-2222-2222-222222222222",
        name="Acme",
        description="Metal parts",
        category="metals",
        country="Germany",
        city="Berlin",
        certifications=["ISO 9001"],
        source="manual",
    )

    class FakeEmbeddingTransport:
        provider_name = "voyage"
        model_name = "voyage-3-lite"

        def set_usage_callback(self, callback):
            self._usage_callback = callback

        def embed_batch(self, texts, input_type="document"):
            observed.append(current_ai_request_context())
            self._usage_callback(
                ProviderUsage(
                    provider=self.provider_name,
                    model=self.model_name,
                    operation=AIOperation.embedding,
                    input_units=5,
                    output_units=0,
                    cost_usd=None,
                    latency_ms=1,
                )
            )
            return [[0.0, 1.0]]

    embedding_gateway = EmbeddingGateway(
        FakeEmbeddingTransport(),
        AIPolicyEngine(
            {
                "voyage": frozenset(
                    {DataClassification.internal}
                )
            }
        ),
        InMemoryAIUsageRecorder(),
    )

    class FakeVectorStore:
        def add_suppliers(self, suppliers):
            embedding_gateway.embed_batch(
                [suppliers[0]["description"]],
                input_type="document",
            )
            return [suppliers[0]["id"]]

    session = MagicMock()
    session.__enter__.return_value = session
    session.__exit__.return_value = False
    monkeypatch.setattr(
        sync_script,
        "_missing_active_suppliers",
        lambda: [supplier],
    )
    monkeypatch.setattr(
        sync_script,
        "create_vector_store",
        lambda: FakeVectorStore(),
    )
    monkeypatch.setattr(
        sync_script,
        "SyncSessionLocal",
        lambda: session,
    )

    assert sync_script.sync_missing(1, 0, False) == 1
    assert observed[0].purpose == "supplier.indexing"
    assert observed[0].classification is DataClassification.internal
