"""Privacy-safe value types shared by AI policy and gateway services."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


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
