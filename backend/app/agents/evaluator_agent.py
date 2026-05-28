"""
app/agents/evaluator_agent.py — Evaluates pipeline result quality.

PRODUCTION V2 (Reflexion pattern):
Evaluates the final ranked suppliers against the user's intent.
If the results are poor, it diagnoses the failure and decides on a retry strategy
(e.g., expanding search scope, relaxing constraints) to feed back into the loop.
"""

import json
import logging
import time

from app.agents.base import BaseAgent
from app.agents.state import AgentState
from app.core.config import settings

logger = logging.getLogger(__name__)

HIGH_QUALITY_THRESHOLD = 0.6

EVALUATOR_PROMPT = """You are the final quality control agent in a supplier discovery pipeline.

User Query: {raw_query}
Parsed Intent: {parsed_constraints}
Search Scope: {search_scope}

Top Results Returned:
{results_summary}

Analyze the quality of these results:
1. Are there at least 3 high-quality matches (score > 60%)?
2. Did we fail because constraints were too strict?
3. Did we fail because we only searched 'approved_only' suppliers?

Decide if the pipeline should RETRY with modified parameters.
You can only retry if you haven't exceeded the max retries.

Valid retry strategies:
- "expand_scope": Change search_scope from 'approved_only' to 'both' to search the web.
- "relax_constraints": Drop the least important constraint.
- "broaden_location": Increase the radius.
- "none": Accept the results as they are (or we already retried).

Return JSON only:
{{
  "verdict": "accept" | "retry" | "fail",
  "reasoning": "Explain your evaluation",
  "retry_strategy": "expand_scope" | "relax_constraints" | "broaden_location" | "none"
}}"""


class EvaluatorAgent(BaseAgent):
    """
    Evaluates the quality of ranked results and decides whether to retry.
    Uses LLM to diagnose poor result sets and suggest adjustments.
    """

    agent_name = "evaluator"

    def execute(self, state: AgentState) -> AgentState:
        start = time.time()

        ranked = state.get("ranked_suppliers", [])
        retries = state.get("evaluator_retries", 0)
        search_scope = state.get("search_scope", "approved_only")
        constraints = state.get("parsed_constraints") or {}

        # If we have great results or maxed out retries, skip LLM call
        high_quality_count = sum(1 for r in ranked if r["total_score"] > HIGH_QUALITY_THRESHOLD)
        if high_quality_count >= 3 or retries >= settings.EVALUATOR_MAX_RETRIES:
            state["evaluator_verdict"] = "auto_accept"
            state["evaluator_should_retry"] = False
            state["pipeline_status"] = "completed"

            reasoning = "Results are sufficient." if high_quality_count >= 3 else "Max retries reached."

            self._log_audit(
                state,
                action="evaluation_bypassed",
                input_summary=f"{len(ranked)} results, {high_quality_count} high quality. Retries: {retries}",
                output_summary="Accepted without LLM evaluation.",
                duration_ms=int((time.time() - start) * 1000),
                reasoning=reasoning,
            )
            return state

        # Build summary of results for LLM
        results_lines = []
        for r in ranked[:3]:
            results_lines.append(
                f"- Supplier: {r['supplier_id']} (Tier: {r['tier']})\n"
                f"  Score: {r['total_score']:.0%}\n"
                f"  Explanation: {r['explanation']}"
            )
        results_summary = "\n\n".join(results_lines) if results_lines else "NO RESULTS FOUND."

        prompt = EVALUATOR_PROMPT.format(
            raw_query=state["raw_query"],
            parsed_constraints=json.dumps({k: v for k, v in constraints.items() if v}),
            search_scope=search_scope,
            results_summary=results_summary,
        )

        try:
            raw = self.llm.complete_json(
                [{"role": "user", "content": prompt}],
                temperature=0.0,
            )
            eval_result = json.loads(raw)
            verdict = eval_result.get("verdict", "accept")
            strategy = eval_result.get("retry_strategy", "none")
            reasoning = eval_result.get("reasoning", "")
        except Exception as e:
            logger.warning("[evaluator] LLM failed: %s. Defaulting to accept.", e)
            verdict = "accept"
            strategy = "none"
            reasoning = "LLM evaluation failed."

        should_retry = False
        action_taken = "accepted"

        if verdict == "retry" and strategy != "none":
            should_retry = True
            state["evaluator_retries"] = retries + 1
            action_taken = f"retry ({strategy})"

            # Apply the strategy
            parsed = state.get("parsed_constraints") or {}
            state.setdefault("relaxed_constraints", [])
            if strategy == "expand_scope" and search_scope == "approved_only":
                state["search_scope"] = "both"
            elif strategy == "broaden_location" and parsed.get("location_radius_km"):
                parsed["location_radius_km"] *= 2
                state["parsed_constraints"] = parsed
                state["relaxed_constraints"].append("location_radius_km (evaluator expanded)")
            elif strategy == "relax_constraints":
                if parsed.get("certifications"):
                    parsed["certifications"] = []
                    state["parsed_constraints"] = parsed
                    state["relaxed_constraints"].append("certifications (evaluator dropped)")
                elif parsed.get("lead_time_max_days"):
                    parsed["lead_time_max_days"] = None
                    state["parsed_constraints"] = parsed
                    state["relaxed_constraints"].append("lead_time_max_days (evaluator dropped)")

        state["evaluator_verdict"] = verdict
        state["evaluator_should_retry"] = should_retry

        if not should_retry:
            state["pipeline_status"] = "completed"

        duration_ms = int((time.time() - start) * 1000)
        self._log_audit(
            state,
            action="evaluation_completed",
            input_summary=f"{len(ranked)} results, {high_quality_count} high quality.",
            output_summary=action_taken,
            duration_ms=duration_ms,
            reasoning=reasoning,
        )

        return state
