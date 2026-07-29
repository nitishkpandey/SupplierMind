# AI Gateway and Usage Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route every LLM and embedding call through a privacy-aware policy gateway, enforce per-call and per-query budgets, and persist query/provider/model cost, latency, classification, and outcome metrics without storing sensitive content.

**Architecture:** Keep `app/core/llm.py` and `app/core/embeddings.py` as provider transports, and place policy, request context, budgets, and usage recording in a new `app/platform/ai/` package. Existing agent and vector-store interfaces remain compatible because `get_llm_client()` and `get_embedding_client()` return gateway objects with the same public methods. PostgreSQL stores authoritative usage events; the admin API and React dashboard aggregate those events.

**Tech Stack:** Python 3.11, FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, PostgreSQL, OpenAI transport, Voyage embedding transport, React 19, TypeScript, Recharts, Vitest, React Testing Library.

## Global Constraints

- Build for Mercanis as one organization with multiple internal roles.
- Keep the application a modular monolith.
- Retain FastAPI, React, PostgreSQL/PostGIS, Milvus, Redis, OpenAI, and Voyage.
- PostgreSQL owns authoritative usage and policy records.
- Every LLM and embedding call must pass through the gateway.
- Every request context declares purpose, classification, redaction/excerpt
  state, token/cost limits, and available request, job, query, user, and
  source-document identifiers.
- Unclassified requests are treated as `restricted` and denied external egress.
- `public` and `internal` are the only externally allowed classifications by default.
- Confidential or restricted processing requires an explicit provider-policy change.
- Prompts, document text, credentials, and API keys must never be written to usage events or logs.
- Persistent metrics must be query-, purpose/agent-, provider-, and
  model-addressable; process-local counters are runtime diagnostics only.
- Preserve the existing `complete()`, `complete_json()`, `embed_one()`, and `embed_batch()` call surfaces for injected test doubles.
- Preserve deterministic ranking and the frozen thesis evaluation corpus.
- Use sentence-style, human-readable commit subjects without AI attribution.

---

## Current-Code Reuse Map

| Existing code | Treatment | Reason |
|---|---|---|
| `app/core/llm.py` | Extend | Keep OpenAI retry, rate-limit, pinned-model, and cost-table behavior as the text-generation transport. |
| `app/core/embeddings.py` | Extend | Keep Voyage batching, caching, retry, dimension validation, and fail-fast benchmark behavior as the embedding transport. |
| `app/core/rate_limiter.py` | Reuse unchanged | Provider throttling remains below the gateway. |
| `app/agents/base.py` | Extend | Bind query/user/agent purpose to all agent calls without rewriting each prompt. |
| `app/services/supplier_extraction.py` | Extend | Override classification to `public` for public web-page extraction. |
| `app/core/vector_store.py` | Reuse public methods | It receives an embedding gateway from `get_embedding_client()` without changing Milvus/Chroma behavior. |
| `app/services/query_memory.py` | Reuse public methods | It receives an embedding gateway and inherits the parser's `internal` request context. |
| `app/api/v1/metrics.py` | Extend and split schemas | Preserve current operational metrics and add persistent AI usage aggregates. |
| `app/db/models.py` and Alembic | Extend | Add explicit usage events and indexes; do not store them in generic audit JSON. |
| `apps/frontend/src/pages/AdminMetricsPage.tsx` | Extend through a focused component | Keep the current operational dashboard and add an AI usage panel. |
| `apps/backend/tests/unit/test_llm_providers.py` | Update | Preserve direct provider transport tests while adding gateway factory expectations. |
| `scripts/verify_release.sh` | Reuse | New backend/frontend tests join the existing deterministic release gate. |

## File Structure

### New backend files

- `apps/backend/app/platform/__init__.py` — platform package marker.
- `apps/backend/app/platform/ai/__init__.py` — supported AI gateway exports.
- `apps/backend/app/platform/ai/types.py` — classification, operation, request context, policy decision, and usage value types.
- `apps/backend/app/platform/ai/context.py` — context-variable binding and safe state-to-context helpers.
- `apps/backend/app/platform/ai/policy.py` — provider/classification policy evaluation and denial errors.
- `apps/backend/app/platform/ai/budget.py` — per-call reservation and per-query spend ledger.
- `apps/backend/app/platform/ai/gateway.py` — text and embedding gateway implementations.
- `apps/backend/app/platform/ai/usage.py` — recorder protocol plus PostgreSQL and in-memory recorders.
- `apps/backend/app/db/repositories/ai_usage_repo.py` — usage-event persistence and aggregate queries.
- `apps/backend/app/schemas/metrics.py` — typed metrics response contracts.
- `apps/backend/tests/unit/test_ai_policy.py` — classification and policy tests.
- `apps/backend/tests/unit/test_ai_gateway.py` — delegation, denial, context, and budget tests.
- `apps/backend/tests/unit/test_ai_usage.py` — persistence and redaction-boundary tests.
- `apps/backend/tests/unit/test_ai_context_propagation.py` — agent, extraction, evaluation, and vector call context tests.
- `apps/backend/tests/unit/test_ai_gateway_boundaries.py` — source-level provider import guard.
- `apps/backend/tests/unit/test_query_log_privacy.py` — raw-query process-log
  exclusion regression.
- `apps/backend/alembic/versions/e2f4a9c1b7d8_ai_usage_events.py` — persistent usage-event schema.
- `docs/adr/ADR-003-ai-data-egress-and-usage.md` — policy and gateway architectural decision.

### New frontend files

- `apps/frontend/src/features/admin/AIUsagePanel.tsx` — provider/model usage and budget display.
- `apps/frontend/src/features/admin/AIUsagePanel.test.tsx` — rendering and unknown-cost tests.
- `apps/frontend/vitest.config.ts` — component-test environment.
- `apps/frontend/src/test/setup.ts` — DOM assertion setup.

### Existing files modified

- `apps/backend/app/core/config.py`
- `apps/backend/app/core/llm.py`
- `apps/backend/app/core/embeddings.py`
- `apps/backend/app/agents/base.py`
- `apps/backend/app/agents/orchestrator.py`
- `apps/backend/app/api/v1/queries.py`
- `apps/backend/app/services/supplier_extraction.py`
- `apps/backend/app/services/query_memory.py`
- `apps/backend/app/evaluation/baselines.py`
- `apps/backend/app/evaluation/runner.py`
- `apps/backend/experiments/paradigm1_singleprompt.py`
- `apps/backend/experiments/paradigm2_rag.py`
- `apps/backend/scripts/provider_integration_check.py`
- `apps/backend/app/db/models.py`
- `apps/backend/alembic/env.py`
- `apps/backend/app/api/v1/metrics.py`
- `apps/backend/tests/unit/test_llm_providers.py`
- `apps/backend/tests/unit/test_metrics.py`
- `apps/frontend/src/services/api.ts`
- `apps/frontend/src/pages/AdminMetricsPage.tsx`
- `apps/frontend/package.json`
- `apps/frontend/package-lock.json`
- `.env.example`
- `ARCHITECTURE.md`
- `README.md`
- `apps/backend/openapi.json`

---

### Task 1: Define AI classifications and provider policy

**Files:**
- Create: `apps/backend/app/platform/__init__.py`
- Create: `apps/backend/app/platform/ai/__init__.py`
- Create: `apps/backend/app/platform/ai/types.py`
- Create: `apps/backend/app/platform/ai/policy.py`
- Modify: `apps/backend/app/core/config.py:55-66`
- Modify: `.env.example:12-22`
- Create: `apps/backend/tests/unit/test_ai_policy.py`

**Interfaces:**
- Produces: `DataClassification`, `AIOperation`, `AIOutcome`, `AIRequestContext`, `AIPolicyDecision`, `AIPolicyEngine`, and `AIDataEgressDenied`.
- Produces: `settings.ai_external_allowed_classifications -> frozenset[DataClassification]`.
- Consumes: existing `Settings` environment loading.

- [ ] **Step 1: Write policy tests**

```python
from dataclasses import replace

import pytest

from app.platform.ai.policy import AIDataEgressDenied, AIPolicyEngine
from app.platform.ai.types import (
    AIOperation,
    AIRequestContext,
    DataClassification,
)


def _context(classification: DataClassification) -> AIRequestContext:
    return AIRequestContext(
        purpose="agent.parser",
        classification=classification,
        user_id="11111111-1111-1111-1111-111111111111",
        query_id="22222222-2222-2222-2222-222222222222",
    )


def test_policy_allows_public_and_internal_for_openai():
    engine = AIPolicyEngine(
        {"openai": frozenset({DataClassification.public, DataClassification.internal})}
    )
    assert engine.authorize("openai", AIOperation.chat, _context(DataClassification.public)).allowed
    assert engine.authorize("openai", AIOperation.chat, _context(DataClassification.internal)).allowed


@pytest.mark.parametrize(
    "classification",
    [DataClassification.confidential, DataClassification.restricted],
)
def test_policy_denies_sensitive_external_egress(classification):
    engine = AIPolicyEngine({"openai": frozenset({DataClassification.public})})
    with pytest.raises(AIDataEgressDenied, match=classification.value):
        engine.require_allowed("openai", AIOperation.chat, _context(classification))


def test_unclassified_context_is_restricted():
    context = AIRequestContext(purpose="unclassified")
    assert context.classification is DataClassification.restricted
    assert replace(context, purpose="agent.compliance").classification is DataClassification.restricted
```

