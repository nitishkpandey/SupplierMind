"""
app/agents/compliance_agent.py — ReAct-pattern constraint validation.

THE REACT PATTERN (Yao et al., 2022 — in your proposal references):
Reason → Act → Observe → Reason → ...

For each supplier and each constraint:
1. REASON: What does this constraint require? What does this supplier offer?
2. ACT: Check the specific field (certifications, capacity, location, etc.)
3. OBSERVE: What did we find? Does it match?
4. OUTPUT: PASS, FAIL, or PARTIAL with a human-readable reason.

WHY NOT JUST SQL?
SQL can answer: "Is 'ISO 9001' in the certifications array?" → True/False
ReAct can answer: "Does this supplier's quality management meet ISO 9001 standards?"
The LLM can reason about:
- Equivalent standards (EMAS vs ISO 14001)
- Partial certification (ISO 9001 in progress)
- Inferred capacity from description text
- Expired certifications
"""

import json
import logging
import re
import time
from pathlib import Path
from typing import Optional

from app.agents.base import BaseAgent
from app.agents.state import AgentState, ComplianceResult, SupplierComplianceResult

logger = logging.getLogger(__name__)

# ── Certification taxonomy (Task 1.3) ─────────────────────────────────
# Human-verified lookup table that grounds cert-equivalence decisions in
# facts instead of LLM guesses. See app/data/cert_taxonomy.json.
_TAXONOMY_PATH = Path(__file__).resolve().parent.parent / "data" / "cert_taxonomy.json"

TAXONOMY_PASS_CONFIDENCE = 0.95   # supersession relationship — deterministic, no LLM
TAXONOMY_FAIL_CONFIDENCE = 0.95   # explicit NOT_equivalent — kills the hallucination


def _load_cert_taxonomy() -> dict[str, dict]:
    try:
        with open(_TAXONOMY_PATH, encoding="utf-8") as f:
            data = json.load(f)
        logger.info("Loaded cert taxonomy: %d entries", len(data))
        return data
    except Exception as e:
        logger.error("Failed to load cert taxonomy from %s: %s", _TAXONOMY_PATH, e)
        return {}


CERT_TAXONOMY: dict[str, dict] = _load_cert_taxonomy()


def _canonical_cert_token(raw: str) -> str:
    """Normalize a cert name to a comparable token.

    Drops version years (':2015'), the '/IEC' qualifier, and all non-alphanumerics
    so 'ISO 9001:2015', 'ISO/IEC 27001', and 'OEKO-TEX Standard 100' compare cleanly.
    """
    s = (raw or "").upper()
    s = re.sub(r":\s*\d{4}", "", s)      # ISO 9001:2015 → ISO 9001
    s = s.replace("ISO/IEC", "ISO")
    s = re.sub(r"[^A-Z0-9]", "", s)      # drop spaces, hyphens, slashes
    return s


# Precomputed {normalized_token: canonical_taxonomy_key}
_NORM_TO_KEY: dict[str, str] = {
    _canonical_cert_token(key): key for key in CERT_TAXONOMY
}

# Explicit aliases for cert spellings that don't resolve via substring matching
# (e.g. 'OEKO-TEX 100' → digits are non-adjacent after normalization).
_CERT_ALIASES: dict[str, str] = {
    "OEKOTEX100": "OEKO-TEX Standard 100",
}


def canonical_cert_key(raw: str) -> Optional[str]:
    """Resolve a raw cert string to its canonical taxonomy key, or None.

    Exact normalized match first, then explicit aliases, then a length-guarded
    substring match so 'OEKO-TEX' resolves to 'OEKO-TEX Standard 100' and
    'AS9100D' to 'AS9100', while short tokens like 'CE' (len < 4) only match
    exactly to avoid noise.
    """
    n = _canonical_cert_token(raw)
    if not n:
        return None
    if n in _NORM_TO_KEY:
        return _NORM_TO_KEY[n]
    if n in _CERT_ALIASES:
        return _CERT_ALIASES[n]
    if len(n) >= 4:
        for norm_key, key in _NORM_TO_KEY.items():
            if n in norm_key or norm_key in n:
                return key
    return None


