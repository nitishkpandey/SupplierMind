"""Generic production-quality regressions for constraint-heavy supplier search.

These tests pin the behaviors that broke in the E2E suite without coupling the
fixes to the benchmark query numbers.
"""

from __future__ import annotations

import json
import time

import pytest

from app.agents.compliance_agent import (
    ComplianceAgent,
    canonical_cert_key,
    product_fit_verdict,
)
from app.agents.evaluator_agent import EvaluatorAgent
from app.agents.external_discovery_agent import (
    ExternalDiscoveryAgent,
    normalise_supplier_name_for_dedupe,
)
from app.agents.parser_agent import ParserAgent
from app.agents.ranking_agent import RankingAgent, build_match_reasons
from app.core.config import settings
from app.services import supplier_extraction
from app.services.supplier_extraction import SupplierExtractionService
from app.services.web_search import WebSearchService


def test_parser_preserves_certification_explicitly_named_in_query_when_finish_loses_it():
    raw_query = (
        "Find ISO 9001 certified office furniture manufacturers in Germany "
        "that can deliver within 30 days"
    )
    llm_payload = {
        "product_type": "office furniture",
        "product_keywords": ["office furniture"],
        "category_hint": "office_supplies",
        "location_country": "Germany",
        "certifications": [],
        "lead_time_max_days": 30,
    }
    trace = [
        {
            "action": "canonicalize_certification",
            "observation": {
                "resolved": True,
                "input": "ISO 9001",
                "canonical": "ISO 9001",
            },
        }
    ]

    constraints = ParserAgent.__new__(ParserAgent)._normalise_constraints(
        llm_payload,
        trace=trace,
        raw_query=raw_query,
    )

    assert constraints["certifications"] == ["ISO 9001"]


def test_evaluator_never_drops_explicit_hard_constraints_on_retry():
    class FakeLLM:
        def complete_json(self, messages, **kwargs):
            return json.dumps(
                {
                    "verdict": "retry",
                    "reasoning": "No exact result yet.",
                    "retry_strategy": "relax_constraints",
                }
            )

    agent = EvaluatorAgent.__new__(EvaluatorAgent)
    agent.llm = FakeLLM()
    agent._log_audit = lambda *args, **kwargs: None
    state = {
        "raw_query": (
            "Find ISO 9001 certified office furniture manufacturers in Germany "
            "that can deliver within 30 days"
        ),
        "parsed_constraints": {
            "product_type": "office furniture",
            "location_country": "Germany",
            "certifications": ["ISO 9001"],
            "lead_time_max_days": 30,
            "query_type": "compliance_critical",
        },
        "search_scope": "both",
        "ranked_suppliers": [],
        "evaluator_retries": 0,
        "audit_log": [],
    }

    out = agent.execute(state)

    assert out["evaluator_should_retry"] is False
    assert out["pipeline_status"] == "completed"
    assert out["parsed_constraints"]["certifications"] == ["ISO 9001"]
    assert out["parsed_constraints"]["lead_time_max_days"] == 30
    assert out["relaxed_constraints"] == []


def test_evaluator_zero_results_with_hard_constraints_does_not_wait_for_llm():
    class ExplodingLLM:
        def complete_json(self, messages, **kwargs):
            raise AssertionError("strict zero-result searches should finish deterministically")

    agent = EvaluatorAgent.__new__(EvaluatorAgent)
    agent.llm = ExplodingLLM()
    agent._log_audit = lambda *args, **kwargs: None
    state = {
        "raw_query": (
            "Find ISO 9001 certified office furniture manufacturers in Germany "
            "that can deliver within 30 days"
        ),
        "parsed_constraints": {
            "product_type": "office furniture",
            "location_country": "Germany",
            "certifications": ["ISO 9001"],
            "lead_time_max_days": 30,
        },
        "search_scope": "both",
        "ranked_suppliers": [],
        "evaluator_retries": 0,
        "audit_log": [],
    }

    out = agent.execute(state)

    assert out["evaluator_should_retry"] is False
    assert out["evaluator_verdict"] == "fail"
    assert out["pipeline_status"] == "completed"
    assert out["parsed_constraints"]["certifications"] == ["ISO 9001"]
    assert out["parsed_constraints"]["lead_time_max_days"] == 30


