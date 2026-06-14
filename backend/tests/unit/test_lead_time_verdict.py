"""Phase D bug 2 — the compliance gate must emit a lead-time verdict on every
query that specifies lead_time_max_days, including suppliers that do not report
a lead time (previously they silently passed the gate with no verdict at all).
"""

from app.agents.compliance_agent import ComplianceAgent


def _agent() -> ComplianceAgent:
    agent = ComplianceAgent.__new__(ComplianceAgent)
    agent._short_circuit_count = 0
    agent._llm_supplier_count = 0
    return agent


def _lead_time_verdict(result: dict):
    for r in result["compliance_results"]:
        if r["constraint_name"] == "lead_time":
            return r
    return None


def test_missing_lead_time_emits_partial_not_silence():
    agent = _agent()
    supplier = {"id": "s1", "country": "DE", "certifications": [], "lead_time_days": None}
    constraints = {"lead_time_max_days": 30}
    result = agent._check_supplier(supplier, constraints, geo_distance=None)
    verdict = _lead_time_verdict(result)
    assert verdict is not None                 # was previously dropped silently
    assert verdict["status"] == "PARTIAL"      # unknown, cannot confirm — not PASS


def test_zero_lead_time_is_pass_not_treated_as_missing():
    # lead_time_days == 0 (same-day) is reported and within any positive limit.
    agent = _agent()
    supplier = {"id": "s2", "country": "DE", "certifications": [], "lead_time_days": 0}
    constraints = {"lead_time_max_days": 30}
    result = agent._check_supplier(supplier, constraints, geo_distance=None)
    verdict = _lead_time_verdict(result)
    assert verdict is not None
    assert verdict["status"] == "PASS"


def test_lead_time_within_limit_passes():
    agent = _agent()
    supplier = {"id": "s3", "country": "DE", "certifications": [], "lead_time_days": 20}
    constraints = {"lead_time_max_days": 30}
    result = agent._check_supplier(supplier, constraints, geo_distance=None)
    assert _lead_time_verdict(result)["status"] == "PASS"


def test_lead_time_far_over_limit_fails():
    agent = _agent()
    supplier = {"id": "s4", "country": "DE", "certifications": [], "lead_time_days": 90}
    constraints = {"lead_time_max_days": 30}
    result = agent._check_supplier(supplier, constraints, geo_distance=None)
    verdict = _lead_time_verdict(result)
    assert verdict["status"] == "FAIL"
    assert result["overall_pass"] is False
