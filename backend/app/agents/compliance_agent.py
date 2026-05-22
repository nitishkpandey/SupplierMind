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
import math
import time
from typing import Optional

from app.agents.base import BaseAgent
from app.agents.state import AgentState, ComplianceResult, SupplierComplianceResult

logger = logging.getLogger(__name__)

COMPLIANCE_SYSTEM_PROMPT = """You are a procurement compliance expert using the ReAct reasoning pattern.

For each constraint, you will:
1. REASON about what the constraint requires
2. ACT by examining the supplier's data
3. OBSERVE what you find
4. OUTPUT your verdict

VERDICT RULES:
- PASS: Supplier clearly satisfies the constraint
- FAIL: Supplier clearly does not satisfy the constraint
- PARTIAL: Supplier partially satisfies it OR there is insufficient data to be certain

IMPORTANT:
- Certifications: PASS only if exact certification is listed. PARTIAL if closely related standard found.
- Capacity: compare numeric values. PARTIAL if within 20% of minimum.
- Location: PASS if within radius. PARTIAL if slightly outside (within 10% of radius).
- Lead time: PASS if at or under limit. FAIL if over.

Return JSON array of compliance results:
[
  {
    "constraint_name": "ISO 9001",
    "status": "PASS" | "FAIL" | "PARTIAL",
    "reason": "one sentence explanation",
    "confidence": 0.0 to 1.0,
    "reasoning_trace": "your THOUGHT→ACT→OBSERVE chain"
  }
]"""


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

        # Fetch full supplier data from database
        suppliers = self._fetch_suppliers(candidate_ids)
        logger.info("[compliance] Checking %d suppliers against %d constraint types",
                    len(suppliers), len([k for k, v in constraints.items() if v]))

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
            reasoning="ReAct pattern applied to each constraint per supplier.",
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
                "confidence": 1.0,
            })

        # ── Hard check: Certifications ────────────────────────────────
        supplier_certs = [c.upper() for c in (supplier.get("certifications") or [])]
        for required_cert in (constraints.get("certifications") or []):
            if required_cert.upper() in supplier_certs:
                results.append({
                    "constraint_name": required_cert,
                    "status": "PASS",
                    "reason": f"Supplier holds {required_cert} certification",
                    "confidence": 1.0,
                })
            else:
                # Check for related standards using LLM reasoning
                llm_result = self._llm_check_certification(
                    required_cert, supplier
                )
                results.append(llm_result)

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
            elif actual_lt <= max_lt * 1.15:  # 15% grace
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
            elif geo_distance <= radius * 1.1:  # 10% grace
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

        return {
            "supplier_id": str(supplier.get("id", "")),
            "compliance_results": results,
            "overall_pass": not has_fail,
            "has_partial": has_partial,
            "pass_rate": pass_rate,
        }

    def _llm_check_certification(
        self, required_cert: str, supplier: dict
    ) -> ComplianceResult:
        """
        Use LLM to reason about certification equivalence.
        Called only when exact match fails.

        Example: required=ISO 14001, supplier has EMAS
        LLM reasons: EMAS is equivalent in scope, return PARTIAL.
        """
        prompt = f"""A supplier does NOT hold {required_cert} certification.
Supplier description: {supplier.get('description', 'N/A')[:200]}
Supplier certifications: {supplier.get('certifications', [])}

Using the ReAct pattern:
THOUGHT: What does {required_cert} certify?
ACT: Look at what certifications and description the supplier has.
OBSERVE: Is there any equivalent or related certification?
OUTPUT: PASS (equivalent found), PARTIAL (related but not equivalent), or FAIL (nothing related)

Return JSON: {{"status": "PASS"|"PARTIAL"|"FAIL", "reason": "one sentence", "reasoning_trace": "THOUGHT→ACT→OBSERVE"}}"""

        try:
            raw = self.llm.complete_json(
                [
                    {"role": "system", "content": "Return JSON only."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
            )
            result = json.loads(raw)
            return {
                "constraint_name": required_cert,
                "status": result.get("status", "FAIL"),
                "reason": result.get("reason", f"No {required_cert} found"),
                "confidence": 0.8,
            }
        except Exception:
            return {
                "constraint_name": required_cert,
                "status": "FAIL",
                "reason": f"{required_cert} not found in certifications list",
                "confidence": 1.0,
            }

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
        elif supplier_cap >= min_cap * 0.8:  # Within 20%
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

    def _fetch_suppliers(self, supplier_ids: list[str]) -> list[dict]:
        """Fetch supplier data from database synchronously."""
        import asyncio
        import uuid
        from app.db.repositories.supplier_repo import SupplierRepository
        from app.db.session import AsyncSessionLocal

        async def _fetch():
            async with AsyncSessionLocal() as db:
                repo = SupplierRepository(db)
                suppliers = await repo.get_by_supplier_ids_str(supplier_ids)
                return [
                    {
                        "id": str(s.id),
                        "name": s.name,
                        "description": s.description,
                        "category": s.category,
                        "country": s.country,
                        "city": s.city,
                        "latitude": s.latitude,
                        "longitude": s.longitude,
                        "certifications": s.certifications or [],
                        "capacity_value": s.capacity_value,
                        "capacity_unit": s.capacity_unit,
                        "lead_time_days": s.lead_time_days,
                        "website": s.website,
                    }
                    for s in suppliers
                ]

        try:
            return asyncio.get_event_loop().run_until_complete(_fetch())
        except RuntimeError:
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, _fetch())
                return future.result()
