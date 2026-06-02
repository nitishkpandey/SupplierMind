"""app/agents/parser_agent.py — Task 3.1: ReAct-pattern constraint extractor.

The Parser is the first agent in the system that does *real* ReAct reasoning
(Yao et al. 2022, arXiv:2210.03629) rather than executing a fixed pipeline. At
each step the LLM emits a Thought + Action + Action Input; the loop dispatches
to a registered Tool, captures the Observation, and feeds it back. The loop
terminates on a Finish action whose payload IS the final structured
constraints dict, or after MAX_REACT_ITERATIONS — at which point a fallback
extraction reuses whatever was learned during the trace.

The agent stays backward compatible: state["parsed_constraints"] keeps the
shape every downstream agent (discovery, compliance, ranking, evaluator)
already reads.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from app.agents.base import BaseAgent
from app.agents.state import AgentState
from app.agents.tools import ToolRegistry, build_default_registry
from app.db.repositories.query_repo import QueryRepository
from app.db.session import SyncSessionLocal

logger = logging.getLogger(__name__)

# ── Loop hyperparameters ─────────────────────────────────────────────
MAX_REACT_ITERATIONS = 6
CLARIFICATION_THRESHOLD = 0.5
LLM_MAX_TOKENS_PER_STEP = 768

# ── Final constraint schema — what Finish must emit ──────────────────
FINISH_SCHEMA = {
    "product_type": "specific product or service name (string)",
    "product_keywords": ["3-7 diverse search terms (list[str])"],
    "industry_context": "industry name (string) or null",
    "buyer_intent": "manufacturer | distributor | service_provider | any",
    "category_hint": (
        "one of: metals, electronics, tools_hardware, logistics, textiles, "
        "chemicals, machinery, packaging, food_ingredients, software_services, "
        "construction_materials, office_supplies, or null"
    ),
    "location_city": "city name (string) or null",
    "location_country": "country name (string) or null",
    "location_region": "broader region (string) or null",
    "location_lat": "latitude (number) or null — only if geocode_location was called",
    "location_lng": "longitude (number) or null — only if geocode_location was called",
    "location_radius_km": "radius in km (number) or null",
    "certifications": ["explicit canonical cert names (list[str])"],
    "capacity_min": "capacity floor (number) or null",
    "capacity_unit": "capacity unit (string) or null",
    "lead_time_max_days": "lead-time ceiling in days (number) or null",
    "query_type": "geographic_priority | compliance_critical | capability_match | general",
    "complexity": "simple | medium | complex",
    "original_language": "en | de | hi | other",
    "confidence": "0.0-1.0 (number)",
    "clarification_needed": "boolean",
    "clarification_question": "string or null",
}


# ── ReAct response model ─────────────────────────────────────────────


@dataclass
class _ReActStep:
    thought: str
    action: str
    action_input: dict


_THOUGHT_RE = re.compile(r"Thought:\s*(.+?)(?=\n\s*Action:|\Z)", re.DOTALL)
_ACTION_RE = re.compile(r"Action:\s*([A-Za-z_][A-Za-z0-9_]*)", re.DOTALL)
_ACTION_INPUT_RE = re.compile(r"Action Input:\s*(\{.*?\}|\[.*?\])\s*$", re.DOTALL)


def _parse_react_response(text: str) -> _ReActStep:
    """Parse one Thought/Action/Action Input block. Raises ValueError on bad shape."""
    thought_m = _THOUGHT_RE.search(text)
    action_m = _ACTION_RE.search(text)
    if not thought_m or not action_m:
        raise ValueError(
            f"Could not parse ReAct response (missing Thought or Action). "
            f"First 200 chars: {text[:200]!r}"
        )
    input_m = _ACTION_INPUT_RE.search(text)
    args: dict = {}
    if input_m:
        try:
            parsed = json.loads(input_m.group(1))
            if isinstance(parsed, dict):
                args = parsed
        except json.JSONDecodeError as e:
            raise ValueError(
                f"Action Input is not valid JSON: {e}. First 200 chars: "
                f"{input_m.group(1)[:200]!r}"
            )
    return _ReActStep(
        thought=thought_m.group(1).strip(),
        action=action_m.group(1).strip(),
        action_input=args,
    )


# ── Prompt builder ───────────────────────────────────────────────────


def _build_system_prompt(tool_registry: ToolRegistry) -> str:
    tools_block = tool_registry.list_for_prompt()
    schema_block = json.dumps(FINISH_SCHEMA, indent=2)
    return f"""You are a procurement-query parser running a ReAct loop. Your job is to