def taxonomy_cert_verdict(
    required_cert: str, supplier_certs: list[str]
) -> Optional[dict]:
    """Decide a required cert against a supplier's certs using the taxonomy only.

    Returns a verdict dict {status, reason, matched_via} when the taxonomy is
    conclusive, else None (caller falls back to the LLM). Precedence:
      1. A supplier cert supersedes/contains the required cert  → PASS
      2. A supplier cert is explicitly NOT_equivalent to it     → FAIL
    """
    req_key = canonical_cert_key(required_cert)
    if req_key is None:
        return None  # required cert not in taxonomy — let the LLM handle it

    # 1. Supersession: supplier cert fully includes the required cert.
    for sup_cert in supplier_certs:
        sup_key = canonical_cert_key(sup_cert)
        if sup_key is None:
            continue
        supersedes = {
            canonical_cert_key(c)
            for c in CERT_TAXONOMY[sup_key].get("contains_or_supersedes", [])
        }
        if req_key in supersedes:
            return {
                "status": "PASS",
                "reason": f"{sup_key} contains/supersedes {req_key}",
                "matched_via": "contains_or_supersedes",
            }

    # 2. Explicit non-equivalence (checked both directions; taxonomy lists both).
    req_not_equiv = {
        canonical_cert_key(c)
        for c in CERT_TAXONOMY[req_key].get("NOT_equivalent_to", [])
    }
    for sup_cert in supplier_certs:
        sup_key = canonical_cert_key(sup_cert)
        if sup_key is None:
            continue
        sup_not_equiv = {
            canonical_cert_key(c)
            for c in CERT_TAXONOMY[sup_key].get("NOT_equivalent_to", [])
        }
        if req_key in sup_not_equiv or sup_key in req_not_equiv:
            return {
                "status": "FAIL",
                "reason": f"{sup_key} is explicitly not equivalent to {req_key}",
                "matched_via": "NOT_equivalent_to",
            }

    return None


def taxonomy_prompt_snippet(cert_names: list[str]) -> str:
    """Build an authoritative taxonomy block for the LLM prompt (step 5)."""
    seen: set[str] = set()
    lines: list[str] = []
    for name in cert_names:
        key = canonical_cert_key(name)
        if key is None or key in seen:
            continue
        seen.add(key)
        e = CERT_TAXONOMY[key]
        lines.append(
            f"- {key}: {e.get('what_it_covers', '')} "
            f"| supersedes: {e.get('contains_or_supersedes', []) or 'none'} "
            f"| NOT equivalent to: {e.get('NOT_equivalent_to', []) or 'none'}"
        )
    return "\n".join(lines)


# ── Quote-or-fail verification (Task 1.4) ─────────────────────────────
# Every LLM-issued PASS/PARTIAL must cite a verbatim phrase from the supplier's
# source text. The backend verifies the phrase exists (substring after
# normalization); unverifiable claims are downgraded to PARTIAL with a logged
# reason rather than silently accepted. Extends the numeric hallucination guard
# to textual compliance claims.

MIN_QUOTE_LEN = 12        # quotes shorter than this are too generic to verify
CONFIDENCE_FLOOR = 0.75   # LLM PASS below this is hedging → downgrade to PARTIAL

# Surrounding quotation marks the LLM may wrap around its evidence_quote.
_QUOTE_CHARS = "\"'“”‘’"


def _normalize_for_match(text: str) -> str:
    """Lowercase, strip surrounding quote marks, collapse whitespace runs."""
    s = (text or "").strip().strip(_QUOTE_CHARS).strip()
    s = s.lower()
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def build_evidence_pool(supplier: dict) -> str:
    """Concatenate a supplier's verifiable text — the only source an LLM
    evidence_quote may be drawn from.

    Sources: free-text description, certification_details values, the structured
    certifications list rendered as text, and per-field source_citation phrases
    (for web-discovered suppliers).
    """
    parts: list[str] = []

    if supplier.get("description"):
        parts.append(str(supplier["description"]))

    cert_details = supplier.get("certification_details")
    if isinstance(cert_details, dict) and cert_details:
        parts.append(" ".join(str(v) for v in cert_details.values() if v))
    elif cert_details:
        parts.append(str(cert_details))

    certs = supplier.get("certifications") or []
    if certs:
        parts.append("Certifications: " + ", ".join(str(c) for c in certs))

    citations = supplier.get("source_citations")
    if isinstance(citations, dict):
        for field in citations.values():
            if isinstance(field, dict) and field.get("source_phrase"):
                parts.append(str(field["source_phrase"]))

    return "\n".join(parts)