- [ ] **Step 2: Run the tests and confirm the missing-module failure**

Run:

```bash
cd apps/backend
uv run --no-sync pytest tests/unit/test_ai_policy.py -v
```

Expected: collection fails with `ModuleNotFoundError: No module named 'app.platform'`.

- [ ] **Step 3: Add the classification and policy value types**

```python
# app/platform/ai/types.py
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from decimal import Decimal


class DataClassification(StrEnum):
    public = "public"
    internal = "internal"
    confidential = "confidential"
    restricted = "restricted"


class AIOperation(StrEnum):
    chat = "chat"
    chat_json = "chat_json"
    embedding = "embedding"


class AIOutcome(StrEnum):
    success = "success"
    error = "error"
    denied = "denied"
    budget_exceeded = "budget_exceeded"


@dataclass(frozen=True, slots=True)
class AIRequestContext:
    purpose: str
    classification: DataClassification = DataClassification.restricted
    user_id: str | None = None
    query_id: str | None = None
    job_id: str | None = None
    source_document_id: str | None = None
    correlation_id: str | None = None
    redaction_applied: bool = False
    excerpted: bool = False
    max_call_tokens: int = 32_000
    max_call_cost_usd: Decimal = Decimal("0.10")


@dataclass(frozen=True, slots=True)
class AIPolicyDecision:
    allowed: bool
    provider: str
    operation: AIOperation
    classification: DataClassification
    reason_code: str
```

```python
# app/platform/ai/policy.py
from app.platform.ai.types import (
    AIOperation,
    AIPolicyDecision,
    AIRequestContext,
    DataClassification,
)


class AIDataEgressDenied(PermissionError):
    pass


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
        permitted = context.classification in self._allowed.get(provider, frozenset())
        return AIPolicyDecision(
            allowed=permitted,
            provider=provider,
            operation=operation,
            classification=context.classification,
            reason_code="allowed" if permitted else "classification_not_allowed",
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
```

- [ ] **Step 4: Add exact settings and environment defaults**

Add to `Settings`:

```python
AI_EXTERNAL_ALLOWED_CLASSIFICATIONS: str = "public,internal"
AI_MAX_CALL_TOKENS: int = 32_000
AI_MAX_CALL_COST_USD: float = 0.10
AI_MAX_QUERY_COST_USD: float = 0.50

@property
def ai_external_allowed_classifications(self) -> frozenset["DataClassification"]:
    from app.platform.ai.types import DataClassification

    values = {
        DataClassification(part.strip())
        for part in self.AI_EXTERNAL_ALLOWED_CLASSIFICATIONS.split(",")
        if part.strip()
    }
    return frozenset(values)
```

Add to `.env.example`:

```dotenv
AI_EXTERNAL_ALLOWED_CLASSIFICATIONS=public,internal
AI_MAX_CALL_TOKENS=32000
AI_MAX_CALL_COST_USD=0.10
AI_MAX_QUERY_COST_USD=0.50
```

- [ ] **Step 5: Export the supported policy API**

`app/platform/ai/__init__.py` must export only:

```python
from app.platform.ai.policy import AIDataEgressDenied, AIPolicyEngine
from app.platform.ai.types import AIOperation, AIRequestContext, DataClassification

__all__ = [
    "AIDataEgressDenied",
    "AIOperation",
    "AIPolicyEngine",
    "AIRequestContext",
    "DataClassification",
]
```

- [ ] **Step 6: Run focused tests and static checks**

Run:

```bash
cd apps/backend
uv run --no-sync pytest tests/unit/test_ai_policy.py -v
uv run --no-sync ruff check app/platform app/core/config.py tests/unit/test_ai_policy.py
uv run --no-sync mypy app/platform app/core/config.py
```

Expected: all commands exit `0`.

- [ ] **Step 7: Commit**

```bash
git add .env.example apps/backend/app/platform apps/backend/app/core/config.py apps/backend/tests/unit/test_ai_policy.py
git commit -m "Define AI data classification policy"
```

---

### Task 2: Bind request context and enforce the gateway boundary

**Files:**
- Create: `apps/backend/app/platform/ai/context.py`
- Create: `apps/backend/app/platform/ai/gateway.py`
- Modify: `apps/backend/app/platform/ai/__init__.py`
- Modify: `apps/backend/app/core/llm.py:117-147,292-327`
- Modify: `apps/backend/app/core/embeddings.py:76-103,291-296`
- Modify: `apps/backend/app/services/query_memory.py:39,176-179`
- Create: `apps/backend/tests/unit/test_ai_gateway.py`
- Modify test: `apps/backend/tests/unit/test_llm_providers.py:40-80`

**Interfaces:**
- Consumes: `AIPolicyEngine.require_allowed()`, existing `OpenAIProvider`, and existing `EmbeddingClient`.
- Produces: `ai_request_scope(context)`, `current_ai_request_context()`,
  `AIGateway`, and `EmbeddingGateway`.
- Produces: structural `EmbeddingService` protocol for gateway and injected
  fake compatibility.
- Preserves: `complete()`, `complete_json()`, `embed_one()`, `embed_batch()`, `total_cost_usd`, and `provider_name`.
- Produces: read-only `transport` and `model_name` properties for health and
  provider-verification code; callers never invoke the transport directly.

- [ ] **Step 1: Write context and gateway denial tests**

```python
from unittest.mock import MagicMock

import pytest

from app.platform.ai.context import ai_request_scope, current_ai_request_context
from app.platform.ai.gateway import AIGateway, EmbeddingGateway
from app.platform.ai.policy import AIDataEgressDenied, AIPolicyEngine
from app.platform.ai.types import AIRequestContext, DataClassification


def _policy():
    return AIPolicyEngine(
        {
            "openai": frozenset({DataClassification.public, DataClassification.internal}),
            "voyage": frozenset({DataClassification.public, DataClassification.internal}),
        }
    )


def test_unbound_gateway_call_is_denied_before_transport():
    transport = MagicMock(provider_name="openai", total_cost_usd=0.0)
    gateway = AIGateway(transport, _policy())
    with pytest.raises(AIDataEgressDenied):
        gateway.complete([{"role": "user", "content": "secret"}])
    transport.complete.assert_not_called()


def test_internal_context_delegates_and_resets():
    transport = MagicMock(provider_name="openai", total_cost_usd=0.0)
    transport.complete.return_value = "ok"
    gateway = AIGateway(transport, _policy())
    original = current_ai_request_context()
    context = AIRequestContext(
        purpose="agent.parser",
        classification=DataClassification.internal,
        query_id="query-1",
    )
    with ai_request_scope(context):
        assert gateway.complete([{"role": "user", "content": "supplier query"}]) == "ok"
        assert current_ai_request_context() == context
    assert current_ai_request_context() == original


def test_embedding_gateway_denies_restricted_data():
    transport = MagicMock(provider_name="voyage")
    gateway = EmbeddingGateway(transport, _policy())
    with pytest.raises(AIDataEgressDenied):
        gateway.embed_one("contract text", input_type="document")
    transport.embed_one.assert_not_called()
```

- [ ] **Step 2: Run the focused test and confirm missing gateway symbols**

Run:

```bash
cd apps/backend
uv run --no-sync pytest tests/unit/test_ai_gateway.py -v
```

Expected: collection fails because `app.platform.ai.context` and
`app.platform.ai.gateway` do not exist.

- [ ] **Step 3: Implement context binding with a restricted default**

```python
# app/platform/ai/context.py
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import replace
from collections.abc import Iterator

from app.platform.ai.types import AIRequestContext


_UNCLASSIFIED = AIRequestContext(purpose="unclassified")
_CURRENT_AI_CONTEXT: ContextVar[AIRequestContext] = ContextVar(
    "suppliermind_ai_request_context",
    default=_UNCLASSIFIED,
)


def current_ai_request_context() -> AIRequestContext:
    return _CURRENT_AI_CONTEXT.get()


@contextmanager
def ai_request_scope(context: AIRequestContext) -> Iterator[AIRequestContext]:
    token = _CURRENT_AI_CONTEXT.set(context)
    try:
        yield context
    finally:
        _CURRENT_AI_CONTEXT.reset(token)


def derive_ai_request_context(**changes: object) -> AIRequestContext:
    return replace(current_ai_request_context(), **changes)
```

- [ ] **Step 4: Implement text and embedding gateways**