def test_evaluator_llm_timeout_fails_closed_without_blocking(monkeypatch):
    monkeypatch.setattr(settings, "EVALUATOR_LLM_TIMEOUT_SECONDS", 0.01, raising=False)
    seen_timeouts: list[float | None] = []

    class TimeoutAwareLLM:
        def complete_json(self, messages, **kwargs):
            timeout = kwargs.get("timeout")
            seen_timeouts.append(timeout)
            if timeout == 0.01:
                raise TimeoutError("evaluator LLM call timed out")
            time.sleep(0.05)
            return json.dumps(
                {
                    "verdict": "retry",
                    "reasoning": "Too slow to be user-critical.",
                    "retry_strategy": "expand_scope",
                }
            )

    agent = EvaluatorAgent.__new__(EvaluatorAgent)
    agent.llm = TimeoutAwareLLM()
    agent._log_audit = lambda *args, **kwargs: None
    state = {
        "raw_query": "Find suppliers for industrial packaging",
        "parsed_constraints": {"product_type": "industrial packaging"},
        "search_scope": "approved_only",
        "ranked_suppliers": [{"total_score": 0.2, "semantic_score": 0.2, "supplier_id": "s1", "tier": "approved", "explanation": "weak"}],
        "evaluator_retries": 0,
        "audit_log": [],
    }

    start = time.monotonic()
    out = agent.execute(state)
    elapsed = time.monotonic() - start

    assert elapsed < 0.04
    assert seen_timeouts == [0.01]
    assert out["evaluator_should_retry"] is False
    assert out["evaluator_verdict"] == "accept"
    assert out["pipeline_status"] == "completed"


def test_parser_recovers_office_furniture_from_constraint_soup_product():
    raw_query = (
        "Find office furniture suppliers in Berlin with ISO 9001 certification "
        "and can deliver within 14 days."
    )
    llm_payload = {
        "product_type": "certification and can, days",
        "product_keywords": ["certification", "days"],
        "category_hint": "office_supplies",
        "location_city": "Berlin",
        "location_country": "Germany",
        "certifications": ["ISO 9001"],
        "lead_time_max_days": 14,
    }

    constraints = ParserAgent.__new__(ParserAgent)._normalise_constraints(
        llm_payload,
        trace=[],
        raw_query=raw_query,
    )

    assert constraints["product_type"] == "office furniture"
    assert "office furniture" in constraints["product_keywords"]


def test_parser_recovers_metal_from_radius_and_lead_time_soup_product():
    raw_query = "Metal suppliers within 25 km of Bremen with lead time under 21 days"
    llm_payload = {
        "product_type": "km of bremen, days",
        "product_keywords": ["km", "Bremen", "days"],
        "category_hint": "metals",
        "location_city": "Bremen",
        "location_country": "Germany",
        "location_radius_km": 25,
        "lead_time_max_days": 21,
    }

    constraints = ParserAgent.__new__(ParserAgent)._normalise_constraints(
        llm_payload,
        trace=[],
        raw_query=raw_query,
    )

    assert constraints["product_type"] == "metal"
    assert "metal" in constraints["product_keywords"]


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("DIN EN ISO 9001", "ISO 9001"),
        ("ISO 9001:2015", "ISO 9001"),
        ("AS9100D", "AS9100"),
        ("IATF 16949-2016", "IATF 16949"),
        ("TISAX AL3", "TISAX"),
        ("DIN EN 6789", "DIN EN 6789"),
        ("BIFMA/ANSI X5.1", "BIFMA/ANSI"),
        ("ANSI/BIFMA e3", "BIFMA/ANSI"),
    ],
)
def test_certification_real_world_variants_canonicalize(raw, expected):
    assert canonical_cert_key(raw) == expected


def test_compliance_rejects_office_furniture_query_for_foundry_candidate():
    result = ComplianceAgent.__new__(ComplianceAgent)._check_supplier(
        supplier={
            "id": "foundry",
            "name": "Berlin Foundry GmbH",
            "description": "Casts bronze and steel parts for industrial customers.",
            "category": "metals",
            "city": "Berlin",
            "country": "Germany",
            "certifications": ["ISO 9001:2015"],
        },
        constraints={
            "product_type": "office furniture",
            "product_keywords": ["office furniture", "desk", "chair"],
            "category_hint": "office_supplies",
            "location_city": "Berlin",
            "location_country": "Germany",
            "certifications": ["ISO 9001"],
        },
        geo_distance=None,
    )

    assert result["overall_pass"] is False
    assert any(
        r["constraint_name"] == "product_fit" and r["status"] == "FAIL"
        for r in result["compliance_results"]
    )


@pytest.mark.parametrize(
    "supplier",
    [
        {
            "id": "packaging",
            "name": "Frankfurt Pack Solutions GmbH",
            "description": "Manufactures industrial packaging solutions and corrugated cardboard.",
            "category": "packaging",
        },
        {
            "id": "automation",
            "name": "Broetje-Automation",
            "description": "Aerospace automation and manufacturing equipment.",
            "category": "machinery",
        },
    ],
)
def test_product_fit_rejects_generic_word_overlap_for_office_furniture(supplier):
    verdict = product_fit_verdict(
        supplier,
        {
            "product_type": "office furniture",
            "product_keywords": [
                "office furniture",
                "furniture",
                "office equipment",
                "workspace solutions",
            ],
            "category_hint": "office_supplies",
        },
    )

    assert verdict is not None
    assert verdict["status"] == "FAIL"


