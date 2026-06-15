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

from app.agents.audit_log import append_audit_entry
from app.agents.base import BaseAgent
from app.agents.state import AgentState
from app.agents.tools import ToolRegistry, build_default_registry
from app.db.repositories.query_repo import QueryRepository
from app.db.session import SyncSessionLocal

logger = logging.getLogger(__name__)

# ── Loop hyperparameters ─────────────────────────────────────────────
MAX_REACT_ITERATIONS = 6
# Exact-args dedup is dodged by arg variations; cap executions per tool too.
_MAX_CALLS_PER_TOOL = 2
CLARIFICATION_THRESHOLD = 0.5
LLM_MAX_TOKENS_PER_STEP = 768

# ── Task 3.3 — Clarification trigger thresholds ──────────────────────
# Rule 2: low confidence AND fewer than N concrete constraints → ask.
CLARIFICATION_CONFIDENCE_FLOOR = 0.4
CLARIFICATION_MIN_CONSTRAINTS = 2
CLARIFICATION_QUESTION_MAX_TOKENS = 96

# Rule 1 pollution guard: the LLM sometimes copies vague query fragments
# ("our project", "my needs", "materials for our project") into product_type,
# which silences Rule 1 even though no real product was named. Anchored
# full-string regex so genuine products ("packaging materials") never match.
_PLACEHOLDER_PRODUCT_RE = re.compile(
    r"^\s*(?:"
    # bare placeholder nouns, optionally with a possessive/article lead-in.
    # "supplier"/"vendor" are placeholders here: searching a supplier corpus
    # for "supplier" carries zero signal (3.4 smoke: "I need a supplier").
    r"(?:(?:our|my|your|their|the|this|that|a|an)\s+)?(?:new\s+|own\s+)?"
    r"(?:projects?|needs?|requirements?|tasks?|business|company|order|usual|"
    r"stuff|things?|items?|something|anything|supplies|materials|"
    r"suppliers?|vendors?|manufacturers?|providers?|sources?|products?)"
    r"|"
    # generic noun + placeholder tail, e.g. "materials for our project"
    r"(?:stuff|things?|items?|materials|supplies|something|products?|suppliers?)\s+"
    r"for\s+(?:our|my|your|their|the)\b.*"
    r")\s*$",
    re.IGNORECASE,
)


def _is_placeholder_product(value: object) -> bool:
    """True when a product_type value is a contentless placeholder."""
    return isinstance(value, str) and bool(_PLACEHOLDER_PRODUCT_RE.match(value.strip()))


# Generic procurement nouns the LLM occasionally drops into location_country
# ("Food ingredient suppliers ..." → location_country='suppliers'). None of
# these are valid country names, so they are cleared (Phase E; surfaced by the
# benchmark-v2 Q8 flake where this emptied the result set ~1/3 of the time).
_NON_COUNTRY_TOKENS = frozenset({
    "suppliers", "supplier", "manufacturers", "manufacturer",
    "vendors", "vendor", "providers", "provider",
})


def _is_non_country_token(value: object) -> bool:
    """True when a location_country value is a generic procurement noun."""
    return isinstance(value, str) and value.strip().lower() in _NON_COUNTRY_TOKENS


# Pre-loop gate vocabulary: if EVERY alphabetic token of the raw query is in
# this set, no amount of tool calling can recover a product or constraint —
# the only sensible move is to ask. Observed in the 3.4 smoke: "We need
# materials for our project" burned all 6 ReAct iterations (including
# geocode("our project location")) before degrading.
_QUERY_STOPWORDS = frozenset({
    "i", "we", "you", "they", "need", "needs", "want", "require", "looking",
    "searching", "sourcing", "find", "get", "buy", "purchase", "procure",
    "me", "us", "for", "a", "an", "some", "the", "new", "our", "my", "your",
    "their", "own", "urgently", "please", "hi", "hello", "help", "can",
    "could", "would", "like", "am", "are", "is", "it", "that", "this",
    "supplier", "suppliers", "vendor", "vendors", "source", "sources",
    "partner", "partners", "someone", "something", "anything", "stuff",
    "thing", "things", "item", "items", "material", "materials", "supplies",
    "product", "products", "project", "projects", "requirement",
    "requirements", "business", "company", "order", "usual", "and", "or",
    "of", "to", "with", "what", "who",
})