```python
# app/platform/ai/gateway.py
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
        return self._transport.provider_name

    @property
    def model_name(self) -> str:
        return self._transport.model_name

    @property
    def total_cost_usd(self) -> float:
        return float(getattr(self._transport, "total_cost_usd", 0.0))

    @property
    def last_provider_used(self) -> str:
        return self._transport.provider_name

    def complete(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        self._policy.require_allowed(
            self._transport.provider_name,
            AIOperation.chat,
            current_ai_request_context(),
        )
        return self._transport.complete(messages, **kwargs)

    def complete_json(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        self._policy.require_allowed(
            self._transport.provider_name,
            AIOperation.chat_json,
            current_ai_request_context(),
        )
        return self._transport.complete_json(messages, **kwargs)


class EmbeddingGateway:
    def __init__(self, transport: Any, policy: AIPolicyEngine) -> None:
        self._transport = transport
        self._policy = policy
        self.provider_name = transport.provider_name

    @property
    def transport(self) -> Any:
        return self._transport

    @property
    def model_name(self) -> str:
        return self._transport.model_name

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

    def embed_one(self, text: str, input_type: str = "document") -> list[float]:
        values = self.embed_batch([text], input_type=input_type)
        return values[0]

    def embed_supplier_text(self, supplier: dict) -> str:
        return self._transport.embed_supplier_text(supplier)
```

Add `provider_name = "voyage"` and `model_name = EMBEDDING_MODEL` to
`EmbeddingClient`. Add a read-only `model_name` property to `OpenAIProvider`
that returns its resolved default model.

- [ ] **Step 5: Make existing factories return gateways**

In `app/core/llm.py`, keep `OpenAIProvider` as the transport and change:

```python
LLMClient = AIGateway


def build_llm_client() -> AIGateway:
    if settings.LLM_PROVIDER != "openai":
        raise ValueError(
            f"Unsupported LLM_PROVIDER={settings.LLM_PROVIDER!r}. "
            "Only 'openai' is supported in the single-provider deployment."
        )
    policy = AIPolicyEngine(
        {"openai": settings.ai_external_allowed_classifications}
    )
    return AIGateway(OpenAIProvider(), policy)
```

In `app/core/embeddings.py`, retain `EmbeddingClient` as the transport and
change the cached factory:

```python
@lru_cache(maxsize=1)
def get_embedding_client() -> EmbeddingService:
    policy = AIPolicyEngine(
        {"voyage": settings.ai_external_allowed_classifications}
    )
    return EmbeddingGateway(EmbeddingClient(), policy)
```

Define `EmbeddingService` as a `Protocol` containing `embed_batch()`,
`embed_one()`, and `embed_supplier_text()`. Change the `QueryMemoryService`
constructor annotation from `EmbeddingClient | None` to
`EmbeddingService | None`; the existing deterministic fake remains valid by
structural typing.

- [ ] **Step 6: Update provider factory tests**

Change the provider-selection assertion to:

```python
client = build_llm_client()
assert isinstance(client, AIGateway)
assert isinstance(client.transport, OpenAIProvider)
assert client.provider_name == "openai"
assert not hasattr(client.transport, "_fallback")
```

Keep direct `OpenAIProvider` retry, auth, model, stop, and cost tests unchanged.

- [ ] **Step 7: Run gateway and provider tests**

Run:

```bash
cd apps/backend
uv run --no-sync pytest \
  tests/unit/test_ai_policy.py \
  tests/unit/test_ai_gateway.py \
  tests/unit/test_llm_providers.py \
  tests/unit/test_cost_table.py -v
uv run --no-sync ruff check app/platform app/core/llm.py app/core/embeddings.py tests/unit/test_ai_gateway.py tests/unit/test_llm_providers.py
uv run --no-sync mypy app/platform app/core/llm.py app/core/embeddings.py
```

Expected: all commands exit `0`.

- [ ] **Step 8: Commit**

```bash
git add apps/backend/app/platform/ai apps/backend/app/core/llm.py apps/backend/app/core/embeddings.py apps/backend/app/services/query_memory.py apps/backend/tests/unit/test_ai_gateway.py apps/backend/tests/unit/test_llm_providers.py
git commit -m "Route model access through the AI gateway"
```

---

### Task 3: Persist privacy-safe AI usage events

**Files:**
- Modify: `apps/backend/app/db/models.py:18-35,345-429`
- Create: `apps/backend/alembic/versions/e2f4a9c1b7d8_ai_usage_events.py`
- Modify: `apps/backend/alembic/env.py:40-55`
- Create: `apps/backend/app/db/repositories/ai_usage_repo.py`
- Create: `apps/backend/app/platform/ai/usage.py`
- Modify: `apps/backend/app/platform/ai/types.py`
- Create: `apps/backend/tests/unit/test_ai_usage.py`

**Interfaces:**
- Produces: `AIUsageMeasurement`, `AIUsageRecorder`, `InMemoryAIUsageRecorder`, `DatabaseAIUsageRecorder`.
- Produces:
  `AIUsageRepository.record_sync(session, measurement)`.
- Produces table: `ai_usage_events`.
- Does not consume or accept prompt/document content.

- [ ] **Step 1: Write privacy and persistence tests**

```python
from decimal import Decimal
from unittest.mock import MagicMock

from app.platform.ai.types import (
    AIOperation,
    AIOutcome,
    AIUsageMeasurement,
    DataClassification,
)
from app.db.repositories.ai_usage_repo import AIUsageRepository


def _measurement() -> AIUsageMeasurement:
    return AIUsageMeasurement(
        purpose="agent.parser",
        classification=DataClassification.internal,
        operation=AIOperation.chat,
        provider="openai",
        model="gpt-4o-mini-2024-07-18",
        input_units=120,
        output_units=30,
        cost_usd=Decimal("0.000036"),
        latency_ms=240,
        outcome=AIOutcome.success,
        query_id="22222222-2222-2222-2222-222222222222",
        user_id="11111111-1111-1111-1111-111111111111",
        job_id="33333333-3333-3333-3333-333333333333",
        correlation_id="request-1",
        redaction_applied=True,
        excerpted=True,
    )


def test_usage_measurement_has_no_content_field():
    names = set(AIUsageMeasurement.__dataclass_fields__)
    assert names.isdisjoint({"prompt", "messages", "content", "document_text", "response"})


def test_repository_records_safe_fields_and_commits():
    session = MagicMock()
    AIUsageRepository.record_sync(session, _measurement())
    event = session.add.call_args.args[0]
    assert event.provider == "openai"
    assert event.classification == "internal"
    assert event.cost_usd == Decimal("0.000036")
    session.commit.assert_called_once_with()
```

- [ ] **Step 2: Run the tests and confirm missing symbols**

Run:

```bash
cd apps/backend
uv run --no-sync pytest tests/unit/test_ai_usage.py -v
```

Expected: collection fails because `AIUsageMeasurement` and
`AIUsageRepository` do not exist.

- [ ] **Step 3: Add the usage measurement type**

```python
@dataclass(frozen=True, slots=True)
class AIUsageMeasurement:
    purpose: str
    classification: DataClassification
    operation: AIOperation
    provider: str
    model: str
    input_units: int
    output_units: int
    cost_usd: Decimal | None
    latency_ms: int
    outcome: AIOutcome
    query_id: str | None = None
    user_id: str | None = None
    job_id: str | None = None
    source_document_id: str | None = None
    correlation_id: str | None = None
    redaction_applied: bool = False
    excerpted: bool = False
    error_code: str | None = None
```

- [ ] **Step 4: Add the SQLAlchemy model**

Add `from decimal import Decimal` and add `Boolean` and `Numeric` to the
SQLAlchemy imports, then define:

```python
class AIUsageEvent(Base):
    __tablename__ = "ai_usage_events"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    query_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("queries.id"), nullable=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    correlation_id: Mapped[str | None] = mapped_column(String(100))
    purpose: Mapped[str] = mapped_column(String(100), nullable=False)
    classification: Mapped[str] = mapped_column(String(20), nullable=False)
    operation: Mapped[str] = mapped_column(String(30), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    input_units: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_units: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(14, 8))
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[str] = mapped_column(String(30), nullable=False)
    redaction_applied: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    excerpted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    error_code: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_ai_usage_events_created_at", "created_at"),
        Index("ix_ai_usage_events_query_id", "query_id"),
        Index("ix_ai_usage_events_job_id", "job_id"),
        Index("ix_ai_usage_events_provider_model", "provider", "model"),
        CheckConstraint("input_units >= 0", name="ai_usage_input_units_nonnegative"),
        CheckConstraint("output_units >= 0", name="ai_usage_output_units_nonnegative"),
        CheckConstraint("latency_ms >= 0", name="ai_usage_latency_nonnegative"),
        CheckConstraint(
            "classification IN ('public','internal','confidential','restricted')",
            name="ai_usage_classification_valid",
        ),
    )
```

- [ ] **Step 5: Add the migration and fix the Alembic whitelist**

The migration revision must be:

```python
revision = "e2f4a9c1b7d8"
down_revision = "d7c30a5e9f12"
```

Its `upgrade()` creates the columns, foreign keys, check constraints, and four
indexes defined by `AIUsageEvent`; `downgrade()` drops indexes and then the
table. `job_id` and `source_document_id` intentionally have no foreign keys in
this migration because `background_jobs` and `supplier_documents` are created
by later independently reversible slices. Their UUID values remain
correlation metadata until those tables exist.

Replace `SUPPLIERMIND_TABLES` with:

```python
SUPPLIERMIND_TABLES = {
    "suppliers",
    "user_supplier_saves",
    "users",
    "queries",
    "query_results",
    "audit_logs",
    "pending_clarifications",
    "ai_usage_events",
}
```

- [ ] **Step 6: Implement repository and recorders**

