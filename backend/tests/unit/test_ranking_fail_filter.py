"""Phase D bug 3 — a candidate with any FAIL compliance verdict must be hard
-excluded from the final ranked result set, not merely score-penalised.

The exclusion is keyed on the verdict status itself, so if the evaluator
downgrades a FAIL to PARTIAL (with reasoning) the candidate is no longer blocked
— a PARTIAL verdict is not a FAIL.
"""

from app.agents.ranking_agent import has_blocking_fail


def test_any_fail_blocks_candidate():
    comp = {"supplier_id": "s1", "compliance_results": [
        {"constraint_name": "ISO 9001", "status": "PASS"},
        {"constraint_name": "country", "status": "FAIL"},
    ]}
    assert has_blocking_fail(comp) is True


def test_all_pass_is_eligible():
    comp = {"supplier_id": "s2", "compliance_results": [
        {"constraint_name": "ISO 9001", "status": "PASS"},
    ]}
    assert has_blocking_fail(comp) is False


def test_partial_does_not_block():
    # A downgrade-to-PARTIAL lifts the block.
    comp = {"supplier_id": "s3", "compliance_results": [
        {"constraint_name": "lead_time", "status": "PARTIAL"},
        {"constraint_name": "ISO 9001", "status": "PASS"},
    ]}
    assert has_blocking_fail(comp) is False


def test_empty_results_is_eligible():
    assert has_blocking_fail({"supplier_id": "s4", "compliance_results": []}) is False
