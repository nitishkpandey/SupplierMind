"""Phase D bug 3 — a candidate with any FAIL compliance verdict must be hard
-excluded from the final ranked result set, not merely score-penalised.

The exclusion is keyed on the verdict status itself, so if the evaluator
downgrades a FAIL to PARTIAL (with reasoning) the candidate is no longer blocked
— a PARTIAL verdict is not a FAIL.
"""

from app.agents.ranking_agent import RankingAgent, has_blocking_fail


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


def test_low_score_eligible_suppliers_are_not_padded_into_results(monkeypatch):
    agent = RankingAgent.__new__(RankingAgent)
    supplier_ids = [f"s{i}" for i in range(1, 8)]

    monkeypatch.setattr(
        agent,
        "_fetch_suppliers",
        lambda ids: [
            {
                "id": sid,
                "name": f"Supplier {sid}",
                "description": "Relevant but sparse supplier.",
                "category": "metals",
                "country": "Germany",
                "city": "Munich",
                "certifications": ["AS9100"],
            }
            for sid in ids
        ],
    )

    state = {
        "parsed_constraints": {"query_type": "general"},
        "compliance_results": [
            {
                "supplier_id": sid,
                "pass_rate": 0.0,
                "overall_pass": False,
                "compliance_results": [
                    {
                        "constraint_name": "AS9100",
                        "status": "PARTIAL",
                        "reason": "Needs confirmation",
                    }
                ],
            }
            for sid in supplier_ids
        ],
        "semantic_scores": {sid: 0.1 for sid in supplier_ids},
        "geo_distances": {},
        "tier_assignments": {sid: "approved" for sid in supplier_ids},
        "audit_log": [],
    }

    result = agent.execute(state)

    assert result["ranked_suppliers"] == []


def test_high_score_eligible_suppliers_still_rank(monkeypatch):
    agent = RankingAgent.__new__(RankingAgent)
    supplier_ids = [f"s{i}" for i in range(1, 4)]

    monkeypatch.setattr(
        agent,
        "_fetch_suppliers",
        lambda ids: [
            {
                "id": sid,
                "name": f"Supplier {sid}",
                "description": "Bronze supplier with verified monthly tonnage and lead time.",
                "category": "metals",
                "country": "Germany",
                "city": "Bremen",
                "certifications": ["ISO 9001"],
                "capacity_value": 5,
                "capacity_unit": "metric_tons/month",
                "lead_time_days": 14,
                "website": "https://example.test",
            }
            for sid in ids
        ],
    )

    state = {
        "parsed_constraints": {"query_type": "general"},
        "compliance_results": [
            {
                "supplier_id": sid,
                "pass_rate": 1.0,
                "overall_pass": True,
                "compliance_results": [
                    {
                        "constraint_name": "capacity",
                        "status": "PASS",
                        "reason": "Capacity meets minimum",
                    },
                    {
                        "constraint_name": "lead_time",
                        "status": "PASS",
                        "reason": "Lead time meets limit",
                    },
                ],
            }
            for sid in supplier_ids
        ],
        "semantic_scores": {sid: 0.8 for sid in supplier_ids},
        "geo_distances": {},
        "tier_assignments": {sid: "approved" for sid in supplier_ids},
        "audit_log": [],
    }

    result = agent.execute(state)

    assert [r["supplier_id"] for r in result["ranked_suppliers"]] == supplier_ids


def test_city_query_ranks_exact_city_above_higher_semantic_country_match(monkeypatch):
    agent = RankingAgent.__new__(RankingAgent)
    bremen_id = "bremen-supplier"
    berlin_id = "berlin-supplier"

    monkeypatch.setattr(
        agent,
        "_fetch_suppliers",
        lambda ids: [
            {
                "id": berlin_id,
                "name": "Berlin Metals Ltd.",
                "description": "Metal supplier elsewhere in Germany.",
                "category": "metals",
                "country": "Germany",
                "city": "Berlin",
                "certifications": ["ISO 9001"],
                "capacity_value": 30000,
                "capacity_unit": "kg/month",
                "lead_time_days": 30,
                "website": "https://berlin.example",
                "contact_email": "sales@berlin.example",
            },
            {
                "id": bremen_id,
                "name": "Bremen Metall GmbH",
                "description": "Metal supplier located in Bremen.",
                "category": "metals",
                "country": "Germany",
                "city": "Bremen",
                "certifications": [],
                "capacity_value": None,
                "capacity_unit": None,
                "lead_time_days": None,
                "website": "https://bremen.example",
                "contact_email": None,
            },
        ],
    )

    state = {
        "parsed_constraints": {
            "query_type": "general",
            "location_city": "Bremen",
            "location_country": "Germany",
        },
        "compliance_results": [
            {
                "supplier_id": berlin_id,
                "pass_rate": 1.0,
                "overall_pass": True,
                "compliance_results": [],
            },
            {
                "supplier_id": bremen_id,
                "pass_rate": 1.0,
                "overall_pass": True,
                "compliance_results": [],
            },
        ],
        "semantic_scores": {berlin_id: 0.9, bremen_id: 0.6},
        "geo_distances": {},
        "tier_assignments": {berlin_id: "approved", bremen_id: "pending_review"},
        "newly_discovered_supplier_ids": [bremen_id],
        "exclude_pending": False,
        "audit_log": [],
    }

    result = agent.execute(state)

    ranked = result["ranked_suppliers"]
    assert ranked[0]["supplier_id"] == bremen_id
    assert ranked[0]["proximity_score"] == 1.0
    assert next(r for r in ranked if r["supplier_id"] == berlin_id)["proximity_score"] == 0.0