def verify_evidence_quote(evidence_quote: Optional[str], evidence_pool: str) -> dict:
    """Check an LLM evidence_quote against the supplier's evidence pool.

    Returns {"ok": bool, "flag": Optional[str]}. flag is the machine reason when
    the quote cannot be trusted: 'equivalence_unverifiable' (missing),
    'quote_too_short' (too generic), or 'quote_not_in_source' (fabrication).
    """
    if not evidence_quote or not str(evidence_quote).strip():
        return {"ok": False, "flag": "equivalence_unverifiable"}

    norm_quote = _normalize_for_match(evidence_quote)
    if len(norm_quote) < MIN_QUOTE_LEN:
        return {"ok": False, "flag": "quote_too_short"}

    if norm_quote not in _normalize_for_match(evidence_pool):
        return {"ok": False, "flag": "quote_not_in_source"}

    return {"ok": True, "flag": None}


def quote_or_fail_verdict(
    status: str, confidence: float, evidence_quote: Optional[str], evidence_pool: str
) -> tuple[str, Optional[str]]:
    """Apply the quote-or-fail rule to one LLM verdict.

    Returns (new_status, flag). flag is None when the verdict stands as-is, else a
    machine reason for the downgrade/annotation. FAIL is never touched (no positive
    claim to substantiate). PASS with an unverifiable quote or sub-floor confidence
    drops to PARTIAL; PARTIAL never escalates and never drops to FAIL — an
    unverifiable PARTIAL is only annotated.
    """
    if status not in ("PASS", "PARTIAL"):
        return status, None

    check = verify_evidence_quote(evidence_quote, evidence_pool)

    if status == "PASS":
        if not check["ok"]:
            return "PARTIAL", check["flag"]
        if (confidence or 0.0) < CONFIDENCE_FLOOR:
            return "PARTIAL", "low_confidence"
        return "PASS", None

    # status == "PARTIAL"
    if not check["ok"]:
        return "PARTIAL", "quote_unverifiable"
    return "PARTIAL", None


LEAD_TIME_GRACE_MULTIPLIER = 1.15   # 15% over limit → PARTIAL instead of FAIL
LOCATION_GRACE_MULTIPLIER = 1.10    # 10% outside radius → PARTIAL instead of FAIL
CAPACITY_PARTIAL_THRESHOLD = 0.80   # within 20% of min → PARTIAL instead of FAIL
CATEGORY_CONFIDENCE = 0.60          # below ranking hard-fail threshold of 0.8
LLM_CERT_CONFIDENCE = 0.80          # LLM reasoning certainty for cert equivalence

COMPLIANCE_BATCH_SYSTEM_PROMPT = """You are a procurement compliance expert. Return JSON only.

Validate multiple certifications for a single supplier in one response.

VERDICT RULES:
- PASS: Supplier holds a directly equivalent certification
- PARTIAL: Supplier holds a related but not equivalent certification
- FAIL: No related certification found

EVIDENCE RULE (mandatory for every PASS or PARTIAL):
- You MUST copy, VERBATIM, the exact phrase from the supplier text that justifies the verdict into "evidence_quote". Copy it character-for-character — do NOT paraphrase, summarize, translate, or reconstruct it.
- If you cannot find a supporting phrase in the supplier text, return FAIL (or leave evidence_quote empty). A PASS/PARTIAL without a verbatim quote found in the text WILL be rejected.
- Never invent or assume text that is not present.
- "confidence" is your certainty the verdict is correct, 0.0 to 1.0.

Return: {"results": [{"constraint_name": "...", "status": "PASS"|"PARTIAL"|"FAIL", "confidence": 0.0, "evidence_quote": "verbatim phrase from supplier text, or empty", "reason": "one sentence", "reasoning_trace": "THOUGHT→ACT→OBSERVE"}, ...]}"""

