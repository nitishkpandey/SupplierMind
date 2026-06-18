"""Task 1.4 — quote-or-fail rule for LLM equivalence claims.

Pure-function tests, no live LLM cost. Covers the evidence pool builder,
the verbatim-quote verifier, and the downgrade decision table.
"""

from app.agents.compliance_agent import (
    CONFIDENCE_FLOOR,
    MIN_QUOTE_LEN,
    build_evidence_pool,
    quote_or_fail_verdict,
    verify_evidence_quote,
)


# ── build_evidence_pool ──────────────────────────────────────────────
def test_evidence_pool_concatenates_all_four_sources():
    supplier = {
        "description": "We make organic cotton fabric.",
        "certification_details": {"ISO 9001": "Certified by TUV since 2019"},
        "certifications": ["ISO 9001", "GOTS"],
        "source_citations": {
            "certifications": {
                "url": "http://x.com",
                "source_phrase": "holds FSC chain-of-custody certification",
            }
        },
    }
    pool = build_evidence_pool(supplier)
    assert "organic cotton fabric" in pool
    assert "Certified by TUV since 2019" in pool
    assert "ISO 9001" in pool and "GOTS" in pool
    assert "FSC chain-of-custody" in pool


def test_evidence_pool_handles_missing_fields():
    pool = build_evidence_pool({"description": "only a description"})
    assert pool == "only a description" or "only a description" in pool


def test_evidence_pool_empty_supplier_returns_empty_string():
    assert build_evidence_pool({}).strip() == ""


# ── verify_evidence_quote ────────────────────────────────────────────
def test_quote_present_verbatim_verifies():
    pool = "We source FSC-certified paper for all packaging."
    r = verify_evidence_quote("FSC-certified paper", pool)
    assert r["ok"] is True
    assert r["flag"] is None


def test_quote_verifies_after_whitespace_and_case_normalization():
    pool = "We   source FSC-CERTIFIED\n  paper here."
    r = verify_evidence_quote('  "fsc-certified paper"  ', pool)
    assert r["ok"] is True


def test_missing_quote_flags_unverifiable():
    assert verify_evidence_quote("", "some pool text here")["flag"] == "equivalence_unverifiable"
    assert verify_evidence_quote(None, "some pool text here")["flag"] == "equivalence_unverifiable"


def test_too_short_quote_flagged():
    pool = "ISO 9001 quality systems certified here."
    r = verify_evidence_quote("ISO 9001", pool)  # 8 chars < MIN_QUOTE_LEN
    assert r["ok"] is False
    assert r["flag"] == "quote_too_short"
    assert len("ISO 9001") < MIN_QUOTE_LEN


def test_quote_not_in_source_flagged_fabrication():
    pool = "We manufacture cardboard boxes in Bavaria."
    r = verify_evidence_quote("certified to FSC chain-of-custody standard", pool)
    assert r["ok"] is False
    assert r["flag"] == "quote_not_in_source"


# ── quote_or_fail_verdict (downgrade table) ──────────────────────────
POOL = "We source FSC-certified paper and run ISO 9001 quality systems."


def test_pass_with_valid_quote_stays_pass():
    status, flag = quote_or_fail_verdict("PASS", 0.9, "FSC-certified paper", POOL)
    assert status == "PASS"
    assert flag is None


def test_pass_with_fabricated_quote_downgrades_to_partial():
    # THE KEY TEST (spec Test 2): LLM cites text not in the source.
    status, flag = quote_or_fail_verdict(
        "PASS", 0.9, "audited FSC forest management on site", POOL
    )
    assert status == "PARTIAL"
    assert flag == "quote_not_in_source"


def test_pass_with_missing_quote_downgrades_to_partial():
    status, flag = quote_or_fail_verdict("PASS", 0.9, "", POOL)
    assert status == "PARTIAL"
    assert flag == "equivalence_unverifiable"


def test_pass_with_too_short_quote_downgrades_to_partial():
    status, flag = quote_or_fail_verdict("PASS", 0.9, "FSC", POOL)
    assert status == "PARTIAL"
    assert flag == "quote_too_short"


def test_pass_with_low_confidence_but_valid_quote_downgrades():
    status, flag = quote_or_fail_verdict(
        "PASS", CONFIDENCE_FLOOR - 0.01, "FSC-certified paper", POOL
    )
    assert status == "PARTIAL"
    assert flag == "low_confidence"


def test_partial_with_valid_quote_stays_partial_unflagged():
    status, flag = quote_or_fail_verdict("PARTIAL", 0.6, "ISO 9001 quality systems", POOL)
    assert status == "PARTIAL"
    assert flag is None


def test_partial_with_invalid_quote_stays_partial_but_flagged():
    status, flag = quote_or_fail_verdict("PARTIAL", 0.6, "audited on site by DNV", POOL)
    assert status == "PARTIAL"
    assert flag == "quote_unverifiable"


def test_fail_is_never_touched_and_needs_no_quote():
    status, flag = quote_or_fail_verdict("FAIL", 0.5, "", POOL)
    assert status == "FAIL"
    assert flag is None
