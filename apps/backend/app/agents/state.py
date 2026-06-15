"""
app/agents/state.py — Shared state schema for the LangGraph agent pipeline.

WHY A SINGLE STATE DICT?
All agents share one state object. Each agent reads what it needs
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
    """Production v2: rich product intent representation."""
    # Product intent (replaces category as primary key)
    product_type: Optional[str]
    product_keywords: Optional[list[str]]
    industry_context: Optional[str]
    buyer_intent: Optional[str]
    category_hint: Optional[str]

    # Location
    location_name: Optional[str]
    location_city: Optional[str]
    location_country: Optional[str]
    location_region: Optional[str]
    location_lat: Optional[float]
    location_lng: Optional[float]
    location_radius_km: Optional[float]

    # Constraints
    certifications: Optional[list[str]]
    capacity_min: Optional[float]
    capacity_unit: Optional[str]
    lead_time_max_days: Optional[int]

    # Query metadata
    query_type: Optional[str]
    complexity: Optional[str]
    original_language: Optional[str]


class ComplianceResult(TypedDict, total=False):
    """Compliance check result for one constraint on one supplier."""
    constraint_name: str
    status: str               # "PASS", "FAIL", "PARTIAL"
    reason: str               # Human-readable explanation
    confidence: float         # 0.0 to 1.0
    evidence_quote: str       # Task 1.4: verbatim phrase the LLM cited (LLM path only)
    quote_flag: str           # Task 1.4: downgrade reason, e.g. "quote_not_in_source"


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


class AuditEntry(TypedDict, total=False):
    """One entry in the agent audit trail.

    `input_snapshot` / `output_snapshot` are optional structured payloads
    introduced for Task 3.1's ReAct trace. When present they override the
    plain-string summaries at the API flush stage so the full trace lands
    in audit_logs.{input,output}_snapshot as JSON.
    """
    agent_name: str
    action: str
    reasoning: Optional[str]
    input_summary: str
    output_summary: str
    duration_ms: int
    timestamp: str
    input_snapshot: Optional[dict]
    output_snapshot: Optional[dict]


class AgentState(TypedDict):
    """
    The complete shared state for the SupplierMind agent pipeline.

    Lifecycle:
    1. Initialised with: raw_query, query_id, user_id, search_scope
    2. Parser Agent adds: parsed_constraints, detected_language
    3. External Discovery Agent adds: newly_discovered_supplier_ids
    4. Discovery Agent adds: candidate_supplier_ids, semantic/structured/geo results
    5. Compliance Agent adds: compliance_results_by_supplier
    6. Ranking Agent adds: ranked_suppliers, final shortlist
    7. Evaluator Agent adds: evaluator_verdict, evaluator_should_retry
    8. Throughout: audit_log grows with each agent's reasoning
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

    # ── Task 3.3 — Multi-turn clarification dialogue ──────────────────
    # Populated by parser_node when the Parser raises a clarification: the
    # DB row id under which the partial state has been persisted, so the
    # API layer can hand it back to the user. `turn_number` is 1 on first
    # ask, 2/3 on resumed re-asks. `previous_partial_constraints` is the
    # hint the resumed Parser prompt uses to avoid starting from scratch.
    clarification_id: Optional[str]
    turn_number: int
    previous_partial_constraints: Optional[ParsedConstraints]

    # ── External Discovery Agent output ───────────────────────────────
    newly_discovered_supplier_ids: list[str]
    external_discovery_stats: dict

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

    # ── Production v2 additions ───────────────────────────────────────
    search_scope: str
    tier_assignments: dict[str, str]
    evaluator_retries: int
    evaluator_verdict: Optional[str]
    evaluator_should_retry: bool

    # ── Task 3.1 — ReAct trace + termination reason ─────────────────
    react_trace: list[dict]
    react_terminated_by: Optional[str]   # "finish" | "max_iterations" | "parse_failed"

    # ── Audit trail (grows throughout pipeline) ───────────────────────
    audit_log: list[AuditEntry]

    # ── Pipeline control ──────────────────────────────────────────────
    error: Optional[str]
    pipeline_status: str    # "running", "completed", "failed", "needs_clarification"
