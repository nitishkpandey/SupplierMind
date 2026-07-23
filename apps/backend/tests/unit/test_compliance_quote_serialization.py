"""Lock the contract the thesis hallucination metric depends on:
a compliance verdict's evidence_quote and quote_flag must survive the
runner's asdict + JSON serialization into evaluation_results.json.

If someone drops those keys or switches ComplianceResult to a model that
strips unknown fields, this test fails before a benchmark run silently loses
the evidence quotes.
"""

from __future__ import annotations

import json
from dataclasses import asdict

from app.evaluation.metrics import QueryMetrics


def test_evidence_quote_and_flag_survive_serialization():
    compliance = [
        {
            "supplier_id": "s1",
            "compliance_results": [
                {
                    "constraint_name": "ISO 9001",
                    "status": "PASS",
                    "reason": "cited",
                    "confidence": 0.9,
                    "evidence_quote": "Holds ISO 9001",
                    "quote_flag": "quote_not_in_source",
                }
            ],
            "overall_pass": True,
            "has_partial": False,
            "pass_rate": 1.0,
        }
    ]
    m = QueryMetrics(
        query_id="q1", query_number=1, difficulty="medium",
        system_name="suppliermind", retrieved_ids=["s1"], ground_truth_ids=["s1"],
        precision_at_5=0.2, reciprocal_rank=1.0, constraint_satisfaction_rate=1.0,
        execution_time_ms=100, compliance_data=compliance,
    )

    roundtrip = json.loads(json.dumps(asdict(m), default=str))
    check = roundtrip["compliance_data"][0]["compliance_results"][0]

    assert check["evidence_quote"] == "Holds ISO 9001"
    assert check["quote_flag"] == "quote_not_in_source"
