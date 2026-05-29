"""Task 1.5 — template-based ranking explanations.

Pure-function tests, no LLM cost. Proves explanations are assembled
deterministically from the compliance matrix + supplier data, and that every
numeric fact traces verbatim to the supplier object (spec Test 1, number fidelity).
"""

from app.agents.ranking_agent import (
    build_concerns,
    build_explanation,
    build_facts,
    build_match_reasons,
    build_summary,
)


def _comp(results):
    return {"supplier_id": "s1", "compliance_results": results}


# ── build_facts: numbers come straight from the supplier object ──────
def test_facts_numbers_match_supplier_exactly():
    supplier = {
        "capacity_value": 454228.0,
        "capacity_unit": "units/month",
        "lead_time_days": 58,
        "certifications": ["ISO 9001", "RoHS"],
        "city": "Bremen",
        "country": "Germany",
    }
    facts = build_facts(supplier, tier="approved")
    assert facts["capacity"] == "454,228 units/month"
    assert facts["lead_time"] == "58 days"
    assert facts["certifications"] == ["ISO 9001", "RoHS"]
    assert facts["location"] == "Bremen, Germany"
    assert facts["tier"] == "approved"


def test_facts_whole_float_capacity_has_no_decimal():
    facts = build_facts({"capacity_value": 2603.0, "capacity_unit": "kg/month"}, "discovered")
    assert facts["capacity"] == "2,603 kg/month"


def test_facts_missing_fields_render_not_specified():
    facts = build_facts({"certifications": []}, "discovered")
    assert facts["capacity"] == "not specified"
    assert facts["lead_time"] == "not specified"
    assert facts["location"] == "not specified"
    assert facts["certifications"] == []


# ── build_summary ─────────────────────────────────────────────────────
def test_summary_all_pass():
    comp = _comp([{"constraint_name": "ISO 9001", "status": "PASS", "reason": "x"}])
    assert build_summary(comp) == "Meets all specified requirements."


def test_summary_partial_no_fail():
    comp = _comp([
        {"constraint_name": "ISO 9001", "status": "PASS", "reason": "x"},
        {"constraint_name": "FSC", "status": "PARTIAL", "reason": "x"},
    ])
    assert build_summary(comp) == "Meets core requirements; some criteria need confirmation."


def test_summary_counts_fails():
    comp = _comp([
        {"constraint_name": "FSC", "status": "FAIL", "reason": "x"},
        {"constraint_name": "capacity", "status": "FAIL", "reason": "x"},
        {"constraint_name": "ISO 9001", "status": "PASS", "reason": "x"},
    ])
    assert build_summary(comp) == "Partial match; 2 requirement(s) not met."


# ── build_match_reasons (PASS verdicts only) ─────────────────────────
def test_match_reasons_cert_pass_phrased_deterministically():
    comp = _comp([{"constraint_name": "AS9100", "status": "PASS", "reason": "LLM prose here"}])
    reasons = build_match_reasons(comp)
    assert reasons == ["Holds required AS9100 certification"]


def test_match_reasons_numeric_pass_reuses_data_built_reason():
    comp = _comp([{
        "constraint_name": "lead_time", "status": "PASS",
        "reason": "Lead time 58d is within the 60d limit",
    }])
    assert build_match_reasons(comp) == ["Lead time 58d is within the 60d limit"]


def test_match_reasons_excludes_fail_and_partial():
    comp = _comp([
        {"constraint_name": "ISO 9001", "status": "PASS", "reason": "r"},
        {"constraint_name": "FSC", "status": "FAIL", "reason": "r"},
        {"constraint_name": "BRC", "status": "PARTIAL", "reason": "r"},
    ])
    assert build_match_reasons(comp) == ["Holds required ISO 9001 certification"]


# ── build_concerns (FAIL/PARTIAL + low score) ────────────────────────
def test_concerns_cert_fail_phrased_deterministically():
    comp = _comp([{"constraint_name": "FSC", "status": "FAIL", "reason": "LLM prose"}])
    assert build_concerns(comp, semantic_score=0.9) == ["Does not hold required FSC certification"]


def test_concerns_cert_partial_unverified_quote_connects_to_task_1_4():
    comp = _comp([{
        "constraint_name": "FSC", "status": "PARTIAL",
        "reason": "supplier appears FSC aligned [downgraded: quote_not_in_source]",
        "quote_flag": "quote_not_in_source",
    }])
    assert build_concerns(comp, semantic_score=0.9) == [
        "FSC could not be verified from supplier text"
    ]


def test_concerns_capacity_fail_reuses_data_built_reason():
    comp = _comp([{
        "constraint_name": "capacity", "status": "FAIL",
        "reason": "Capacity 454,228 units/month is below minimum 500,000",
    }])
    assert build_concerns(comp, semantic_score=0.9) == [
        "Capacity 454,228 units/month is below minimum 500,000"
    ]


def test_concerns_appends_low_semantic_match():
    comp = _comp([{"constraint_name": "ISO 9001", "status": "PASS", "reason": "r"}])
    concerns = build_concerns(comp, semantic_score=0.3)
    assert "Limited semantic match to the query" in concerns


def test_concerns_no_low_semantic_when_score_ok():
    comp = _comp([{"constraint_name": "ISO 9001", "status": "PASS", "reason": "r"}])
    assert build_concerns(comp, semantic_score=0.8) == []


# ── build_explanation (the full assembled object) ────────────────────
def test_build_explanation_has_all_fields_and_no_llm():
    supplier = {
        "capacity_value": 454228.0, "capacity_unit": "units/month",
        "lead_time_days": 58, "certifications": ["ISO 9001"],
        "city": "Bremen", "country": "Germany",
    }
    comp = _comp([
        {"constraint_name": "ISO 9001", "status": "PASS", "reason": "r"},
        {"constraint_name": "FSC", "status": "FAIL", "reason": "r"},
    ])
    exp = build_explanation(supplier, "approved", comp, semantic_score=0.7)
    assert set(exp.keys()) == {"match_reasons", "concerns", "facts", "summary"}
    assert exp["match_reasons"] == ["Holds required ISO 9001 certification"]
    assert exp["concerns"] == ["Does not hold required FSC certification"]
    assert exp["facts"]["capacity"] == "454,228 units/month"
    assert exp["summary"] == "Partial match; 1 requirement(s) not met."