convert a natural-language procurement query into a structured set of
constraints. You can read context, call tools, and finish.

You have access to these tools:
{tools_block}

Plus the special action `Finish` which ends the loop and returns the final
constraints. `Finish` takes the constraints object itself as Action Input.

Follow this format STRICTLY. Emit exactly one Thought, one Action, and one
Action Input per turn:

Thought: <one short sentence reasoning about what to figure out next>
Action: <tool_name or Finish>
Action Input: <JSON object — must be valid JSON>

After each action you will receive:
Observation: <tool output as JSON>

Use observations to enrich the constraints. When you have enough information,
emit:

Thought: I have enough to extract the constraints.
Action: Finish
Action Input: <the constraints JSON, conforming to the schema below>

Rules:
- Do NOT call the same tool with the same arguments twice. If you need a
  result you already have, reuse it.
- Maximum {MAX_REACT_ITERATIONS} iterations total. After that the loop ends
  with whatever was learned.
- If a tool fails, the Observation will contain an "error" field. Do not
  retry the same call; either try different arguments or finish.
- Always finish with `Finish`. Never end mid-thought.
- The Finish Action Input MUST be a single JSON object matching this schema:

{schema_block}

Fields you cannot determine should be null (do not omit them). Lists default
to []. Confidence is your subjective certainty in the extraction; set
clarification_needed = true when confidence < {CLARIFICATION_THRESHOLD}.
"""


# ── The agent ─────────────────────────────────────────────────────────


class ParserAgent(BaseAgent):
    agent_name = "parser"

    def __init__(self, tool_registry: ToolRegistry | None = None) -> None:
        super().__init__()
        self.tools = tool_registry if tool_registry is not None else build_default_registry()

    # The orchestrator calls .run() (in BaseAgent) which wraps this.
    def execute(self, state: AgentState) -> AgentState:
        start = time.time()
        raw_query = state["raw_query"]
        user_id = state.get("user_id", "")

        memory_context = self._load_user_memory(user_id)
        system_prompt = _build_system_prompt(self.tools)
        user_open = self._build_initial_user_message(raw_query, memory_context)

        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_open},
        ]

        trace: list[dict[str, Any]] = []
        seen_calls: set[tuple[str, str]] = set()
        terminated_by = "max_iterations"
        final_constraints: dict | None = None
        loop_error: str | None = None

        for iteration in range(MAX_REACT_ITERATIONS):
            try:
                response = self.llm.complete(
                    messages,
                    max_tokens=LLM_MAX_TOKENS_PER_STEP,
                    temperature=0.0,
                )
            except Exception as e:
                loop_error = f"llm_call_failed: {type(e).__name__}: {e}"
                logger.error("[parser/react] LLM call failed at iteration %d: %s", iteration, e)
                terminated_by = "llm_error"
                break

            try:
                step = _parse_react_response(response)
            except ValueError as e:
                # Recoverable parse failure: tell the LLM to try again.
                logger.warning("[parser/react] parse failure at iter %d: %s", iteration, e)
                trace.append({
                    "iteration": iteration,
                    "thought": None,
                    "action": None,
                    "action_input": None,
                    "observation": {"error": "parse_failed", "detail": str(e)},
                    "raw_response_head": response[:200],
                })
                messages.append({"role": "assistant", "content": response})
                messages.append({
                    "role": "user",
                    "content": (
                        "Observation: {\"error\": \"Your response did not match the "
                        "required Thought/Action/Action Input format. Please try again.\"}"
                    ),
                })
                continue

            entry: dict[str, Any] = {
                "iteration": iteration,
                "thought": step.thought,
                "action": step.action,
                "action_input": step.action_input,
            }

            if step.action == "Finish":
                final_constraints = step.action_input or {}
                entry["observation"] = {"status": "finished"}
                trace.append(entry)
                terminated_by = "finish"
                break

            # Same-args dedup: refuse a repeat of (tool, args) we already saw.
            args_key = json.dumps(step.action_input, sort_keys=True, default=str)
            call_key = (step.action, args_key)
            if call_key in seen_calls:
                entry["observation"] = {
                    "error": "duplicate_call",
                    "detail": (
                        f"You already called {step.action} with these args. Do not "
                        f"repeat; reuse the prior observation or move on."
                    ),
                }
                trace.append(entry)
                messages.append({"role": "assistant", "content": response})
                messages.append({
                    "role": "user",
                    "content": f"Observation: {json.dumps(entry['observation'])}",
                })
                continue
            seen_calls.add(call_key)

            # Dispatch to the tool.
            try:
                tool = self.tools.get(step.action)
            except KeyError:
                entry["observation"] = {
                    "error": "unknown_tool",
                    "detail": f"No tool named {step.action!r}. Available: {self.tools.names()}",
                }
            else:
                try:
                    result = tool.fn(**step.action_input)
                    entry["observation"] = result if isinstance(result, (dict, list)) else {"value": result}
                except TypeError as e:
                    entry["observation"] = {"error": "bad_args", "detail": str(e)}
                except Exception as e:  # noqa: BLE001 — surface any tool failure as observation
                    logger.warning("[parser/react] tool %s raised: %s", step.action, e)
                    entry["observation"] = {"error": type(e).__name__, "detail": str(e)}

            trace.append(entry)
            messages.append({"role": "assistant", "content": response})
            messages.append({
                "role": "user",
                "content": f"Observation: {json.dumps(entry['observation'], default=str)}",
            })

        # Build the constraints dict from Finish payload, or fall back.
        if final_constraints is None:
            final_constraints = self._fallback_extract(raw_query, trace)
            if loop_error is None and terminated_by == "max_iterations":
                logger.info(
                    "[parser/react] hit max iterations (%d); using fallback extraction",
                    MAX_REACT_ITERATIONS,
                )

        constraints = self._normalise_constraints(final_constraints, trace)
        confidence = float(final_constraints.get("confidence", 0.5) or 0.5)
        clarification_needed = (
            bool(final_constraints.get("clarification_needed"))
            or confidence < CLARIFICATION_THRESHOLD
        )

        duration_ms = int((time.time() - start) * 1000)
        tools_used = [t["action"] for t in trace if t.get("action") and t["action"] != "Finish"]
        summary = (
            f"react iterations={len(trace)} terminated_by={terminated_by} "
            f"tools={tools_used} confidence={confidence:.2f}"
        )

        self._log_audit(
            state,
            action="react_loop_completed" if terminated_by == "finish" else "react_loop_degraded",
            input_summary=raw_query[:200],
            output_summary=summary,
            duration_ms=duration_ms,
            reasoning=(
                f"ReAct loop terminated via {terminated_by} after "
                f"{len(trace)} iteration(s); tools selected: "
                f"{tools_used or 'none'}"
            ),
            input_snapshot={
                "raw_query": raw_query,
                "memory_context": memory_context,
                "tool_registry": self.tools.names(),
            },
            output_snapshot={
                "terminated_by": terminated_by,
                "iterations": len(trace),
                "tools_called": tools_used,
                "trace": trace,
                "parsed_constraints": constraints,
                "loop_error": loop_error,
            },
        )

        state["react_trace"] = trace
        state["react_terminated_by"] = terminated_by
        state["parsed_constraints"] = constraints
        state["detected_language"] = constraints.get("original_language") or "en"
        state["needs_clarification"] = clarification_needed
        state["clarification_question"] = (
            final_constraints.get("clarification_question") if clarification_needed else None
        )
        state["pipeline_status"] = (
            "needs_clarification" if clarification_needed else "running"
        )

        logger.info(
            "[parser/react] product=%r certs=%s loc=%s type=%s tools=%s iters=%d",
            constraints.get("product_type"),
            constraints.get("certifications") or [],
            constraints.get("location_name") or constraints.get("location_country"),
            constraints.get("query_type"),
            tools_used,
            len(trace),
        )
        return state

    # ── helpers ──────────────────────────────────────────────────────

    def _build_initial_user_message(self, raw_query: str, memory_context: Optional[str]) -> str:
        if memory_context:
            return (
                "User's recent successful queries (context only, do not copy):\n"
                f"{memory_context}\n\n"
                f"Current query: {raw_query}\n\n"
                "Begin. Emit your first Thought / Action / Action Input."
            )
        return (
            f"Current query: {raw_query}\n\n"
            "Begin. Emit your first Thought / Action / Action Input."
        )

    def _load_user_memory(self, user_id: str) -> Optional[str]:
        if not user_id:
            return None
        try:
            user_uuid = uuid.UUID(user_id)
        except ValueError:
            return None
        try:
            with SyncSessionLocal() as db:
                recent = QueryRepository.get_user_recent_queries_sync(
                    db, user_uuid, limit=5
                )
                if not recent:
                    return None
                return "\n".join(f"  • {q.raw_query[:100]}" for q in recent[:3])
        except Exception as e:  # noqa: BLE001 — memory is opportunistic context
            logger.debug("[parser] Memory load failed: %s", e)
            return None

    def _normalise_constraints(self, raw: dict, trace: list[dict]) -> dict:
        """Map the LLM's Finish payload to the ParsedConstraints shape.

        Tolerant of missing keys and of legacy "location" nesting. Promotes
        a geocode_location observation into location_lat/lng if the LLM
        forgot to include them in the Finish payload.
        """
        raw = dict(raw or {})
        # Legacy nested shape (Week 1/2 prompt produced "location": {...}).
        if isinstance(raw.get("location"), dict):
            loc = raw.pop("location")
            raw.setdefault("location_city", loc.get("city"))
            raw.setdefault("location_country", loc.get("country"))
            raw.setdefault("location_region", loc.get("region"))
            raw.setdefault("location_radius_km", loc.get("radius_km"))
        if isinstance(raw.get("capacity"), dict):
            cap = raw.pop("capacity")
            raw.setdefault("capacity_min", cap.get("min_value"))
            raw.setdefault("capacity_unit", cap.get("unit"))

        # If a geocode_location observation succeeded but the LLM dropped
        # lat/lng from Finish, restore them from the trace.
        if raw.get("location_lat") is None or raw.get("location_lng") is None:
            for step in trace:
                if step.get("action") == "geocode_location":
                    obs = step.get("observation") or {}
                    if obs.get("found"):
                        raw.setdefault("location_lat", obs.get("lat"))
                        raw.setdefault("location_lng", obs.get("lng"))
                        raw.setdefault("location_city", raw.get("location_city") or obs.get("city"))
                        raw.setdefault(
                            "location_country", raw.get("location_country") or obs.get("country")
                        )

        # Same trick for canonicalize_certification: if the LLM kept the raw
        # cert name but the canonical key is known, swap to canonical.
        certs_in = list(raw.get("certifications") or [])
        if certs_in:
            canonical_map: dict[str, str] = {}
            for step in trace:
                if step.get("action") == "canonicalize_certification":
                    obs = step.get("observation") or {}
                    if obs.get("resolved") and obs.get("input") and obs.get("canonical"):
                        canonical_map[obs["input"].strip().lower()] = obs["canonical"]
            normalised_certs: list[str] = []
            for c in certs_in:
                if not isinstance(c, str):
                    continue
                key = c.strip().lower()
                normalised_certs.append(canonical_map.get(key, c))
            raw["certifications"] = normalised_certs

        location_city = raw.get("location_city")
        location_country = raw.get("location_country")
        location_name = location_city or location_country

        return {
            "product_type": raw.get("product_type"),
            "product_keywords": list(raw.get("product_keywords") or []),
            "industry_context": raw.get("industry_context"),
            "buyer_intent": raw.get("buyer_intent") or "any",
            "category_hint": raw.get("category_hint"),

            "location_name": location_name,
            "location_city": location_city,
            "location_country": location_country,
            "location_region": raw.get("location_region"),
            "location_lat": raw.get("location_lat"),
            "location_lng": raw.get("location_lng"),
            "location_radius_km": raw.get("location_radius_km"),

            "certifications": list(raw.get("certifications") or []),
            "capacity_min": raw.get("capacity_min"),
            "capacity_unit": raw.get("capacity_unit"),
            "lead_time_max_days": raw.get("lead_time_max_days"),

            "query_type": raw.get("query_type") or "general",
            "complexity": raw.get("complexity") or "medium",
            "original_language": raw.get("original_language") or "en",
        }

    def _fallback_extract(self, raw_query: str, trace: list[dict]) -> dict:
        """Reuse whatever the trace learned when the loop hits max iterations.

        Cheaper and safer than firing another LLM call after the budget is
        exhausted. The downstream pipeline can still proceed because the
        constraint shape is filled with best-effort values.
        """
        fallback: dict[str, Any] = {
            "product_type": None,
            "product_keywords": [],
            "industry_context": None,
            "buyer_intent": "any",
            "category_hint": None,
            "location_city": None,
            "location_country": None,
            "certifications": [],
            "capacity_min": None,
            "capacity_unit": None,
            "lead_time_max_days": None,
            "query_type": "general",
            "complexity": "medium",
            "original_language": "en",
            "confidence": 0.2,
            "clarification_needed": True,
            "clarification_question": (
                "I ran out of reasoning budget before finishing the extraction. "
                "Could you restate the product, location, and any required "
                "certifications more directly?"
            ),
        }
        for step in trace:
            obs = step.get("observation") or {}
            action = step.get("action")
            if action == "geocode_location" and obs.get("found"):
                fallback["location_city"] = fallback.get("location_city") or obs.get("city")
                fallback["location_country"] = fallback.get("location_country") or obs.get("country")
                fallback["location_lat"] = obs.get("lat")
                fallback["location_lng"] = obs.get("lng")
            elif action == "canonicalize_certification" and obs.get("resolved"):
                certs = list(fallback["certifications"])
                if obs.get("canonical") and obs["canonical"] not in certs:
                    certs.append(obs["canonical"])
                fallback["certifications"] = certs
            elif action == "infer_industry_context":
                fallback["industry_context"] = fallback["industry_context"] or obs.get("industry")
            elif action == "parse_quantity_unit" and obs.get("parsed"):
                fallback["capacity_min"] = fallback["capacity_min"] or obs.get("value")
                fallback["capacity_unit"] = (
                    fallback["capacity_unit"] or obs.get("normalized_unit") or obs.get("unit")
                )

        # Tokenise the raw query for at least some product keywords so the
        # downstream semantic search has *something* to work with.
        if not fallback["product_keywords"]:
            words = [w for w in re.findall(r"[A-Za-z][A-Za-z0-9]{2,}", raw_query)]
            fallback["product_keywords"] = words[:5]
            fallback["product_type"] = fallback["product_type"] or " ".join(words[:3]) or None
        return fallback