# Human-readable tails for the downgrade log line (thesis audit trail).
_QUOTE_FLAG_MESSAGES = {
    "quote_not_in_source": "LLM quote not found in supplier text",
    "quote_too_short": "LLM quote too short to verify",
    "equivalence_unverifiable": "LLM gave no supporting quote",
    "low_confidence": "LLM confidence below floor",
    "quote_unverifiable": "LLM quote could not be verified",
}


class ComplianceAgent(BaseAgent):
    """
    Validates each candidate supplier against all extracted constraints.
    Uses LLM reasoning for soft constraints, direct checks for hard constraints.

    HARD CONSTRAINTS (binary check):
    - Certifications: either in list or not
    - Category: either matches or not

    SOFT CONSTRAINTS (LLM reasoning):
    - Capacity: might be inferrable from description even if not in structured field
    - Lead time: supplier might state "typically X days" in description
    - Location: PARTIAL if slightly outside stated radius
    """

    agent_name = "compliance"

    # Per-query counters (reset at the start of each execute()).
    _llm_supplier_count: int = 0
    _short_circuit_count: int = 0

    def execute(self, state: AgentState) -> AgentState:
        candidate_ids = state.get("candidate_supplier_ids", [])
        constraints = state.get("parsed_constraints") or {}

        if not candidate_ids:
            state["compliance_results"] = []
            state["pipeline_status"] = "running"
            return state

        if not constraints:
            # No constraints to validate — all candidates pass
            state["compliance_results"] = [
                {
                    "supplier_id": sid,
                    "compliance_results": [],
                    "overall_pass": True,
                    "has_partial": False,
                    "pass_rate": 1.0,
                }
                for sid in candidate_ids
            ]
            state["pipeline_status"] = "running"
            return state

        start = time.time()

        # Reset per-query counters (instance is reused across pipeline runs)
        self._llm_supplier_count = 0
        self._short_circuit_count = 0

        # Fetch full supplier data from database
        suppliers = self._fetch_suppliers(candidate_ids)
        active_constraint_count = sum(1 for v in constraints.values() if v)
        logger.info("[compliance] Checking %d suppliers against %d constraint types",
                    len(suppliers), active_constraint_count)

        compliance_results: list[SupplierComplianceResult] = []

        for supplier in suppliers:
            supplier_id = str(supplier.get("id", ""))
            geo_distance = state.get("geo_distances", {}).get(supplier_id)

            result = self._check_supplier(
                supplier=supplier,
                constraints=constraints,
                geo_distance=geo_distance,
            )
            compliance_results.append(result)

        logger.info(
            "[compliance] %d/%d suppliers needed an LLM call; %d verdict(s) short-circuited deterministically",
            self._llm_supplier_count, len(suppliers), self._short_circuit_count,
        )

        # Sort: fully passing suppliers first, then partial, then failed
        compliance_results.sort(
            key=lambda r: (not r["overall_pass"], -r["pass_rate"])
        )

        duration_ms = int((time.time() - start) * 1000)
        pass_count = sum(1 for r in compliance_results if r["overall_pass"])
        partial_count = sum(1 for r in compliance_results if r["has_partial"] and not r["overall_pass"])

        self._log_audit(
            state,
            action="compliance_check_completed",
            input_summary=f"{len(suppliers)} suppliers, constraints: {list(constraints.keys())}",
            output_summary=f"PASS={pass_count}, PARTIAL={partial_count}, FAIL={len(suppliers)-pass_count-partial_count}",
            duration_ms=duration_ms,
            reasoning=(
                "Hybrid validation: deterministic short-circuit for unambiguous cases "
                f"({self._short_circuit_count} verdicts), LLM reserved for semantic cert "
                f"equivalence ({self._llm_supplier_count}/{len(suppliers)} suppliers)."
            ),
        )

        state["compliance_results"] = compliance_results
        state["pipeline_status"] = "running"
        return state

    def _check_supplier(
        self,
        supplier: dict,
        constraints: dict,
        geo_distance: Optional[float],
    ) -> SupplierComplianceResult:
        """Run all compliance checks for one supplier."""
        results: list[ComplianceResult] = []
        sc_count = 0   # short-circuited (deterministic, no-LLM) verdicts for this supplier

        # ── Hard check: Category ──────────────────────────────────────
        if constraints.get("category") and supplier.get("category"):
            status = "PASS" if supplier["category"] == constraints["category"] else "FAIL"
            results.append({
                "constraint_name": "category",
                "status": status,
                "reason": (
                    f"Supplier category '{supplier['category']}' "
                    f"{'matches' if status == 'PASS' else 'does not match'} "
                    f"required '{constraints['category']}'"
                ),
                "confidence": CATEGORY_CONFIDENCE,
            })

        # ── Short-circuit: Hard country mismatch ──────────────────────
        # Semantic search can surface out-of-country suppliers (structured
        # search filters by country, semantic does not). A confident country
        # mismatch is deterministic — FAIL at confidence 1.0, no LLM. Only a
        # mismatch is recorded; matches add no entry so pass_rate (and the
        # ranking score distribution) is unchanged for in-country suppliers.
        req_country = (constraints.get("location_country") or "").strip().casefold()
        sup_country = (supplier.get("country") or "").strip().casefold()
        if req_country and sup_country and req_country != sup_country \
                and req_country not in sup_country and sup_country not in req_country:
            results.append({
                "constraint_name": "country",
                "status": "FAIL",
                "reason": (
                    f"Supplier is in {supplier.get('country')}, "
                    f"required country is {constraints.get('location_country')}"
                ),
                "confidence": 1.0,
            })
            sc_count += 1

        # ── Hard check: Certifications ────────────────────────────────
        supplier_certs_raw = supplier.get("certifications") or []
        supplier_certs = [c.upper() for c in supplier_certs_raw]
        required_certs = constraints.get("certifications") or []
        certs_needing_llm: list[str] = []

        if required_certs and not supplier_certs:
            # Short-circuit: supplier lists NO certifications at all, so every
            # required cert FAILs deterministically. Skips the batch LLM call.
            for required_cert in required_certs:
                results.append({
                    "constraint_name": required_cert,
                    "status": "FAIL",
                    "reason": f"Supplier lists no certifications; {required_cert} required",
                    "confidence": 1.0,
                })
            sc_count += len(required_certs)
        else:
            for required_cert in required_certs:
                if required_cert.upper() in supplier_certs:
                    # Step 1 (Task 1.2): verbatim (case-insensitive) match → PASS, no LLM.
                    results.append({
                        "constraint_name": required_cert,
                        "status": "PASS",
                        "reason": f"Supplier holds {required_cert} certification",
                        "confidence": 1.0,
                    })
                    sc_count += 1
                    continue

                # Steps 3-4 (Task 1.3): taxonomy lookup before the LLM.
                # contains_or_supersedes → PASS; NOT_equivalent_to → FAIL.
                verdict = taxonomy_cert_verdict(required_cert, supplier_certs_raw)
                if verdict is not None:
                    results.append({
                        "constraint_name": required_cert,
                        "status": verdict["status"],
                        "reason": verdict["reason"],
                        "confidence": (
                            TAXONOMY_PASS_CONFIDENCE
                            if verdict["status"] == "PASS"
                            else TAXONOMY_FAIL_CONFIDENCE
                        ),
                    })
                    sc_count += 1
                    logger.info(
                        "[compliance] Supplier %r: taxonomy %s for %r (%s), no LLM",
                        supplier.get("name", supplier.get("id", "?")),
                        verdict["status"], required_cert, verdict["matched_via"],
                    )
                    continue

                # Step 5: genuinely ambiguous — defer to the LLM.
                certs_needing_llm.append(required_cert)

        # Single batched LLM call for ONLY the genuinely ambiguous certs
        # (no exact match, no taxonomy verdict, supplier has at least one cert).
        if certs_needing_llm:
            batch_results = self._llm_check_certifications_batch(
                certs_needing_llm, supplier
            )
            results.extend(batch_results)
            self._llm_supplier_count += 1

        # ── Numeric check: Capacity ───────────────────────────────────
        if constraints.get("capacity_min") and constraints.get("capacity_unit"):
            cap_result = self._check_capacity(
                supplier,
                constraints["capacity_min"],
                constraints["capacity_unit"],
            )
            results.append(cap_result)

        # ── Numeric check: Lead time ──────────────────────────────────
        if constraints.get("lead_time_max_days") and supplier.get("lead_time_days"):
            max_lt = constraints["lead_time_max_days"]
            actual_lt = supplier["lead_time_days"]
            if actual_lt <= max_lt:
                status = "PASS"
                reason = f"Lead time {actual_lt}d is within the {max_lt}d limit"
            elif actual_lt <= max_lt * LEAD_TIME_GRACE_MULTIPLIER:
                status = "PARTIAL"
                reason = f"Lead time {actual_lt}d slightly exceeds {max_lt}d limit"
            else:
                status = "FAIL"
                reason = f"Lead time {actual_lt}d exceeds {max_lt}d limit"
            results.append({
                "constraint_name": "lead_time",
                "status": status,
                "reason": reason,
                "confidence": 1.0,
            })

        # ── Geospatial check: Radius ──────────────────────────────────
        if constraints.get("location_radius_km") and geo_distance is not None:
            radius = constraints["location_radius_km"]
            if geo_distance <= radius:
                status = "PASS"
                reason = f"Supplier is {geo_distance:.1f}km away, within {radius}km radius"
            elif geo_distance <= radius * LOCATION_GRACE_MULTIPLIER:
                status = "PARTIAL"
                reason = f"Supplier is {geo_distance:.1f}km away, slightly outside {radius}km radius"
            else:
                status = "FAIL"
                reason = f"Supplier is {geo_distance:.1f}km away, outside {radius}km radius"
            results.append({
                "constraint_name": "location_radius",
                "status": status,
                "reason": reason,
                "confidence": 1.0,
            })

        # ── Calculate overall result ──────────────────────────────────
        has_fail = any(r["status"] == "FAIL" for r in results)
        has_partial = any(r["status"] == "PARTIAL" for r in results)
        pass_count = sum(1 for r in results if r["status"] == "PASS")
        pass_rate = pass_count / len(results) if results else 1.0

        if sc_count:
            self._short_circuit_count += sc_count
            logger.info(
                "[compliance] Supplier %r: %d verdict(s) short-circuited (deterministic, no LLM)",
                supplier.get("name", supplier.get("id", "?")), sc_count,
            )

        return {
            "supplier_id": str(supplier.get("id", "")),
            "compliance_results": results,
            "overall_pass": not has_fail,
            "has_partial": has_partial,
            "pass_rate": pass_rate,
        }

    def _llm_check_certifications_batch(
        self, certs_to_check: list[str], supplier: dict
    ) -> list[ComplianceResult]:
        """
        Single LLM call to validate ALL unmatched certs for one supplier.
        Replaces per-cert calls — 1 call per supplier regardless of cert count.
        """
        supplier_certs = supplier.get("certifications", []) or []
        taxonomy_block = taxonomy_prompt_snippet(certs_to_check + supplier_certs)
        taxonomy_section = (
            f"\nAUTHORITATIVE CERTIFICATION TAXONOMY (consult this; do NOT claim "
            f"equivalence unless supported by the 'supersedes' relationship below):\n"
            f"{taxonomy_block}\n"
            if taxonomy_block else ""
        )

        # The evidence pool is the ONLY text the LLM may quote from, and exactly
        # what the backend verifies the evidence_quote against (Task 1.4).
        evidence_pool = build_evidence_pool(supplier)

        prompt = f"""Supplier does NOT hold these certifications (no exact match found): {certs_to_check}

SUPPLIER TEXT (you may ONLY quote verbatim from the text below):
\"\"\"
{evidence_pool[:1500]}
\"\"\"
{taxonomy_section}
For each required certification, check if the supplier holds an equivalent or related one.
For any PASS or PARTIAL, copy the exact supporting phrase from the SUPPLIER TEXT into evidence_quote.

Return JSON object:
{{"results": [
  {{"constraint_name": "<cert>", "status": "PASS"|"PARTIAL"|"FAIL", "confidence": 0.0, "evidence_quote": "verbatim phrase from supplier text, or empty", "reason": "one sentence", "reasoning_trace": "THOUGHT→ACT→OBSERVE"}},
  ...one entry per cert in {certs_to_check}
]}}"""

        try:
            raw = self.llm.complete_json(
                [
                    {"role": "system", "content": COMPLIANCE_BATCH_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
            )
            data = json.loads(raw)
            items = data.get("results", [])
            if not isinstance(items, list):
                raise ValueError("LLM returned non-list results")

            supplier_label = supplier.get("name", supplier.get("id", "?"))
            output: list[ComplianceResult] = []
            returned_names = set()
            for item in items:
                name = item.get("constraint_name", "")
                returned_names.add(name)
                raw_status = item.get("status", "FAIL")
                evidence_quote = (item.get("evidence_quote") or "").strip()
                reason = item.get("reason", f"No {name} found")
                try:
                    confidence = float(item.get("confidence", LLM_CERT_CONFIDENCE))
                except (TypeError, ValueError):
                    confidence = LLM_CERT_CONFIDENCE

                # Quote-or-fail (Task 1.4): a PASS/PARTIAL must cite a verbatim
                # phrase that exists in the supplier text, else it is downgraded.
                new_status, flag = quote_or_fail_verdict(
                    raw_status, confidence, evidence_quote, evidence_pool
                )

                result: ComplianceResult = {
                    "constraint_name": name,
                    "status": new_status,
                    "reason": reason,
                    "confidence": confidence,
                }
                if evidence_quote:
                    result["evidence_quote"] = evidence_quote
                if flag:
                    result["quote_flag"] = flag
                    detail = _QUOTE_FLAG_MESSAGES.get(flag, "verdict not verifiable")
                    if new_status != raw_status:
                        result["reason"] = f"{reason} [downgraded: {flag}]"
                        logger.info(
                            "[compliance] Supplier %r constraint %r: %s downgraded to %s (%s) - %s",
                            supplier_label, name, raw_status, new_status, flag, detail,
                        )
                    else:
                        result["reason"] = f"{reason} [unverified: {flag}]"
                        logger.info(
                            "[compliance] Supplier %r constraint %r: %s kept, quote unverifiable (%s) - %s",
                            supplier_label, name, raw_status, flag, detail,
                        )
                output.append(result)

            # Fill in any certs the LLM omitted
            for cert in certs_to_check:
                if cert not in returned_names:
                    logger.warning("[compliance] LLM omitted cert %r from batch response", cert)
                    output.append({
                        "constraint_name": cert,
                        "status": "FAIL",
                        "reason": f"{cert} not found in certifications list",
                        "confidence": 1.0,
                    })

            logger.info(
                "[compliance] Supplier %r: 1 LLM call for %d unmatched cert(s): %s",
                supplier_label,
                len(certs_to_check),
                certs_to_check,
            )
            return output

        except Exception as e:
            logger.warning("[compliance] Batch LLM cert check failed: %s", e)
            return [
                {
                    "constraint_name": cert,
                    "status": "FAIL",
                    "reason": f"{cert} not found in certifications list",
                    "confidence": 1.0,
                }
                for cert in certs_to_check
            ]

    def _check_capacity(
        self, supplier: dict, min_cap: float, cap_unit: str
    ) -> ComplianceResult:
        """Check if supplier meets minimum capacity requirement."""
        supplier_cap = supplier.get("capacity_value")
        supplier_unit = supplier.get("capacity_unit", "")

        if supplier_cap is None:
            return {
                "constraint_name": "capacity",
                "status": "PARTIAL",
                "reason": "Capacity data not available in supplier profile",
                "confidence": 0.5,
            }

        if supplier_unit != cap_unit:
            return {
                "constraint_name": "capacity",
                "status": "PARTIAL",
                "reason": f"Capacity unit mismatch: supplier has {supplier_unit}, required {cap_unit}",
                "confidence": 0.6,
            }

        if supplier_cap >= min_cap:
            return {
                "constraint_name": "capacity",
                "status": "PASS",
                "reason": f"Capacity {supplier_cap:,.0f} {supplier_unit} meets minimum {min_cap:,.0f}",
                "confidence": 1.0,
            }
        elif supplier_cap >= min_cap * CAPACITY_PARTIAL_THRESHOLD:
            return {
                "constraint_name": "capacity",
                "status": "PARTIAL",
                "reason": f"Capacity {supplier_cap:,.0f} is slightly below minimum {min_cap:,.0f} {supplier_unit}",
                "confidence": 0.9,
            }
        else:
            return {
                "constraint_name": "capacity",
                "status": "FAIL",
                "reason": f"Capacity {supplier_cap:,.0f} {supplier_unit} is below minimum {min_cap:,.0f}",
                "confidence": 1.0,
            }

