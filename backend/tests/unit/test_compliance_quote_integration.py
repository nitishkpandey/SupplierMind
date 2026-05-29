"""Task 1.4 — quote-or-fail wired into the batch LLM compliance path.

The LLM is the one external boundary, so it is stubbed with canned JSON; the
real _llm_check_certifications_batch parsing + verification runs unchanged. No
Groq cost. Proves the fabrication catch (spec Test 2) end-to-end through the
agent, not just the pure helper.
"""

import json

from app.agents.compliance_agent import ComplianceAgent


class _StubLLM:
    """Returns a fixed JSON string, mimicking LLMClient.complete_json."""

    def __init__(self, payload: dict):
        self._raw = json.dumps(payload)

    def complete_json(self, messages, temperature=0.0):
        return self._raw


def _agent_with_llm(payload: dict) -> ComplianceAgent:
    # Skip __init__ (avoids constructing a live LLM client) and inject the stub.
    agent = ComplianceAgent.__new__(ComplianceAgent)
    agent.llm = _StubLLM(payload)
    return agent


SUPPLIER = {
    "id": "s1",
    "name": "Bavaria Boxes GmbH",
    "description": "We manufacture cardboard boxes and run ISO 9001 quality systems.",
    "certifications": ["ISO 9001"],
    "certification_details": {},
    "source_citations": {},
}


def test_fabricated_quote_is_downgraded_end_to_end():
    # LLM claims FSC PASS but cites a phrase that is NOT in the supplier text.
    payload = {"results": [{
        "constraint_name": "FSC",
        "status": "PASS",
        "confidence": 0.9,
        "evidence_quote": "audited FSC chain-of-custody forest management on site",
        "reason": "supplier appears FSC aligned",
    }]}
    agent = _agent_with_llm(payload)

    results = agent._llm_check_certifications_batch(["FSC"], SUPPLIER)

    assert len(results) == 1
    r = results[0]
    assert r["constraint_name"] == "FSC"
    assert r["status"] == "PARTIAL"               # downgraded from PASS
    assert r["quote_flag"] == "quote_not_in_source"
    assert "quote_not_in_source" in r["reason"]


def test_legitimate_quote_keeps_pass_end_to_end():
    payload = {"results": [{
        "constraint_name": "TUV cert",
        "status": "PASS",
        "confidence": 0.9,
        "evidence_quote": "ISO 9001 quality systems",   # present in description
        "reason": "ISO 9001 evidenced in supplier text",
    }]}
    agent = _agent_with_llm(payload)

    results = agent._llm_check_certifications_batch(["TUV cert"], SUPPLIER)

    assert results[0]["status"] == "PASS"
    assert results[0].get("quote_flag") is None


def test_missing_quote_is_downgraded_end_to_end():
    payload = {"results": [{
        "constraint_name": "FSC",
        "status": "PASS",
        "confidence": 0.95,
        "evidence_quote": "",
        "reason": "claims FSC",
    }]}
    agent = _agent_with_llm(payload)

    results = agent._llm_check_certifications_batch(["FSC"], SUPPLIER)

    assert results[0]["status"] == "PARTIAL"
    assert results[0]["quote_flag"] == "equivalence_unverifiable"