def test_product_fit_reason_uses_verdict_reason_not_certification_template():
    reasons = build_match_reasons({
        "compliance_results": [
            {
                "constraint_name": "product_fit",
                "status": "PASS",
                "reason": "Supplier product scope matches wrenches and hand tools.",
            }
        ]
    })

    assert reasons == ["Supplier product scope matches wrenches and hand tools."]
    assert "certification" not in reasons[0].casefold()


def test_ranking_excludes_known_city_mismatch_for_city_focused_query(monkeypatch):
    agent = RankingAgent.__new__(RankingAgent)
    bremen_id = "bremen-office"
    berlin_id = "berlin-foundry"

    monkeypatch.setattr(
        agent,
        "_fetch_suppliers",
        lambda ids: [
            {
                "id": bremen_id,
                "name": "Bremen Office GmbH",
                "description": "Office furniture supplier in Bremen.",
                "category": "office_supplies",
                "country": "Germany",
                "city": "Bremen",
                "website": "https://bremen.example",
            },
            {
                "id": berlin_id,
                "name": "Berlin Foundry GmbH",
                "description": "Metal castings and foundry services.",
                "category": "metals",
                "country": "Germany",
                "city": "Berlin",
                "website": "https://berlin.example",
            },
        ],
    )

    state = {
        "parsed_constraints": {
            "product_type": "office furniture",
            "category_hint": "office_supplies",
            "location_city": "Bremen",
            "location_country": "Germany",
            "query_type": "general",
        },
        "compliance_results": [
            {
                "supplier_id": bremen_id,
                "pass_rate": 1.0,
                "overall_pass": True,
                "compliance_results": [],
            },
            {
                "supplier_id": berlin_id,
                "pass_rate": 1.0,
                "overall_pass": True,
                "compliance_results": [],
            },
        ],
        "semantic_scores": {bremen_id: 0.7, berlin_id: 0.95},
        "geo_distances": {},
        "tier_assignments": {bremen_id: "approved", berlin_id: "approved"},
        "audit_log": [],
    }

    result = agent.execute(state)

    assert [r["supplier_id"] for r in result["ranked_suppliers"]] == [bremen_id]


def test_ranking_dedupes_visible_results_by_normalized_supplier_name(monkeypatch):
    agent = RankingAgent.__new__(RankingAgent)
    hazet_a = "hazet-gmbh"
    hazet_b = "hazet-short"
    wera = "wera"

    monkeypatch.setattr(
        agent,
        "_fetch_suppliers",
        lambda ids: [
            {
                "id": hazet_a,
                "name": "HAZET GmbH & Co. KG",
                "description": "German hand tools and torque tools manufacturer.",
                "category": "tools_hardware",
                "country": "Germany",
                "city": "Remscheid",
                "website": "https://hazet.example",
            },
            {
                "id": hazet_b,
                "name": "HAZET",
                "description": "Hand tools and socket wrenches.",
                "category": "tools_hardware",
                "country": "Germany",
                "city": "Remscheid",
                "website": "https://hazet.example",
            },
            {
                "id": wera,
                "name": "Wera Tools",
                "description": "German screwdrivers, socket tools, and torque tools.",
                "category": "tools_hardware",
                "country": "Germany",
                "city": "Wuppertal",
                "website": "https://wera.example",
            },
        ],
    )

    compliance_results = [
        {
            "supplier_id": supplier_id,
            "pass_rate": 1.0,
            "overall_pass": True,
            "compliance_results": [
                {
                    "constraint_name": "product_fit",
                    "status": "PASS",
                    "reason": "Supplier product scope matches hand tools.",
                }
            ],
        }
        for supplier_id in (hazet_a, hazet_b, wera)
    ]

    result = agent.execute({
        "parsed_constraints": {
            "product_type": "hand tools",
            "category_hint": "tools_hardware",
            "location_country": "Germany",
            "query_type": "general",
        },
        "compliance_results": compliance_results,
        "semantic_scores": {hazet_a: 0.95, hazet_b: 0.9, wera: 0.85},
        "geo_distances": {},
        "tier_assignments": {
            hazet_a: "approved",
            hazet_b: "approved",
            wera: "approved",
        },
        "audit_log": [],
    })

    assert [r["supplier_id"] for r in result["ranked_suppliers"]] == [hazet_a, wera]