```python
# app/db/repositories/ai_usage_repo.py
import uuid

from sqlalchemy.orm import Session

from app.db.models import AIUsageEvent
from app.platform.ai.types import AIUsageMeasurement


class AIUsageRepository:
    @staticmethod
    def record_sync(session: Session, measurement: AIUsageMeasurement) -> None:
        event = AIUsageEvent(
            query_id=uuid.UUID(measurement.query_id) if measurement.query_id else None,
            user_id=uuid.UUID(measurement.user_id) if measurement.user_id else None,
            job_id=uuid.UUID(measurement.job_id) if measurement.job_id else None,
            source_document_id=(
                uuid.UUID(measurement.source_document_id)
                if measurement.source_document_id
                else None
            ),
            correlation_id=measurement.correlation_id,
            purpose=measurement.purpose,
            classification=measurement.classification.value,
            operation=measurement.operation.value,
            provider=measurement.provider,
            model=measurement.model,
            input_units=measurement.input_units,
            output_units=measurement.output_units,
            cost_usd=measurement.cost_usd,
            latency_ms=measurement.latency_ms,
            outcome=measurement.outcome.value,
            redaction_applied=measurement.redaction_applied,
            excerpted=measurement.excerpted,
            error_code=measurement.error_code,
        )
        session.add(event)
        session.commit()
```

`DatabaseAIUsageRecorder.record()` opens `SyncSessionLocal`, calls the
repository, and catches `SQLAlchemyError`. It logs only provider, operation,
outcome, correlation ID, and exception type. `InMemoryAIUsageRecorder` stores
measurements in a lock-protected list for unit tests.

- [ ] **Step 7: Run model, repository, and migration checks**

Run:

```bash
cd apps/backend
uv run --no-sync pytest tests/unit/test_ai_usage.py -v
uv run --no-sync ruff check app/db/models.py app/db/repositories/ai_usage_repo.py app/platform/ai/usage.py tests/unit/test_ai_usage.py alembic/versions/e2f4a9c1b7d8_ai_usage_events.py
uv run --no-sync mypy app/db/models.py app/db/repositories/ai_usage_repo.py app/platform/ai/usage.py
uv run --no-sync alembic upgrade head
uv run --no-sync alembic downgrade d7c30a5e9f12
uv run --no-sync alembic upgrade head
```

Expected: tests and static checks exit `0`; the migration upgrades,
downgrades, and upgrades without an error.

- [ ] **Step 8: Commit**

```bash
git add apps/backend/app/db apps/backend/app/platform/ai apps/backend/alembic
git commit -m "Persist privacy-safe AI usage events"
```

---

### Task 4: Record provider usage without storing content

**Files:**
- Modify: `apps/backend/app/core/llm.py:149-289`
- Modify: `apps/backend/app/core/embeddings.py:76-234`
- Modify: `apps/backend/app/platform/ai/gateway.py`
- Modify: `apps/backend/app/platform/ai/usage.py`
- Modify test: `apps/backend/tests/unit/test_llm_providers.py`
- Modify test: `apps/backend/tests/unit/test_ai_gateway.py`
- Modify test: `apps/backend/tests/unit/test_ai_usage.py`

**Interfaces:**
- Consumes: `AIUsageRecorder.record(AIUsageMeasurement)`.
- Produces: one measurement for every successful, denied, or failed external
  operation.
- Produces: nullable embedding cost when no configured rate is available,
  rather than silently recording zero.
- Changes gateway constructors to
  `AIGateway(transport, policy, recorder)` and
  `EmbeddingGateway(transport, policy, recorder)`.
- Produces transport method
  `set_usage_callback(Callable[[ProviderUsage], None] | None) -> None`; only
  gateways register this callback in application code.

- [ ] **Step 1: Write provider usage callback tests**

Add to `test_llm_providers.py`:

```python
def test_openai_provider_emits_usage_without_content():
    emitted = []
    fake_completion = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="answer"))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )
    fake_sdk = MagicMock()
    fake_sdk.chat.completions.create.return_value = fake_completion
    with patch.object(llm_mod.settings, "OPENAI_API_KEY", "sk-test"), \
         patch("openai.OpenAI", MagicMock(return_value=fake_sdk)):
        provider = OpenAIProvider(usage_callback=emitted.append)
        assert provider.complete([{"role": "user", "content": "sensitive input"}]) == "answer"
    assert len(emitted) == 1
    usage = emitted[0]
    assert usage.input_units == 10
    assert usage.output_units == 5
    assert usage.cost_usd > 0
    assert "sensitive input" not in repr(usage)
    assert "answer" not in repr(usage)
```

Add gateway tests asserting:

- a successful call creates one `AIOutcome.success` measurement;
- a denied call creates one `AIOutcome.denied` measurement with zero units;
- a provider exception creates one `AIOutcome.error` measurement with the
  exception class name as `error_code`;
- no measurement dataclass exposes messages or response content.

- [ ] **Step 2: Run focused tests and confirm callback failure**

Run:

```bash
cd apps/backend
uv run --no-sync pytest tests/unit/test_llm_providers.py tests/unit/test_ai_gateway.py tests/unit/test_ai_usage.py -v
```

Expected: failure because `OpenAIProvider.__init__()` does not accept
`usage_callback`.

- [ ] **Step 3: Add provider usage value type**

```python
@dataclass(frozen=True, slots=True)
class ProviderUsage:
    provider: str
    model: str
    operation: AIOperation
    input_units: int
    output_units: int
    cost_usd: Decimal | None
    latency_ms: int
```

- [ ] **Step 4: Instrument OpenAI transport**

Add `usage_callback: Callable[[ProviderUsage], None] | None = None` to
`OpenAIProvider.__init__()` and store it behind
`set_usage_callback()`. Measure elapsed time from rate-limit acquisition
through the SDK response. Change `_UsageTracking._track()` to return a
`ProviderUsage`, then invoke the callback after total-cost bookkeeping. The
callback value must contain only
provider/model/operation/unit/cost/latency fields.

`complete()` emits `AIOperation.chat`; `complete_json()` emits
`AIOperation.chat_json`.

- [ ] **Step 5: Instrument Voyage transport**

Add `usage_callback` and `set_usage_callback()` to
`EmbeddingClient`. Change `_call_api()` to return `(vectors, total_tokens)`
where:

```python
total_tokens = int(getattr(result, "total_tokens", 0) or 0)
```

For each cache-miss API batch, emit:

```python
ProviderUsage(
    provider="voyage",
    model=EMBEDDING_MODEL,
    operation=AIOperation.embedding,
    input_units=total_tokens,
    output_units=0,
    cost_usd=None,
    latency_ms=elapsed_ms,
)
```

Cache hits emit no external-provider event.

- [ ] **Step 6: Convert provider usage to persistent measurements in gateways**

Each gateway constructor accepts an `AIUsageRecorder`, stores it, and calls
`transport.set_usage_callback(self._record_provider_usage)`. The gateway owns
a `ContextVar[_ActiveAICall | None]`; `_ActiveAICall` contains the immutable
request context, start time, and operation. Immediately before transport
invocation, set the active call and always reset its context token in
`finally`.

`_record_provider_usage()` must read `_ActiveAICall`, reject a callback without
an active call as a transport contract error, combine the captured request
context with `ProviderUsage`, and call the configured recorder. It copies
`job_id`, `source_document_id`, `redaction_applied`, and `excerpted`, but never
receives prompts or responses. Gateway exception and policy-denial paths
create their own zero-unit measurements using `model_name`; their latency is
measured at the gateway boundary and the exception path records only the
exception class name.

Factories use one process-level `DatabaseAIUsageRecorder()` in application
code and tests inject `InMemoryAIUsageRecorder()`. Update the Task 2 gateway
tests to pass an in-memory recorder to both constructors.

- [ ] **Step 7: Run focused tests and static checks**

Run:

```bash
cd apps/backend
uv run --no-sync pytest \
  tests/unit/test_llm_providers.py \
  tests/unit/test_ai_gateway.py \
  tests/unit/test_ai_usage.py \
  tests/unit/test_cost_table.py -v
uv run --no-sync ruff check app/core/llm.py app/core/embeddings.py app/platform/ai tests/unit/test_llm_providers.py tests/unit/test_ai_gateway.py tests/unit/test_ai_usage.py
uv run --no-sync mypy app/core/llm.py app/core/embeddings.py app/platform/ai
```

Expected: all commands exit `0`.

- [ ] **Step 8: Commit**

```bash
git add apps/backend/app/core/llm.py apps/backend/app/core/embeddings.py apps/backend/app/platform/ai apps/backend/tests/unit/test_llm_providers.py apps/backend/tests/unit/test_ai_gateway.py apps/backend/tests/unit/test_ai_usage.py
git commit -m "Measure every external AI provider call"
```

---

### Task 5: Enforce per-call and per-query budgets

