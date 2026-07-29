"""Privacy-safe value types shared by AI policy and gateway services."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.platform.ai.budget import AIBudgetLedger


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
    budget: AIBudgetLedger | None = None
    max_call_tokens: int = 32_000
    max_call_cost_usd: Decimal = Decimal("0.10")


@dataclass(frozen=True, slots=True)
class AIPolicyDecision:
    allowed: bool
    provider: str
    operation: AIOperation
    classification: DataClassification
    reason_code: str


@dataclass(frozen=True, slots=True)
class ProviderUsage:
    provider: str
    model: str
    operation: AIOperation
    input_units: int
    output_units: int
    cost_usd: Decimal | None
    latency_ms: int


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