def test_web_search_city_is_in_every_query_and_runs_basic_depth(monkeypatch):
    queries_seen: list[str] = []

    service = WebSearchService.__new__(WebSearchService)
    service._client = object()
    service._search_raw = lambda query, max_results=10, timeout_seconds=None: (
        queries_seen.append(query)
        or [{
            "url": f"https://example{len(queries_seen)}.de",
            "title": "Example",
            "content": "Berlin office furniture supplier",
            "score": 0.9,
        }]
    )

    results = service.search_suppliers(
        category="office_supplies",
        country="Germany",
        city="Berlin",
        certifications=["ISO 9001"],
        product_terms=["office furniture"],
        raw_query="office furniture suppliers in Berlin",
        max_results=2,
    )

    assert len(results) == 2
    assert queries_seen
    assert all("Berlin" in query for query in queries_seen)
    assert all("Germany" in query for query in queries_seen)


def test_certification_query_runs_before_global_cap_is_applied():
    service = WebSearchService.__new__(WebSearchService)
    seen: list[str] = []
    service._client = object()
    service._search_raw = lambda query, max_results=10, timeout_seconds=None: (
        seen.append(query)
        or [{
            "url": f"https://example{len(seen)}.de",
            "title": "Company",
            "content": query,
            "score": 0.9,
        }]
    )

    service.search_suppliers(
        category="office_supplies",
        country="Germany",
        certifications=["ISO 9001"],
        product_terms=["office furniture"],
        max_results=2,
    )

    assert any("ISO 9001" in query for query in seen)


def test_external_discovery_caps_web_results_even_when_env_is_higher(monkeypatch):
    class FakeWebSearch:
        is_available = True

        def __init__(self):
            self.max_results: int | None = None

        def search_suppliers(self, **kwargs):
            self.max_results = kwargs["max_results"]
            return []

    fake_search = FakeWebSearch()
    agent = ExternalDiscoveryAgent.__new__(ExternalDiscoveryAgent)
    agent.web_search = fake_search
    agent._log_audit = lambda *args, **kwargs: None

    monkeypatch.setattr(settings, "ENABLE_EXTERNAL_DISCOVERY", True)
    monkeypatch.setattr(settings, "EXTERNAL_DISCOVERY_MAX_RESULTS", 10)

    agent.execute({
        "raw_query": "hand tools suppliers in Germany",
        "parsed_constraints": {
            "product_type": "hand tools",
            "category_hint": "tools_hardware",
            "location_country": "Germany",
        },
        "audit_log": [],
    })

    assert fake_search.max_results == 6


def test_supplier_extraction_bounds_optional_fallback_page_probes(monkeypatch):
    fetched_urls: list[str] = []

    def fake_fetch(url: str) -> str:
        fetched_urls.append(url)
        return ""

    monkeypatch.setattr(supplier_extraction, "fetch_page_content", fake_fetch)
    service = SupplierExtractionService.__new__(SupplierExtractionService)

    assert service._discover_location_from_site("https://example.de/products") == {}
    assert len(fetched_urls) == 3

    fetched_urls.clear()
    assert service._discover_certifications_from_site("https://example.de/products", "") == {}
    assert len(fetched_urls) == 2


@pytest.mark.parametrize(
    "left,right",
    [
        ("HAZET GmbH & Co. KG", "HAZET"),
        ("Munich Electronics GmbH", "Munich Electronics AG"),
        ("Stuttgart Automotive GmbH", "Stuttgart Automotive"),
    ],
)
def test_supplier_dedupe_normalises_legal_suffixes(left, right):
    assert normalise_supplier_name_for_dedupe(left) == normalise_supplier_name_for_dedupe(right)


def test_evaluator_prompt_does_not_claim_approved_only_when_scope_is_both():
    prompts: list[str] = []

    class FakeLLM:
        def complete_json(self, messages, **kwargs):
            prompts.append(messages[-1]["content"])
            return json.dumps(
                {
                    "verdict": "accept",
                    "reasoning": "Scope already includes web discovery.",
                    "retry_strategy": "none",
                }
            )

    agent = EvaluatorAgent.__new__(EvaluatorAgent)
    agent.llm = FakeLLM()
    agent._log_audit = lambda *args, **kwargs: None

    state = {
        "raw_query": "office furniture suppliers in Berlin",
        "parsed_constraints": {"product_type": "office furniture", "location_city": "Berlin"},
        "search_scope": "both",
        "ranked_suppliers": [
            {
                "supplier_id": "supplier-1",
                "tier": "pending_review",
                "total_score": 0.45,
                "semantic_score": 0.3,
                "explanation": "Limited semantic match to office furniture.",
            }
        ],
        "evaluator_retries": 0,
        "audit_log": [],
    }

    agent.execute(state)

    assert prompts
    assert "only searched 'approved_only'" not in prompts[0]
    assert "expand_scope" not in prompts[0]