**Files:**
- Create: `apps/backend/app/platform/ai/budget.py`
- Modify: `apps/backend/app/platform/ai/types.py`
- Modify: `apps/backend/app/platform/ai/context.py`
- Modify: `apps/backend/app/platform/ai/gateway.py`
- Modify: `apps/backend/app/core/llm.py`
- Modify: `apps/backend/app/core/embeddings.py`
- Modify: `apps/backend/app/core/config.py`
- Modify: `apps/backend/app/db/repositories/ai_usage_repo.py`
- Modify test: `apps/backend/tests/unit/test_ai_gateway.py`
- Modify test: `apps/backend/tests/unit/test_cost_table.py`
- Modify test: `apps/backend/tests/unit/test_ai_usage.py`

**Interfaces:**
- Produces: `AIBudgetLedger`, `AIBudgetExceeded`, `BudgetReservation`.
- Consumes: existing `estimate_message_tokens()` and
  `estimate_call_cost_usd()`.
- Preserves: actual provider cost reconciliation and deterministic budget
  failure before provider invocation.
- Enforces: the configured token ceiling for both text and embedding calls.
- Produces:
  `AIUsageRepository.known_query_cost_sync(session, query_id) -> Decimal`,
  which sums persisted non-null costs for a resumed query.

- [ ] **Step 1: Write reservation and denial tests**

```python
from decimal import Decimal

from app.platform.ai.budget import AIBudgetExceeded, AIBudgetLedger


def test_budget_reservation_blocks_before_provider_call():
    ledger = AIBudgetLedger(limit_usd=Decimal("0.000001"))
    with pytest.raises(AIBudgetExceeded):
        ledger.reserve(Decimal("0.01"))
    assert ledger.spent_usd == Decimal("0")
    assert ledger.reserved_usd == Decimal("0")


def test_budget_settlement_replaces_reservation_with_actual_cost():
    ledger = AIBudgetLedger(limit_usd=Decimal("1.00"))
    reservation = ledger.reserve(Decimal("0.10"))
    ledger.settle(reservation, Decimal("0.025"))
    assert ledger.reserved_usd == Decimal("0")
    assert ledger.spent_usd == Decimal("0.025")


def test_gateway_budget_failure_never_calls_transport():
    transport = MagicMock(provider_name="openai", total_cost_usd=0.0)
    context = AIRequestContext(
        purpose="agent.parser",
        classification=DataClassification.internal,
        budget=AIBudgetLedger(limit_usd=Decimal("0.000001")),
        max_call_tokens=32_000,
        max_call_cost_usd=Decimal("0.10"),
    )
    gateway = AIGateway(transport, _policy(), InMemoryAIUsageRecorder())
    with ai_request_scope(context), pytest.raises(AIBudgetExceeded):
        gateway.complete(
            [{"role": "user", "content": "supplier query"}],
            model="gpt-4o-mini-2024-07-18",
            max_tokens=2048,
        )
    transport.complete.assert_not_called()
```

- [ ] **Step 2: Run the tests and confirm missing budget symbols**

Run:

```bash
cd apps/backend
uv run --no-sync pytest tests/unit/test_ai_gateway.py tests/unit/test_cost_table.py -v
```

Expected: collection fails because `app.platform.ai.budget` does not exist.

- [ ] **Step 3: Implement a lock-protected budget ledger**

```python
# app/platform/ai/budget.py
from dataclasses import dataclass
from decimal import Decimal
from threading import Lock
from uuid import UUID, uuid4


class AIBudgetExceeded(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class BudgetReservation:
    id: UUID
    amount_usd: Decimal


class AIBudgetLedger:
    def __init__(
        self,
        limit_usd: Decimal,
        initial_spent_usd: Decimal = Decimal("0"),
    ) -> None:
        self.limit_usd = limit_usd
        self.spent_usd = max(initial_spent_usd, Decimal("0"))
        self.reserved_usd = Decimal("0")
        self._reservations: dict[UUID, Decimal] = {}
        self._lock = Lock()

    def reserve(self, amount_usd: Decimal) -> BudgetReservation:
        amount = max(amount_usd, Decimal("0"))
        with self._lock:
            projected = self.spent_usd + self.reserved_usd + amount
            if projected > self.limit_usd:
                raise AIBudgetExceeded(
                    f"AI budget exceeded: projected ${projected} > ${self.limit_usd}"
                )
            reservation = BudgetReservation(uuid4(), amount)
            self._reservations[reservation.id] = amount
            self.reserved_usd += amount
            return reservation

    def settle(self, reservation: BudgetReservation, actual_usd: Decimal) -> None:
        with self._lock:
            held = self._reservations.pop(reservation.id)
            self.reserved_usd -= held
            self.spent_usd += max(actual_usd, Decimal("0"))

    def release(self, reservation: BudgetReservation) -> None:
        with self._lock:
            held = self._reservations.pop(reservation.id, Decimal("0"))
            self.reserved_usd -= held
```

- [ ] **Step 4: Carry the shared ledger in request context**

Add:

```python
budget: AIBudgetLedger | None = None
```

to `AIRequestContext`. Add:

```python
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
```

- [ ] **Step 5: Enforce token limits and reconcile the exact reservation**

Before a text transport call, calculate:

```python
estimated_tokens = estimate_message_tokens(messages, max_tokens)
estimated_cost = Decimal(
    str(estimate_call_cost_usd(resolved_model, estimated_tokens - max_tokens, max_tokens))
)
```

Reject when `estimated_tokens > context.max_call_tokens` or
`estimated_cost > context.max_call_cost_usd`. Reserve the estimate against
`context.budget` before setting the Task 4 active-call context.

Extend mutable `_ActiveAICall` with
`reservation: BudgetReservation | None`. `_record_provider_usage()` settles
that exact reservation with the successful LLM callback's `cost_usd`, then
sets `active.reservation = None` before recording the measurement. The outer
gateway `except` block releases only a still-present reservation. After a
successful transport return, a still-present reservation is a
`ProviderUsageContractError`: release it and fail the call, because silently
retaining budget is not allowed. This `ContextVar` association makes
concurrent calls settle only their own reservation.

Before an embedding call, estimate input tokens as
`sum(max(1, (len(text) + 3) // 4) for text in texts)` and reject when that
exceeds `context.max_call_tokens`. Embedding costs remain nullable until an
approved Voyage price is configured; classification policy and the token
ceiling still apply, and actual provider token usage is recorded. Every token
or cost denial records `AIOutcome.budget_exceeded` before returning the error.
Add explicit tests for an over-limit text token estimate and an over-limit
embedding input; both must deny before the respective transport method runs.

- [ ] **Step 6: Load prior spend for resumed queries**

Implement `known_query_cost_sync()` with
`SELECT COALESCE(SUM(cost_usd), 0)` filtered by `query_id`. Add a repository
test proving known spend seeds `AIBudgetLedger.initial_spent_usd`; rows with
unknown cost remain unknown telemetry and are not converted into invented
dollar amounts.

- [ ] **Step 7: Run budget and cost tests**

Run:

```bash
cd apps/backend
uv run --no-sync pytest tests/unit/test_ai_gateway.py tests/unit/test_ai_usage.py tests/unit/test_cost_table.py -v
uv run --no-sync ruff check app/platform/ai app/core/llm.py app/core/embeddings.py app/core/config.py app/db/repositories/ai_usage_repo.py tests/unit/test_ai_gateway.py tests/unit/test_ai_usage.py
uv run --no-sync mypy app/platform/ai app/core/llm.py app/core/embeddings.py app/core/config.py app/db/repositories/ai_usage_repo.py
```

Expected: all commands exit `0`.

- [ ] **Step 8: Commit**

```bash
git add apps/backend/app/platform/ai apps/backend/app/core/llm.py apps/backend/app/core/embeddings.py apps/backend/app/core/config.py apps/backend/app/db/repositories/ai_usage_repo.py apps/backend/tests/unit/test_ai_gateway.py apps/backend/tests/unit/test_ai_usage.py apps/backend/tests/unit/test_cost_table.py
git commit -m "Enforce AI call and query budgets"
```

---

### Task 6: Propagate safe context through agents and public extraction

**Files:**
- Modify: `apps/backend/app/agents/base.py:15-72`
- Modify: `apps/backend/app/agents/orchestrator.py:494-629`
- Modify: `apps/backend/app/api/v1/queries.py:120-160`
- Modify: `apps/backend/app/services/supplier_extraction.py:165-310`
- Modify: `apps/backend/app/agents/external_discovery_agent.py:126-159`
- Create: `apps/backend/tests/unit/test_ai_context_propagation.py`
- Modify test: `apps/backend/tests/unit/test_supplier_extraction.py`
- Modify test: `apps/backend/tests/unit/test_orchestrator_retry.py`
- Create: `apps/backend/tests/unit/test_query_log_privacy.py`

**Interfaces:**
- Consumes: `new_query_ai_context()`, `ai_request_scope()`, and
  `derive_ai_request_context()`.
- Consumes: `AIUsageRepository.known_query_cost_sync()` so clarification
  resumes share the original query's remaining known-cost budget.
- Produces: agent purposes `agent.<agent_name>` with `internal`
  classification.
- Produces: web extraction purposes `discovery.classify_web_page` and
  `discovery.extract_web_page` with `public` classification.
- Produces: `excerpted=True` for truncated snippets/pages and
  `redaction_applied=False` unless a future sanitizer actually transforms the
  content.
- Preserves: one budget ledger across an entire query and nested overrides.
- Removes: raw query and prompt-injection text from application logs while
  preserving user/query identifiers and reason codes.