def _is_contentless_query(raw_query: str) -> bool:
    """True when the query has no content-bearing token at all."""
    tokens = re.findall(r"[a-zA-Z]+", (raw_query or "").lower())
    return bool(tokens) and all(t in _QUERY_STOPWORDS for t in tokens)


# Rule 3 placeholders: vague references the system can't resolve without
# either memory help or a user-side clarification. The list is conservative
# on purpose — over-clarifying is worse than under-clarifying.
_PLACEHOLDER_PATTERNS = (
    "our project",
    "our new project",
    "the usual",
    "same as before",
    "the same suppliers",
    "what we had last time",
    "our packaging needs",
    "our usual vendors",
)

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
    "certifications": [
        "ONLY certifications the user explicitly named in the query "
        "(canonical names, list[str]). Do NOT add certs you merely inferred."
    ],
    "industry_typical_certs": [
        "certs surfaced by infer_industry_context that the user did NOT state "
        "(list[str]). These are soft hints, never hard requirements."
    ],
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
def _parse_react_response(text: str) -> _ReActStep:
    """Parse one Thought/Action/Action Input block. Raises ValueError on bad shape.

    llama-3.1 sometimes hallucinates the Observation (and further commentary)
    inside its own completion even with a stop sequence in place (e.g. when
    the response arrives via a provider that ignores `stop`). Defend in two
    layers: truncate everything from a hallucinated "Observation:" onwards,
    then parse only the FIRST JSON value after "Action Input:" and ignore any
    trailing junk (json.JSONDecoder.raw_decode instead of json.loads).
    """
    obs_pos = text.find("\nObservation:")
    if obs_pos != -1:
        text = text[:obs_pos]

    thought_m = _THOUGHT_RE.search(text)
    action_m = _ACTION_RE.search(text)
    if not thought_m or not action_m:
        raise ValueError(
            f"Could not parse ReAct response (missing Thought or Action). "
            f"First 200 chars: {text[:200]!r}"
        )
    args: dict = {}
    label_m = re.search(r"Action Input:\s*", text)
    if label_m:
        payload = text[label_m.end():]
        start = next((i for i, ch in enumerate(payload) if ch in "{["), None)
        if start is not None:
            try:
                parsed, _end = json.JSONDecoder().raw_decode(payload[start:])
                if isinstance(parsed, dict):
                    args = parsed
            except json.JSONDecodeError as e:
                raise ValueError(
                    f"Action Input is not valid JSON: {e}. First 200 chars: "
                    f"{payload[start:start + 200]!r}"
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
- CERTIFICATION PROVENANCE: `certifications` is a HARD filter — put a cert there
  ONLY if the user explicitly named it in the query. Certifications that merely
  came back from `infer_industry_context` as commonly-required-in-this-industry
  go in `industry_typical_certs` instead. Never copy inferred certs into
  `certifications`; doing so wrongly rejects every supplier that lacks them.
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
        # Task 3.3 — on a resumed run, pass the partial constraints from the
        # paused turn so the Parser doesn't re-extract from scratch.
        prior_partial = state.get("previous_partial_constraints") or None

        # Pre-loop placeholder gate (Task 3.4 smoke finding). A query whose
        # every token is filler ("I need a supplier", "we need materials for
        # our project") cannot be improved by tool calls — the ReAct loop
        # just spends its whole budget and degrades. Ask the user up front:
        # one cheap composer call instead of 6+ main-loop calls, and the
        # clarification is resumable. Resumed turns and memory-assisted
        # queries skip the gate (memory may resolve "same as before").
        if prior_partial is None and not memory_context and _is_contentless_query(raw_query):
            return self._raise_pre_loop_clarification(state, raw_query, start)

        system_prompt = _build_system_prompt(self.tools)
        user_open = self._build_initial_user_message(
            raw_query, memory_context, prior_partial
        )

        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_open},
        ]

        trace: list[dict[str, Any]] = []
        seen_calls: set[tuple[str, str]] = set()
        tool_call_counts: dict[str, int] = {}
        terminated_by = "max_iterations"
        final_constraints: dict | None = None
        loop_error: str | None = None

        for iteration in range(MAX_REACT_ITERATIONS):
            # Force-finish nudge (Task 3.4): on the last allowed iteration,
            # tell the model explicitly that only Finish is acceptable.
            # llama-3.1 otherwise keeps "validating" with more tool calls
            # until the budget dies (observed: 4x infer_industry_context).
            if iteration == MAX_REACT_ITERATIONS - 1:
                messages.append({
                    "role": "user",
                    "content": (
                        "This is your FINAL step. You MUST respond with "
                        "Action: Finish and the complete JSON payload in "
                        "Action Input, built from everything learned in the "
                        "observations above. Do not call any other tool."
                    ),
                })
            try:
                response = self.llm.complete(
                    messages,
                    max_tokens=LLM_MAX_TOKENS_PER_STEP,
                    temperature=0.0,
                    # llama-3.1 tends to hallucinate the Observation inside its
                    # own completion; cut generation before it gets the chance.
                    stop=["\nObservation:", "Observation:"],
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

            # Per-tool budget (Task 3.4): exact-args dedup is dodged by arg
            # variations ("...for construction" vs "...for building"). Two
            # executions of the same tool are plenty for one query; a third
            # request gets a hint instead of a tool run.
            if tool_call_counts.get(step.action, 0) >= _MAX_CALLS_PER_TOOL:
                entry["observation"] = {
                    "error": "tool_budget_exhausted",
                    "detail": (
                        f"You have already called {step.action} "
                        f"{_MAX_CALLS_PER_TOOL} times. Its earlier observations "
                        f"are sufficient. Use a different tool only if strictly "
                        f"needed, otherwise emit Action: Finish now."
                    ),
                }
                trace.append(entry)
                messages.append({"role": "assistant", "content": response})
                messages.append({
                    "role": "user",
                    "content": f"Observation: {json.dumps(entry['observation'])}",
                })
                continue
            tool_call_counts[step.action] = tool_call_counts.get(step.action, 0) + 1

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

        constraints = self._normalise_constraints(
            final_constraints, trace, raw_query=raw_query, prior_partial=prior_partial
        )
        confidence = float(final_constraints.get("confidence", 0.5) or 0.5)
        legacy_clarification_needed = (
            bool(final_constraints.get("clarification_needed"))
            or confidence < CLARIFICATION_THRESHOLD
        )
        legacy_clarification_question = final_constraints.get("clarification_question")

        # Task 3.3 — Post-loop clarification decision. Only fires on a clean
        # `finish` termination; the fallback/degraded paths already emit
        # their own clarification text and we don't override them.
        composed_question: Optional[str] = None
        if terminated_by == "finish":
            composed_question = self._decide_clarification(
                constraints=constraints,
                trace=trace,
                raw_query=raw_query,
                confidence=confidence,
                memory_context=memory_context,
            )

        if composed_question is not None:
            clarification_needed = True
            clarification_question = composed_question
        else:
            clarification_needed = legacy_clarification_needed
            clarification_question = (
                legacy_clarification_question if clarification_needed else None
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
        state["clarification_question"] = clarification_question
        state["pipeline_status"] = (
            "needs_clarification" if clarification_needed else "running"
        )

        # Task 3.3 — a clarification is a distinct, auditable event. Logged
        # under a dedicated agent_name so it surfaces cleanly in /admin/metrics
        # and audit-log queries can count "clarifications raised per query".
        # Both origins are audited: the post-loop composer AND the legacy
        # path where the LLM set clarification_needed in its Finish payload
        # (Task 3.4 smoke found the latter raised a resumable dialogue with
        # no audit row). Degraded paths are excluded — they don't pause.
        if clarification_needed and terminated_by == "finish":
            origin = (
                "Post-loop trigger fired"
                if composed_question is not None
                else "LLM Finish payload requested clarification"
            )
            self._append_audit_entry(
                state,
                agent_name="clarification_handler",
                action="clarification_raised",
                duration_ms=0,
                reasoning=(
                    f"{origin}: confidence={confidence:.2f}, "
                    f"product_type={constraints.get('product_type')!r}"
                ),
                input_summary=raw_query[:200],
                output_summary=clarification_question or "",
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

    def _raise_pre_loop_clarification(
        self, state: AgentState, raw_query: str, start: float
    ) -> AgentState:
        """Short-circuit for contentless queries: raise a resumable
        clarification without entering the ReAct loop (Task 3.4)."""
        question = self._compose_clarification_question(
            raw_query, {}, missing="placeholder"
        )
        constraints = self._normalise_constraints({}, [])
        duration_ms = int((time.time() - start) * 1000)

        self._log_audit(
            state,
            action="react_loop_skipped",
            input_summary=raw_query[:200],
            output_summary="contentless query; clarification raised pre-loop",
            duration_ms=duration_ms,
            reasoning=(
                "Every token of the query is filler vocabulary; tool calls "
                "cannot recover a product or constraint. Asking the user "
                "instead of spending the ReAct budget."
            ),
            input_snapshot={"raw_query": raw_query},
            output_snapshot={
                "terminated_by": "pre_loop_clarification",
                "iterations": 0,
                "tools_called": [],
                "trace": [],
                "parsed_constraints": constraints,
                "loop_error": None,
            },
        )
        self._append_audit_entry(
            state,
            agent_name="clarification_handler",
            action="clarification_raised",
            duration_ms=0,
            reasoning="Pre-loop gate fired: contentless query, no memory help",
            input_summary=raw_query[:200],
            output_summary=question or "",
        )

        state["react_trace"] = []
        state["react_terminated_by"] = "pre_loop_clarification"
        state["parsed_constraints"] = constraints
        state["detected_language"] = "en"
        state["needs_clarification"] = True
        state["clarification_question"] = question
        state["pipeline_status"] = "needs_clarification"
        return state

    def _decide_clarification(
        self,
        constraints: dict,
        trace: list[dict],
        raw_query: str,
        confidence: float,
        memory_context: Optional[str],
    ) -> Optional[str]:
        """Task 3.3 — decide whether to interrupt the pipeline with a question.

        Three trigger rules, evaluated in priority order. The first rule that
        fires composes a single user-facing question via a focused LLM call.
        Returns None when the loop's extraction is sufficient to proceed.
        """
        # Rule 1 pollution guard: a placeholder copied into product_type
        # ("our project", "supplier") is NOT a real product.
        has_product = bool(constraints.get("product_type")) and not _is_placeholder_product(
            constraints.get("product_type")
        )
        memory_was_helpful = self._memory_returned_useful_hit(trace)
        constraint_count = sum(
            1 for k in (
                "product_type",
                "certifications",
                "location_country",
                "capacity_min",
            )
            if constraints.get(k)
        )

        # Rule 1 — missing product, no memory help.
        if not has_product and not memory_was_helpful:
            return self._compose_clarification_question(
                raw_query, constraints, missing="product"
            )

        # Rule 2 — low confidence AND sparse constraints.
        if confidence < CLARIFICATION_CONFIDENCE_FLOOR and constraint_count < CLARIFICATION_MIN_CONSTRAINTS:
            return self._compose_clarification_question(
                raw_query, constraints, missing="multiple"
            )

        # Rule 3 — placeholder-style references the system can't resolve.
        lowered = raw_query.lower()
        has_placeholder = any(p in lowered for p in _PLACEHOLDER_PATTERNS)
        if has_placeholder and not memory_was_helpful and constraint_count < CLARIFICATION_MIN_CONSTRAINTS:
            return self._compose_clarification_question(
                raw_query, constraints, missing="placeholder"
            )

        return None

    @staticmethod
    def _memory_returned_useful_hit(trace: list[dict]) -> bool:
        """True iff a lookup_past_query observation came back non-empty.

        Task 3.2's lookup_past_query tool returns a list of memory rows. An
        empty list means no useful prior query was found, which we treat the
        same as the tool never having been called.
        """
        for step in trace:
            if step.get("action") != "lookup_past_query":
                continue
            obs = step.get("observation")
            if isinstance(obs, list) and obs:
                return True
            if isinstance(obs, dict):
                rows = obs.get("results") or obs.get("rows") or obs.get("matches")
                if isinstance(rows, list) and rows:
                    return True
        return False

    def _compose_clarification_question(
        self,
        raw_query: str,
        partial_constraints: dict,
        missing: str,
    ) -> str:
        """Single focused LLM call: render ONE short question for the user.

        The model is heavily constrained: one question, under 25 words, no
        explanation, suggest 2-3 example options inline when possible. If
        the LLM call fails, fall back to a deterministic template so the
        feature never crashes the Parser end-to-end.
        """
        summary = self._format_constraints_for_clarification(partial_constraints)
        prompt = (
            f'A procurement user asked: "{raw_query}"\n\n'
            f"We extracted partial constraints:\n{summary}\n\n"
            "This is not enough to find suppliers. The most useful single "
            f"question to ask the user is one that resolves: {missing}.\n\n"
            "Write ONE short, friendly clarification question (under 25 words). "
            "Do NOT ask multiple questions. Do NOT explain.\n"
            "Focus on the single most important missing piece. If possible, "
            "suggest 2-3 example options inline.\n\n"
            "Question:"
        )
        messages = [
            {"role": "system", "content": "You write one short clarification question. No preamble. No explanation."},
            {"role": "user", "content": prompt},
        ]
        try:
            raw = self.llm.complete(
                messages,
                max_tokens=CLARIFICATION_QUESTION_MAX_TOKENS,
                temperature=0.2,
            )
        except Exception as e:  # noqa: BLE001 — clarification must not crash Parser
            logger.warning("[parser/clarify] LLM call failed: %s; using fallback", e)
            return self._fallback_clarification(missing)

        return self._tidy_clarification_question(raw) or self._fallback_clarification(missing)

    @staticmethod
    def _format_constraints_for_clarification(constraints: dict) -> str:
        """Render the small subset of fields the LLM needs to write a question.

        Kept minimal on purpose — handing the LLM the full schema invites it
        to comment on every absent field rather than focus on the one we care
        about.
        """
        rows: list[str] = []
        for label, key in (
            ("Product", "product_type"),
            ("Certifications", "certifications"),
            ("Country", "location_country"),
            ("City", "location_city"),
            ("Capacity floor", "capacity_min"),
        ):
            v = constraints.get(key)
            if not v:
                rows.append(f"  - {label}: (not specified)")
            elif isinstance(v, list):
                rows.append(f"  - {label}: {', '.join(str(x) for x in v) or '(not specified)'}")
            else:
                rows.append(f"  - {label}: {v}")
        return "\n".join(rows)

    @staticmethod
    def _tidy_clarification_question(text: str) -> str:
        """Normalise the model's output to a single short question."""
        cleaned = (text or "").strip()
        if not cleaned:
            return ""
        # Strip a leading "Question:" label if the model echoes it.
        lowered = cleaned.lower()
        if lowered.startswith("question:"):
            cleaned = cleaned.split(":", 1)[1].strip()
        # Keep only the first non-empty line; the LLM occasionally writes
        # bullets or explanations after the question itself.
        first_line = next((ln.strip() for ln in cleaned.splitlines() if ln.strip()), "")
        if len(first_line) > 240:
            first_line = first_line[:240].rsplit(" ", 1)[0] + "…"
        return first_line

    @staticmethod
    def _fallback_clarification(missing: str) -> str:
        """Deterministic fallback when the LLM clarification call fails."""
        if missing == "product":
            return (
                "What product are you sourcing? For example: packaging, "
                "electronics, or raw materials."
            )
        if missing == "placeholder":
            return (
                "Could you say which product or service you need? "
                "Your last message did not name one."
            )
        return (
            "Could you give a bit more detail — product, certifications, "
            "or country — so I can narrow the search?"
        )

    def _append_audit_entry(
        self,
        state: AgentState,
        *,
        agent_name: str,
        action: str,
        input_summary: str,
        output_summary: str,
        duration_ms: int,
        reasoning: Optional[str] = None,
    ) -> None:
        """Audit-log appender that lets us record entries under a different
        agent_name than self (e.g. 'clarification_handler' is not a real
        agent, it's a sub-decision inside the Parser)."""
        append_audit_entry(
            state,
            agent_name=agent_name,
            action=action,
            input_summary=input_summary,
            output_summary=output_summary,
            duration_ms=duration_ms,
            reasoning=reasoning,
        )

    def _build_initial_user_message(
        self,
        raw_query: str,
        memory_context: Optional[str],
        prior_partial: Optional[dict] = None,
    ) -> str:
        parts: list[str] = []
        if memory_context:
            parts.append(
                "User's recent successful queries (context only, do not copy):\n"
                f"{memory_context}"
            )
        if prior_partial:
            # Task 3.3 — on resumed turns, the Parser already extracted some
            # constraints in the prior turn. Hand those over so the LLM can
            # merge the user's new clarification instead of re-extracting.
            try:
                prior_block = json.dumps(prior_partial, indent=2, default=str)
            except (TypeError, ValueError):
                prior_block = str(prior_partial)
            parts.append(
                "Constraints extracted on the previous turn (merge with the "
                f"current query, do not discard):\n{prior_block}"
            )
        parts.append(
            f"Current query: {raw_query}\n\n"
            "Begin. Emit your first Thought / Action / Action Input."
        )
        return "\n\n".join(parts)

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

    @staticmethod
    def _normalise_cert(value: object) -> str:
        """Case-insensitive, whitespace-collapsed cert token for comparison.

        Mirrors the lenient matching compliance uses when checking certs
        (lowercase + strip + single-space) so the provenance split lines up
        with how the cert is later compared against supplier records.
        """
        if not isinstance(value, str):
            return ""
        return re.sub(r"\s+", " ", value.strip().lower())

    @staticmethod
    def _iter_memory_rows(observation: object) -> list[dict]:
        """Normalise a lookup_past_query observation to a list of memory rows.

        The tool returns either a bare list of rows or a dict wrapping them
        under results/rows/matches (mirrors _memory_returned_useful_hit)."""
        if isinstance(observation, list):
            return [r for r in observation if isinstance(r, dict)]
        if isinstance(observation, dict):
            rows = observation.get("results") or observation.get("rows") or observation.get("matches")
            if isinstance(rows, list):
                return [r for r in rows if isinstance(r, dict)]
        return []

    def _partition_certifications(
        self,
        raw: dict,
        trace: list[dict],
        raw_query: str,
        prior_partial: Optional[dict],
    ) -> tuple[list[str], list[str]]:
        """Split the LLM's cert list by provenance — the cert-hallucination fix.

        Runs on EVERY parse (not only when the LLM misbehaves). A cert keeps
        its place in the HARD `certifications` gate only when it has *user*
        provenance; certs whose only origin is the inference tool become SOFT
        hints; certs with no provenance at all are dropped with a warning.

        User provenance (→ hard):
          - named verbatim in the raw query, OR
          - recalled from memory (lookup_past_query) constraints, OR
          - carried over from a prior clarification turn (prior_partial), OR
          - explicitly resolved via canonicalize_certification.
        Inference provenance (→ soft `industry_typical_certs`):
          - surfaced by infer_industry_context.common_certs and not user-stated.
        """
        query_norm = self._normalise_cert(raw_query)

        # ── Build the user-provenance set ────────────────────────────────
        user_provenance: set[str] = set()
        for c in (prior_partial or {}).get("certifications") or []:
            n = self._normalise_cert(c)
            if n:
                user_provenance.add(n)
        for step in trace:
            action = step.get("action")
            if action == "lookup_past_query":
                for row in self._iter_memory_rows(step.get("observation")):
                    for c in (row.get("constraints") or {}).get("certifications") or []:
                        n = self._normalise_cert(c)
                        if n:
                            user_provenance.add(n)
            elif action == "canonicalize_certification":
                obs = step.get("observation") or {}
                if isinstance(obs, dict) and obs.get("resolved"):
                    for key in (obs.get("input"), obs.get("canonical")):
                        n = self._normalise_cert(key)
                        if n:
                            user_provenance.add(n)

        # ── Collect inference-tool certs (ordered, deduped) ──────────────
        inferred_observed: list[str] = []
        inferred_norm: set[str] = set()
        for step in trace:
            if step.get("action") != "infer_industry_context":
                continue
            obs = step.get("observation")
            if not isinstance(obs, dict):
                continue
            for c in obs.get("common_certs") or []:
                n = self._normalise_cert(c)
                if n and n not in inferred_norm:
                    inferred_norm.add(n)
                    inferred_observed.append(c.strip())

        def _is_user_stated(norm: str) -> bool:
            # Substring against the query so "ISO 9001" matches "...ISO 9001:2015".
            return bool(norm) and (norm in query_norm or norm in user_provenance)

        # ── Classify each cert the LLM put in `certifications` ───────────
        hard: list[str] = []
        hard_norm: set[str] = set()
        for c in raw.get("certifications") or []:
            n = self._normalise_cert(c)
            if not n:
                continue
            if _is_user_stated(n):
                if n not in hard_norm:
                    hard_norm.add(n)
                    hard.append(c.strip() if isinstance(c, str) else c)
            elif n in inferred_norm:
                continue  # belongs to the soft list, assembled below
            else:
                logger.warning(
                    "[parser/provenance] Dropping cert %r: absent from user query "
                    "and not surfaced by infer_industry_context (query=%r)",
                    c, raw_query,
                )

        # ── Assemble the soft list: inferred certs + any LLM-routed soft
        # certs, minus anything already accepted as a hard user cert. ─────
        soft: list[str] = []
        soft_norm: set[str] = set()
        for c in inferred_observed + list(raw.get("industry_typical_certs") or []):
            n = self._normalise_cert(c)
            if not n or n in hard_norm or n in soft_norm:
                continue
            soft_norm.add(n)
            soft.append(c.strip() if isinstance(c, str) else c)

        return hard, soft

    def _normalise_constraints(
        self,
        raw: dict,
        trace: list[dict],
        raw_query: str = "",
        prior_partial: Optional[dict] = None,
    ) -> dict:
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
        # If certifications is empty entirely, promote every resolved cert
        # observation directly — llama-3.1 occasionally emits an empty Finish
        # payload after a dedup-then-finish step, so we let the trace win.
        certs_in = list(raw.get("certifications") or [])
        canonical_map: dict[str, str] = {}
        canonical_seen: list[str] = []
        for step in trace:
            if step.get("action") == "canonicalize_certification":
                obs = step.get("observation") or {}
                if obs.get("resolved") and obs.get("input") and obs.get("canonical"):
                    canonical_map[obs["input"].strip().lower()] = obs["canonical"]
                    if obs["canonical"] not in canonical_seen:
                        canonical_seen.append(obs["canonical"])
        if certs_in:
            normalised_certs: list[str] = []
            for c in certs_in:
                if not isinstance(c, str):
                    continue
                key = c.strip().lower()
                normalised_certs.append(canonical_map.get(key, c))
            raw["certifications"] = normalised_certs
        elif canonical_seen:
            raw["certifications"] = list(canonical_seen)

        # Promote parse_quantity_unit when the LLM forgot capacity_min/unit.
        if raw.get("capacity_min") is None or raw.get("capacity_unit") is None:
            for step in trace:
                if step.get("action") == "parse_quantity_unit":
                    obs = step.get("observation") or {}
                    if obs.get("parsed") and obs.get("value") is not None:
                        if raw.get("capacity_min") is None:
                            raw["capacity_min"] = obs.get("value")
                        if raw.get("capacity_unit") is None:
                            raw["capacity_unit"] = obs.get("normalized_unit") or obs.get("unit")
                        break

        # Promote infer_industry_context for industry_context + a best-effort
        # product_type when the LLM emitted an empty Finish payload.
        if not raw.get("industry_context") or not raw.get("product_type"):
            for step in trace:
                if step.get("action") == "infer_industry_context":
                    obs = step.get("observation") or {}
                    if not isinstance(obs, dict):
                        continue
                    if not raw.get("industry_context") and obs.get("industry"):
                        raw["industry_context"] = obs["industry"]
                    if not raw.get("product_type"):
                        # The LLM's own Action Input is the closest thing to a
                        # product label that survived the trace.
                        product_desc = (step.get("action_input") or {}).get("product_description")
                        if product_desc:
                            raw["product_type"] = product_desc
                    break

        location_city = raw.get("location_city")
        location_country = raw.get("location_country")
        # Phase E (Rule 1 pollution): a generic procurement noun ("suppliers",
        # "manufacturers", ...) is never a country — drop it so the discovery
        # structured filter doesn't search Supplier.country == 'suppliers' and
        # return nothing (benchmark-v2 Q8 flake).
        if _is_non_country_token(location_country):
            location_country = None
        # Bug 1 (Phase D): a "within Nkm of <place>" query's geocoded place is a
        # radius *centre*, not a country filter. geocode_location buckets a
        # no-comma place name ("Berlin") as a country, so a radius query arrives
        # with the centre sitting in location_country. Promote it to
        # location_city and clear the country, so the compliance gate does not
        # run a spurious country-equality check against the supplier's real
        # country ("required country is Berlin"). A genuine country query has no
        # radius and is left untouched.
        if raw.get("location_radius_km") and location_country and not location_city:
            location_city = location_country
            location_country = None
        location_name = location_city or location_country

        # Rule 1 pollution guard (Task 3.4): never let a placeholder reach
        # downstream discovery as a product_type — semantic search for
        # "our project" is noise and it silences the clarification trigger.
        product_type = raw.get("product_type")
        if _is_placeholder_product(product_type):
            product_type = None

        # Cert provenance guard: keep only user-stated certs in the hard
        # `certifications` gate; route inference-tool certs to the soft
        # `industry_typical_certs`; drop certs with no provenance at all.
        hard_certs, inferred_certs = self._partition_certifications(
            raw, trace, raw_query, prior_partial
        )

        return {
            "product_type": product_type,
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

            "certifications": hard_certs,
            "industry_typical_certs": inferred_certs,
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
                # The LLM's own product_description argument is its distilled
                # product label — far better than the token salad below
                # (Task 3.4: resumed runs carry the user's answer here).
                product_desc = (step.get("action_input") or {}).get("product_description")
                if (
                    product_desc
                    and not fallback["product_type"]
                    and not _is_placeholder_product(product_desc)
                ):
                    fallback["product_type"] = product_desc
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

        # Task 3.4: when the trace recovered a real product AND at least one
        # other concrete constraint, the extraction is good enough to proceed.
        # Asking the user again after a productive (if unfinished) loop is
        # worse UX than running the search with what was learned — especially
        # on a resumed turn where the user already answered once.
        other_constraints = sum(
            1 for v in (
                fallback["certifications"],
                fallback["location_country"] or fallback["location_city"],
                fallback["capacity_min"],
            ) if v
        )
        if not _is_placeholder_product(fallback["product_type"]) and (
            fallback["product_type"] and other_constraints >= 1
        ):
            # 0.5 = the neutral default, deliberately AT the clarification
            # threshold (not below it) so the legacy low-confidence check
            # downstream doesn't immediately re-raise what we just cleared.
            fallback["confidence"] = 0.5
            fallback["clarification_needed"] = False
            fallback["clarification_question"] = None
        return fallback
