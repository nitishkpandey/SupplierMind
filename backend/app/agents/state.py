"""
app/agents/state.py — Shared state schema for the LangGraph agent pipeline.

WHY A SINGLE STATE DICT?
All 5 agents share one state object. Each agent reads what it needs
and writes its output back. LangGraph manages passing the state
between agents automatically.

Think of it as a relay baton. Each agent enriches it, then passes it on.

IMPORTANT: All fields must have a default value (None or []).
LangGraph initialises the state dict at the start of a pipeline run.
If a field has no default, LangGraph raises an error on initialisation.
"""

from typing import Any, Optional
from typing_extensions import TypedDict


class ParsedConstraints(TypedDict, total=False):
    """
    Structured output of the Parser Agent.
    total=False means all fields are optional (parsed from natural language,
    so not every query will contain every constraint type).
    """
    category: Optional[str]          # "metals", "electronics", etc.
    location_name: Optional[str]      # "Bremen", "Germany", etc.
    location_lat: Optional[float]     # Geocoded latitude
    location_lng: Optional[float]     # Geocoded longitude
    location_radius_km: Optional[float]  # Radius in km (if specified)
    certifications: Optional[list[str]]  # ["ISO 9001", "ISO 14001"]
    capacity_min: Optional[float]
    capacity_unit: Optional[str]      # "kg/month", "units/month", etc.
    lead_time_max_days: Optional[int]
    budget_note: Optional[str]        # Free text — not hard constraint
    original_language: Optional[str]  # Detected language of input query


class ComplianceResult(TypedDict):
    """Compliance check result for one constraint on one supplier."""
    constraint_name: str
    status: str               # "PASS", "FAIL", "PARTIAL"
    reason: str               # Human-readable explanation
    confidence: float         # 0.0 to 1.0


class SupplierComplianceResult(TypedDict):
    """All compliance results for one supplier."""
    supplier_id: str
    compliance_results: list[ComplianceResult]
    overall_pass: bool        # True if NO "FAIL" constraints
    has_partial: bool         # True if any "PARTIAL" constraints
    pass_rate: float          # Fraction of constraints that PASS


class RankedSupplier(TypedDict):
    """One ranked supplier in the final shortlist."""
    rank: int
    supplier_id: str
    total_score: float
    constraint_score: float
    semantic_score: float
    proximity_score: Optional[float]
    completeness_score: float
    compliance_matrix: dict[str, str]   # {constraint: "PASS"/"FAIL"/"PARTIAL"}
    explanation: str                     # LLM-generated explanation
    distance_km: Optional[float]


class AuditEntry(TypedDict):
    """One entry in the agent audit trail."""
    agent_name: str
    action: str
    reasoning: Optional[str]
    input_summary: str
    output_summary: str
    duration_ms: int
    timestamp: str


class AgentState(TypedDict):
    """
    The complete shared state for the SupplierMind agent pipeline.

    Lifecycle:
    1. Initialised with: raw_query, query_id, user_id
    2. Parser Agent adds: parsed_constraints, detected_language
    3. Discovery Agent adds: candidate_supplier_ids, semantic/structured/geo results
    4. Compliance Agent adds: compliance_results_by_supplier
    5. Ranking Agent adds: ranked_suppliers, final shortlist
    6. Throughout: audit_log grows with each agent's reasoning
    """

    # ── Input (set by API before pipeline starts) ─────────────────────
    raw_query: str
    query_id: str
    user_id: str

    # ── Parser Agent output ───────────────────────────────────────────
    parsed_constraints: Optional[ParsedConstraints]
    detected_language: str
    needs_clarification: bool
    clarification_question: Optional[str]

    # ── Discovery Agent output ────────────────────────────────────────
    candidate_supplier_ids: list[str]
    semantic_scores: dict[str, float]   # {supplier_id: similarity_score}
    geo_distances: dict[str, float]     # {supplier_id: distance_km}
    retry_count: int
    relaxed_constraints: list[str]      # Which constraints were relaxed on retry

    # ── Compliance Agent output ───────────────────────────────────────
    compliance_results: list[SupplierComplianceResult]

    # ── Ranking Agent output ──────────────────────────────────────────
    ranked_suppliers: list[RankedSupplier]

    # ── Audit trail (grows throughout pipeline) ───────────────────────
    audit_log: list[AuditEntry]

    # ── Pipeline control ──────────────────────────────────────────────
    error: Optional[str]
    pipeline_status: str    # "running", "completed", "failed", "needs_clarification"