- [ ] **Step 1: Write propagation tests**

```python
from app.agents.base import BaseAgent
from app.platform.ai.context import current_ai_request_context
from app.platform.ai.types import DataClassification


class ContextProbeAgent(BaseAgent):
    agent_name = "probe"

    def execute(self, state):
        context = current_ai_request_context()
        state["observed_ai_context"] = {
            "purpose": context.purpose,
            "classification": context.classification.value,
            "query_id": context.query_id,
            "user_id": context.user_id,
            "budget_id": id(context.budget),
        }
        return state


def test_base_agent_derives_internal_context_from_state():
    state = {
        "query_id": "22222222-2222-2222-2222-222222222222",
        "user_id": "11111111-1111-1111-1111-111111111111",
    }
    result = ContextProbeAgent().run(state)
    assert result["observed_ai_context"]["purpose"] == "agent.probe"
    assert result["observed_ai_context"]["classification"] == "internal"
    assert result["observed_ai_context"]["query_id"] == state["query_id"]
```

Add a supplier-extraction test whose fake gateway records
`current_ai_request_context()` and asserts `public` classification and the
`discovery.extract_web_page` purpose.

Add `caplog` regressions that submit a unique secret string through query
validation and orchestration and assert the secret never appears in captured
application logs.

- [ ] **Step 2: Run propagation tests and confirm the unclassified result**

Run:

```bash
cd apps/backend
uv run --no-sync pytest tests/unit/test_ai_context_propagation.py tests/unit/test_supplier_extraction.py -v
```

Expected: the context-probe assertion fails because the current context is
`restricted/unclassified`.

- [ ] **Step 3: Bind one root context at the orchestration entry point**

Import `Decimal`, `AIUsageRepository`, and `SyncSessionLocal` at module scope.
Before creating the context, load prior known spend without blocking the event
loop:

```python
def _load_known_spend() -> Decimal:
    with SyncSessionLocal() as db:
        return AIUsageRepository.known_query_cost_sync(db, query_id)

initial_spent_usd = await asyncio.to_thread(_load_known_spend)
```

Then wrap pipeline invocation in `run_pipeline()` with:

```python
context = new_query_ai_context(
    purpose="query.pipeline",
    classification=DataClassification.internal,
    user_id=user_id,
    query_id=query_id,
    correlation_id=query_id,
    initial_spent_usd=initial_spent_usd,
)
with ai_request_scope(context):
    final_state = await asyncio.to_thread(pipeline.invoke, initial_state)
```

Replace the existing `run_in_executor()` pipeline call with `asyncio.to_thread`
because `to_thread` copies `ContextVar` state into the worker. Keep
`resume_pipeline()`'s database load unchanged; it performs no AI work and
delegates to `run_pipeline()`, which seeds one ledger with all known cost
already recorded for the same query. Add regressions whose probe runs inside
the worker thread and sees the root `query_id`, `user_id`, and budget, and
whose resumed query cannot exceed the remaining known-cost budget.

- [ ] **Step 4: Derive agent-specific purpose in `BaseAgent.run()`**

Wrap `self.execute(state)` with:

```python
parent = current_ai_request_context()
if parent.purpose == "unclassified":
    parent = new_query_ai_context(
        purpose=f"agent.{self.agent_name}",
        classification=DataClassification.internal,
        user_id=state.get("user_id"),
        query_id=state.get("query_id"),
    )
agent_context = replace(parent, purpose=f"agent.{self.agent_name}")
with ai_request_scope(agent_context):
    updated_state = self.execute(state)
```

The direct-agent fallback supports existing demos and unit tests while keeping
external gateway calls classified.

- [ ] **Step 5: Override public web-page extraction context**

Add optional `query_id` and `user_id` keyword arguments to
`stage1_classify()` and `stage2_extract()`. Wrap their LLM calls with:

```python
context = derive_ai_request_context(
    purpose="discovery.classify_web_page",
    classification=DataClassification.public,
    query_id=query_id,
    user_id=user_id,
    redaction_applied=False,
    excerpted=True,
)
with ai_request_scope(context):
    return complete_json_dict(...)
```

Use `discovery.extract_web_page` for stage 2. Pass state IDs from
`ExternalDiscoveryAgent.execute()`. Do not place the URL or page text in the
context or usage event.

- [ ] **Step 6: Remove raw query text from application logs**

Change query-submission, prompt-injection, and orchestration log messages to
emit only user ID, query ID when available, scope, turn, query length, and a
stable reason code. The raw query remains in its authorized PostgreSQL domain
records and audit trail; it must not be copied to process logs.

- [ ] **Step 7: Run agent, extraction, and orchestration regressions**

Run:

```bash
cd apps/backend
uv run --no-sync pytest \
  tests/unit/test_ai_context_propagation.py \
  tests/unit/test_supplier_extraction.py \
  tests/unit/test_orchestrator_retry.py \
  tests/unit/test_query_log_privacy.py \
  tests/unit/test_parser_react.py \
  tests/unit/test_compliance_quote_integration.py -v
uv run --no-sync ruff check app/agents/base.py app/agents/orchestrator.py app/agents/external_discovery_agent.py app/api/v1/queries.py app/services/supplier_extraction.py tests/unit/test_ai_context_propagation.py tests/unit/test_query_log_privacy.py
uv run --no-sync mypy app/agents/base.py app/agents/orchestrator.py app/agents/external_discovery_agent.py app/api/v1/queries.py app/services/supplier_extraction.py
```

Expected: all commands exit `0`.

- [ ] **Step 8: Commit**

```bash
git add apps/backend/app/agents apps/backend/app/api/v1/queries.py apps/backend/app/services/supplier_extraction.py apps/backend/tests/unit/test_ai_context_propagation.py apps/backend/tests/unit/test_supplier_extraction.py apps/backend/tests/unit/test_orchestrator_retry.py apps/backend/tests/unit/test_query_log_privacy.py
git commit -m "Propagate AI policy context through discovery"
```

---

### Task 7: Cover evaluation, scripts, and provider boundaries

**Files:**
- Modify: `apps/backend/app/evaluation/baselines.py`
- Modify: `apps/backend/app/evaluation/runner.py`
- Modify: `apps/backend/experiments/paradigm1_singleprompt.py`
- Modify: `apps/backend/experiments/paradigm2_rag.py`
- Modify: `apps/backend/scripts/provider_integration_check.py`
- Modify: `apps/backend/scripts/ingest_suppliers.py`
- Modify: `apps/backend/scripts/bulk_ingest_synthetic.py`
- Modify: `apps/backend/scripts/sync_active_supplier_vectors.py`
- Create: `apps/backend/tests/unit/test_ai_gateway_boundaries.py`
- Modify test: `apps/backend/tests/unit/test_paradigm_baselines.py`
- Modify test: `apps/backend/tests/unit/test_eval_runner.py`

**Interfaces:**
- Consumes: gateway factories and `ai_request_scope()`.
- Produces: explicit purposes for evaluation, smoke checks, and ingestion.
- Enforces: only `app/core/llm.py` may import `openai`; only
  `app/core/embeddings.py` may import `voyageai`.
- Removes: raw evaluation-query text from process logs while retaining query
  number, difficulty, result counts, and timing.

- [ ] **Step 1: Write the provider import guard**

```python
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[2]
SCANNED_ROOTS = ("app", "experiments", "scripts")


def test_provider_sdks_are_confined_to_transports():
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
```

Add evaluation tests that inject a gateway probe and assert purposes
`evaluation.p1`, `evaluation.p2`, and `evaluation.runner` with `internal`
classification.

- [ ] **Step 2: Run boundary and evaluation tests**

Run:

```bash
cd apps/backend
uv run --no-sync pytest \
  tests/unit/test_ai_gateway_boundaries.py \
  tests/unit/test_paradigm_baselines.py \
  tests/unit/test_eval_runner.py -v
```

Expected: evaluation context assertions fail because the evaluation functions
do not bind an AI request context.

- [ ] **Step 3: Bind evaluation contexts**

Wrap P1, P2, and evaluation-run entry points in `AIRequestContext` scopes with:

```python
AIRequestContext(
    purpose="evaluation.p1",
    classification=DataClassification.internal,
    user_id=EVAL_USER_ID,
    correlation_id=run_id,
    budget=AIBudgetLedger(Decimal(str(settings.AI_MAX_QUERY_COST_USD))),
    max_call_cost_usd=Decimal(str(settings.AI_MAX_CALL_COST_USD)),
)
```

Use `evaluation.p2` and `evaluation.runner` for the corresponding paths.
Preserve curated supplier-ID filtering and benchmark fail-fast behavior.

- [ ] **Step 4: Remove raw evaluation text from logs**

Replace raw-query slices and derived keyword lists in
`evaluation/baselines.py` log calls with query length, result count, and
timing. In `evaluation/runner.py`, retain benchmark query number and difficulty
but remove the raw-query slice. Add a `caplog` regression that runs a baseline
with a unique secret and proves the secret is absent.

- [ ] **Step 5: Bind ingestion and provider-check contexts**

