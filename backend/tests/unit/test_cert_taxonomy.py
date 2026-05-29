"""Task 1.3 — cert taxonomy grounding. Pure-function tests, no LLM cost.

Verifies the human-curated taxonomy loads, canonicalizes spelling variants, and
returns correct deterministic verdicts (supersession PASS, explicit non-equivalence
FAIL, genuine ambiguity → None → LLM).
"""

import pytest

from app.agents.compliance_agent import (
    CERT_TAXONOMY,
    canonical_cert_key,
    taxonomy_cert_verdict,
)


def test_taxonomy_loads_at_least_20_certs():
    assert len(CERT_TAXONOMY) >= 20


@pytest.mark.parametrize("raw,expected", [
    ("ISO 9001:2015", "ISO 9001"),
    ("ISO/IEC 27001", "ISO 27001"),
    ("AS9100D", "AS9100"),
    ("OEKO-TEX", "OEKO-TEX Standard 100"),
    ("OEKO-TEX 100", "OEKO-TEX Standard 100"),
])
def test_canonicalization_of_spelling_variants(raw, expected):
    assert canonical_cert_key(raw) == expected


def test_gots_does_not_satisfy_oeko_tex():
    # The headline anti-hallucination case.
    v = taxonomy_cert_verdict("OEKO-TEX", ["GOTS"])
    assert v is not None and v["status"] == "FAIL"


def test_as9100_supersedes_iso_9001():
    v = taxonomy_cert_verdict("ISO 9001", ["AS9100"])
    assert v is not None and v["status"] == "PASS"


def test_iso_22000_supersedes_haccp():
    v = taxonomy_cert_verdict("HACCP", ["ISO 22000"])
    assert v is not None and v["status"] == "PASS"


def test_pefc_does_not_satisfy_fsc():
    v = taxonomy_cert_verdict("FSC", ["PEFC"])
    assert v is not None and v["status"] == "FAIL"


def test_iso_9001_does_not_supersede_as9100_defers_to_llm():
    # Genuine ambiguity must fall through to the LLM, not be force-decided.
    assert taxonomy_cert_verdict("AS9100", ["ISO 9001"]) is None
