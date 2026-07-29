"""Typed admin operational and AI usage metrics responses."""

from pydantic import BaseModel


class OperationalSummary(BaseModel):
    total_queries: int
    total_agent_invocations: int
    total_human_decisions: int
    queries_with_errors: int


class AgentLatencyRow(BaseModel):
    agent_name: str
    p50_ms: int
    p95_ms: int
    mean_ms: int
    count: int


class ThrottleEvents(BaseModel):
    throttle_429_count: int
    throttle_pacing_events: int
    sanctions_pending_review: int


class RecentErrorRow(BaseModel):
    timestamp: str | None
    agent_name: str
    action: str
    query_id: str | None
    reasoning: str


class LLMRuntimeInfo(BaseModel):
    provider: str
    model: str | None = None
    last_provider_used: str | None = None
    error_code: str | None = None


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


class AIUsageMetrics(BaseModel):
    summary: AIUsageSummary
    providers: list[AIProviderUsageRow]
    purposes: list[AIPurposeUsageRow]
    top_queries: list[AIQueryUsageRow]


class AdminMetricsResponse(BaseModel):
    window_hours: int
    as_of: str
    summary: OperationalSummary
    agent_latency: list[AgentLatencyRow]
    throttle_events: ThrottleEvents
    recent_errors: list[RecentErrorRow]
    llm: LLMRuntimeInfo
    ai_usage: AIUsageMetrics