Use `supplier.indexing` with `internal` classification around supplier vector
indexing. Use `provider.smoke_check` with `public` classification around the
literal `provider-ok` call. Update the provider assertion to:

```python
client = get_llm_client()
assert isinstance(client, AIGateway)
assert isinstance(client.transport, OpenAIProvider)
```

- [ ] **Step 6: Add an executable unbound-call guard**

In `test_ai_gateway_boundaries.py`, instantiate the real gateway with fake
transports and assert that each public entry function binds a non-restricted
context before the fake transport receives a call. Cover P1, P2,
`provider_integration_check.check_provider()`, and one vector-ingestion
function. Also scan `app`, `experiments`, and `scripts` for direct
`OpenAIProvider(` or `EmbeddingClient(` construction and allow it only in the
two transport factories and the explicitly marked live-verification type
assertion; unit tests may construct transports directly.

- [ ] **Step 7: Run evaluation, script, and vector regressions**

Run:

```bash
cd apps/backend
uv run --no-sync pytest \
  tests/unit/test_ai_gateway_boundaries.py \
  tests/unit/test_paradigm_baselines.py \
  tests/unit/test_eval_runner.py \
  tests/unit/test_llm_providers.py \
  tests/unit/test_query_memory.py \
  tests/unit/test_tools.py -v
uv run --no-sync ruff check app experiments scripts tests/unit/test_ai_gateway_boundaries.py
uv run --no-sync mypy app experiments
```

Expected: all commands exit `0`.

- [ ] **Step 8: Commit**

```bash
git add apps/backend/app/evaluation apps/backend/experiments apps/backend/scripts apps/backend/tests/unit/test_ai_gateway_boundaries.py apps/backend/tests/unit/test_paradigm_baselines.py apps/backend/tests/unit/test_eval_runner.py
git commit -m "Apply AI policy to evaluation and indexing"
```

---

### Task 8: Expose query and provider usage metrics

**Files:**
- Create: `apps/backend/app/schemas/metrics.py`
- Modify: `apps/backend/app/db/repositories/ai_usage_repo.py`
- Modify: `apps/backend/app/api/v1/metrics.py`
- Modify test: `apps/backend/tests/unit/test_metrics.py`
- Modify: `apps/backend/openapi.json`

**Interfaces:**
- Produces: `AIUsageSummary`, `AIProviderUsageRow`, `AIPurposeUsageRow`, and
  `AdminMetricsResponse`.
- Produces API fields: `ai_usage.summary`, `ai_usage.providers`,
  `ai_usage.purposes`, and `ai_usage.top_queries`.
- Preserves existing operational metrics fields.

- [ ] **Step 1: Extend endpoint contract tests**

After the existing five operational-query results, add mocked results six
through nine for AI summary, provider groups, purpose groups, and top queries,
in that order.
Assert:

```python
assert body["ai_usage"]["summary"] == {
    "calls": 12,
    "input_units": 4200,
    "output_units": 900,
    "known_cost_usd": 0.0432,
    "unknown_cost_calls": 3,
    "denied_calls": 2,
    "failed_calls": 1,
}
assert body["ai_usage"]["providers"][0] == {
    "provider": "openai",
    "model": "gpt-4o-mini-2024-07-18",
    "operation": "chat",
    "calls": 8,
    "p95_ms": 1820,
    "known_cost_usd": 0.0432,
    "unknown_cost_calls": 0,
}
assert body["ai_usage"]["purposes"][0] == {
    "purpose": "agent.parser",
    "calls": 5,
    "p95_ms": 1510,
    "known_cost_usd": 0.012,
    "denied_calls": 0,
    "failed_calls": 1,
}
```

Assert that a provider with nullable cost increments `unknown_cost_calls`
instead of reporting `$0`.

- [ ] **Step 2: Run the metrics tests and confirm missing AI usage**

Run:

```bash
cd apps/backend
uv run --no-sync pytest tests/unit/test_metrics.py -v
```

Expected: response assertions fail because `ai_usage` is absent.

- [ ] **Step 3: Add typed response schemas**

```python
class AIUsageSummary(BaseModel):
    calls: int
    input_units: int
    output_units: int
    known_cost_usd: float
    unknown_cost_calls: int
    denied_calls: int
    failed_calls: int


class AIProviderUsageRow(BaseModel):
    provider: str
    model: str
    operation: str
    calls: int
    p95_ms: int
    known_cost_usd: float
    unknown_cost_calls: int


class AIPurposeUsageRow(BaseModel):
    purpose: str
    calls: int
    p95_ms: int
    known_cost_usd: float
    denied_calls: int
    failed_calls: int


class AIQueryUsageRow(BaseModel):
    query_id: str
    calls: int
    known_cost_usd: float
    unknown_cost_calls: int
```

`AdminMetricsResponse` retains the current summary, agent latency, throttle,
recent errors, and LLM provider data and adds these AI usage structures.

- [ ] **Step 4: Add aggregate repository queries**

Implement async repository methods that:

- filter `created_at` using the validated `window_hours`;
- sum only non-null `cost_usd`;
- count null costs as unknown;
- group provider rows by provider/model/operation;
- group purpose rows by `purpose`, which makes `agent.<agent_name>` calls
  directly addressable without duplicating an agent-name column;
- return p95 latency with `PERCENTILE_CONT`;
- return the ten highest known-cost non-null query IDs;
- never expose user IDs, prompts, responses, or document identifiers.

- [ ] **Step 5: Return typed AI metrics**

Inject `AIUsageRepository` into the existing endpoint, append its aggregate
results, and set `response_model=AdminMetricsResponse`. Remove the process-wide
`total_cost_usd` as the source of truth; retain the active provider/model label
as runtime metadata.

- [ ] **Step 6: Regenerate OpenAPI mechanically**

Run:

```bash
cd apps/backend
uv run --no-sync python -c 'import json; from app.main import app; open("openapi.json", "w", encoding="utf-8").write(json.dumps(app.openapi(), indent=2) + "\n")'
```

- [ ] **Step 7: Run API and schema checks**

Run:

```bash
cd apps/backend
uv run --no-sync pytest tests/unit/test_metrics.py tests/unit/test_ai_usage.py -v
uv run --no-sync ruff check app/api/v1/metrics.py app/schemas/metrics.py app/db/repositories/ai_usage_repo.py tests/unit/test_metrics.py
uv run --no-sync mypy app/api/v1/metrics.py app/schemas/metrics.py app/db/repositories/ai_usage_repo.py
```

Expected: all commands exit `0`.

- [ ] **Step 8: Commit**

```bash
git add apps/backend/app/api/v1/metrics.py apps/backend/app/schemas/metrics.py apps/backend/app/db/repositories/ai_usage_repo.py apps/backend/tests/unit/test_metrics.py apps/backend/openapi.json
git commit -m "Expose persistent AI usage metrics"
```

---

### Task 9: Add the AI usage dashboard

**Files:**
- Modify: `apps/frontend/package.json`
- Modify: `apps/frontend/package-lock.json`
- Create: `apps/frontend/vitest.config.ts`
- Create: `apps/frontend/src/test/setup.ts`
- Create: `apps/frontend/src/features/admin/AIUsagePanel.tsx`
- Create: `apps/frontend/src/features/admin/AIUsagePanel.test.tsx`
- Modify: `apps/frontend/src/services/api.ts:176-212`
- Modify: `apps/frontend/src/pages/AdminMetricsPage.tsx`

**Interfaces:**
- Consumes: `AdminMetrics.ai_usage`.
- Produces: provider/model/operation table, known cost, unknown-cost warning,
  denied/failure counts, and highest-cost query links.
- Preserves: existing Node-based presentation tests.

- [ ] **Step 1: Add component-test dependencies and scripts**

Add dev dependencies:

```json
"@testing-library/dom": "^10.4.1",
"@testing-library/jest-dom": "^6.9.1",
"@testing-library/react": "^16.3.2",
"jsdom": "^29.1.1",
"vitest": "^4.1.10"
```

Change scripts to:

```json
"test": "npm run test:unit && npm run test:components",
"test:unit": "node --experimental-strip-types --test src/**/*.test.ts",
"test:components": "vitest run"
```

Run `node --version` first and require Node 20 or newer, then run
`npm install` from `apps/frontend` to update the lockfile. Vitest 4 requires
Vite 6+ and Node 20+; this repository already uses Vite 8 and its current
workspace runtime is Node 26.

- [ ] **Step 2: Write dashboard component tests**

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AIUsagePanel } from "./AIUsagePanel";

const usage = {
  summary: {
    calls: 12,
    input_units: 4200,
    output_units: 900,
    known_cost_usd: 0.0432,
    unknown_cost_calls: 3,
    denied_calls: 2,
    failed_calls: 1,
  },
  providers: [{
    provider: "openai",
    model: "gpt-4o-mini-2024-07-18",
    operation: "chat",
    calls: 8,
    p95_ms: 1820,
    known_cost_usd: 0.0432,
    unknown_cost_calls: 0,
  }],
  purposes: [{
    purpose: "agent.parser",
    calls: 5,
    p95_ms: 1510,
    known_cost_usd: 0.012,
    denied_calls: 0,
    failed_calls: 1,
  }],
  top_queries: [],
};

describe("AIUsagePanel", () => {
  it("shows known cost and warns about unknown-cost calls", () => {
    render(<AIUsagePanel usage={usage} />);
    expect(screen.getByText("$0.0432")).toBeInTheDocument();
    expect(screen.getByText(/3 calls have unknown cost/i)).toBeInTheDocument();
    expect(screen.getByText(/gpt-4o-mini-2024-07-18/i)).toBeInTheDocument();
    expect(screen.getByText(/agent.parser/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run the component test and confirm missing component**

Run:

```bash
cd apps/frontend
npm run test:components -- src/features/admin/AIUsagePanel.test.tsx
```

Expected: failure because `AIUsagePanel.tsx` does not exist.

- [ ] **Step 4: Add Vitest configuration**

```typescript
// vitest.config.ts
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
  },
});
```

`src/test/setup.ts` imports `@testing-library/jest-dom/vitest`.

- [ ] **Step 5: Add exact API types**

Define:

```typescript
export interface AIUsageMetrics {
  summary: {
    calls: number;
    input_units: number;
    output_units: number;
    known_cost_usd: number;
    unknown_cost_calls: number;
    denied_calls: number;
    failed_calls: number;
  };
  providers: Array<{
    provider: string;
    model: string;
    operation: string;
    calls: number;
    p95_ms: number;
    known_cost_usd: number;
    unknown_cost_calls: number;
  }>;
  purposes: Array<{
    purpose: string;
    calls: number;
    p95_ms: number;
    known_cost_usd: number;
    denied_calls: number;
    failed_calls: number;
  }>;
  top_queries: Array<{
    query_id: string;
    calls: number;
    known_cost_usd: number;
    unknown_cost_calls: number;
  }>;
}
```

Add `ai_usage: AIUsageMetrics` and the existing `llm` runtime shape to
`AdminMetrics`.

- [ ] **Step 6: Implement and mount `AIUsagePanel`**

Render:

- four summary cards for calls, known cost, denied calls, and failed calls;
- an amber warning when `unknown_cost_calls > 0`;
- a provider table with model, operation, calls, p95, known cost, and unknown
  count;
- a purpose/agent table with calls, p95, known cost, denials, and failures;
- top-query links to `/query/{query_id}/results`;
- an explicit empty state when `calls === 0`.

Mount the component after the existing operational summary in
`AdminMetricsPage`.

- [ ] **Step 7: Run frontend tests, lint, and build**

Run:

```bash
cd apps/frontend
npm test
npm run lint
npm run build
```

Expected: all commands exit `0`.

- [ ] **Step 8: Commit**

```bash
git add apps/frontend/package.json apps/frontend/package-lock.json apps/frontend/vitest.config.ts apps/frontend/src/test apps/frontend/src/features/admin apps/frontend/src/services/api.ts apps/frontend/src/pages/AdminMetricsPage.tsx
git commit -m "Show AI usage and budget visibility"
```

---

### Task 10: Document, verify, and close the AI gateway slice

**Files:**
- Create: `docs/adr/ADR-003-ai-data-egress-and-usage.md`
- Modify: `ARCHITECTURE.md`
- Modify: `README.md`
- Modify: `apps/backend/scripts/provider_integration_check.py`
- Modify: `apps/backend/tests/unit/test_live_verification_script.py`
- Modify: `scripts/verify_release.sh`

**Interfaces:**
- Documents: classifications, policy defaults, budget behavior, unknown
  embedding cost, provider approval, and operational response.
- Verifies: gateway type, policy binding, database usage row, and no content in
  stored telemetry.
- Preserves: the existing deterministic and optional live release gates.

- [ ] **Step 1: Write a provider-check regression**

Add a test that runs `check_provider()` with a fake `AIGateway` and asserts:

- the gateway wraps `OpenAIProvider`;
- the smoke prompt is bound as `public/provider.smoke_check`;
- one safe usage event is emitted;
- the event representation does not contain `provider-ok`;
- the script prints provider/model and numeric cost only.

- [ ] **Step 2: Run the regression and confirm old provider assertion failure**

Run:

```bash
cd apps/backend
uv run --no-sync pytest tests/unit/test_live_verification_script.py -v
```

Expected: failure because the script still requires a bare
`OpenAIProvider`.

- [ ] **Step 3: Update provider integration verification**

Change `check_provider()` to assert `AIGateway` plus an
`OpenAIProvider` transport. Bind the smoke prompt using:

```python
with ai_request_scope(
    new_query_ai_context(
        purpose="provider.smoke_check",
        classification=DataClassification.public,
        user_id=EVAL_USER_ID,
        query_id=None,
        correlation_id=correlation_id,
    )
):
    out = client.complete(...)
```

Generate `correlation_id = f"provider-check-{uuid4()}"` before the scope.
After the call, query the usage event by that exact correlation ID and assert
its safe metadata fields.

- [ ] **Step 4: Write ADR-003**

The ADR records:

- status `Accepted`;
- default allow list `public,internal`;
- restricted fallback for unbound context;
- required purpose, classification, redaction/excerpt state, token/cost
  limits, and correlation identifiers;
- provider transports retained below the gateway;
- PostgreSQL usage events as operational source of truth;
- content-exclusion rule;
- per-call `$0.10` and per-query `$0.50` configurable defaults;
- per-call `32,000`-token configurable default for text and embedding input;
- nullable unknown embedding cost rather than silent zero;
- security/legal approval required before confidential external processing;
- deterministic fake providers for CI and separate live checks.

- [ ] **Step 5: Update architecture and operator documentation**

Update `ARCHITECTURE.md` and `README.md` with:

- gateway position in the request flow;
- classification meanings;
- required environment variables;
- admin usage dashboard;
- budget-denial behavior;
- resumed-query budget seeding from persisted known spend;
- how to investigate `classification_not_allowed`,
  `budget_exceeded`, and usage persistence errors;
- how to run the provider check without printing credentials.

- [ ] **Step 6: Make the release gate explicit**

Add focused policy and boundary tests before the full backend suite in
`scripts/verify_release.sh`:

```bash
uv run --no-sync pytest \
  tests/unit/test_ai_policy.py \
  tests/unit/test_ai_gateway.py \
  tests/unit/test_ai_gateway_boundaries.py
```

The existing full `pytest`, Ruff, mypy, frontend tests, lint, build, bundle,
and `git diff --check` commands remain.

- [ ] **Step 7: Run focused verification**

Run:

```bash
cd apps/backend
uv run --no-sync pytest \
  tests/unit/test_ai_policy.py \
  tests/unit/test_ai_gateway.py \
  tests/unit/test_ai_usage.py \
  tests/unit/test_ai_context_propagation.py \
  tests/unit/test_ai_gateway_boundaries.py \
  tests/unit/test_llm_providers.py \
  tests/unit/test_metrics.py \
  tests/unit/test_live_verification_script.py -v
```

Expected: all focused tests pass.

- [ ] **Step 8: Run complete release verification**

Run from the repository root:

```bash
./scripts/verify_release.sh
```

Expected:

- backend tests pass;
- Ruff exits `0`;
- mypy exits `0`;
- frontend unit and component tests pass;
- frontend lint and build pass;
- bundle check passes;
- `git diff --check` exits `0`;
- protected benchmark and thesis paths remain unchanged.

- [ ] **Step 9: Inspect the final change set**

Run:

```bash
git status --short
git diff --stat HEAD~9..HEAD
git diff --check
rg -n "import openai|from openai|import voyageai|from voyageai" apps/backend/app
```

Expected provider SDK matches:

```text
apps/backend/app/core/llm.py
apps/backend/app/core/embeddings.py
```

No benchmark result, synthetic dataset, or thesis branch files may be
modified.

- [ ] **Step 10: Commit**

```bash
git add docs/adr/ADR-003-ai-data-egress-and-usage.md ARCHITECTURE.md README.md apps/backend/scripts/provider_integration_check.py apps/backend/tests/unit/test_live_verification_script.py scripts/verify_release.sh
git commit -m "Document and verify the AI gateway release"
```

---

## Completion Evidence

Before declaring this implementation slice complete, capture:

1. The final `./scripts/verify_release.sh` output.
2. `alembic current` showing revision `e2f4a9c1b7d8`.
3. A deterministic gateway-denial test proving the transport was not called.
4. A database usage row containing classification, purpose, provider, model,
   units, cost status, latency, outcome, and correlation IDs.
5. A source scan proving provider SDK imports are confined to the two
   transport modules.
6. A rendered admin dashboard with known and unknown costs distinguished.
7. A clean `git status --short`.

## Follow-On Plans

After this slice is verified, create separate executable plans in this order:

1. Durable jobs, transactional outbox, Redis event streaming, and worker health.
2. Secure object storage, validated uploads, quarantine, and ClamAV scanning.
3. Feature flags, compliance-officer RBAC, and production authentication hardening.
4. Parser schema and clarification confidence hardening.
5. Candidate ledger and crawler provenance.
6. Supplier documents, certificates, expiry, verification, and risk.
7. Procurement comparison, saved alerts, RFQs, quotes, and outreach approval.
8. Document RAG, supplier relationships, feedback, and learned ranking.
9. ERP, supplier-master, risk, and messaging adapters.
