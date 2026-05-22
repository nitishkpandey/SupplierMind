"""
app/agents/parser_agent.py — Extracts structured procurement constraints from natural language.

DESIGN DECISION: Why use an LLM for parsing instead of regex/NLP?
Regex: "Find ISO 9001 certified supplier" — easy.
Regex: "Ich suche einen zertifizierten Metalllieferanten in Bremen" — impossible.
Regex: "bronze supplier" → category "metals" — requires domain knowledge.

LLM handles all three cases naturally.
The tradeoff: it's slower (~2s) but far more flexible.
We use JSON mode to guarantee structured output.
"""

import json
import logging
import time

from app.agents.base import BaseAgent
from app.agents.state import AgentState, ParsedConstraints
from app.services.geocoding import GeocodingService

logger = logging.getLogger(__name__)

# Confidence threshold below which we ask for clarification
CLARIFICATION_THRESHOLD = 0.6

SYSTEM_PROMPT = """You are a procurement constraint extraction system.
Your job is to parse a natural-language procurement query and extract structured constraints.

IMPORTANT RULES:
1. Always respond with valid JSON only. No markdown, no explanation outside the JSON.
2. If the query is in a language other than English, translate it first, then extract.
3. Map product names to standard categories:
   - bronze, steel, aluminum, copper, metal, alloy → "metals"
   - circuit, PCB, sensor, electronic, semiconductor → "electronics"
   - freight, shipping, transport, logistics, delivery → "logistics"
   - fabric, textile, fiber, cloth, garment → "textiles"
   - chemical, solvent, reagent, compound → "chemicals"
   - machine, equipment, automation, conveyor → "machinery"
   - box, carton, container, packaging, pallet → "packaging"
   - ingredient, flavour, additive, food chemical → "food_ingredients"
   - software, IT service, development, cloud → "software_services"
   - concrete, insulation, building material → "construction_materials"
4. Extract radius ONLY if explicitly stated (e.g. "within 25km", "50km radius").
   Do not infer radius from city names alone.
5. Confidence < 0.6 means the query is too vague to proceed.

Return this JSON structure:
{
  "category": string or null,
  "location_name": string or null,
  "location_radius_km": number or null,
  "certifications": array of strings or [],
  "capacity_min": number or null,
  "capacity_unit": string or null,
  "lead_time_max_days": number or null,
  "budget_note": string or null,
  "original_language": "en" | "de" | "hi" | "other",
  "confidence": number between 0.0 and 1.0,
  "clarification_needed": boolean,
  "clarification_question": string or null,
  "reasoning": string
}"""


class ParserAgent(BaseAgent):
    """
    Extracts structured procurement constraints from a natural-language query.

    AGENTIC BEHAVIORS:
    1. Multilingual: detects and handles German, Hindi, English
    2. Implicit knowledge: "bronze" → category "metals" (not in the query!)
    3. Ambiguity detection: too vague → asks specific clarifying question
    4. Tool use: geocodes location name to coordinates
    """

    agent_name = "parser"

    def __init__(self) -> None:
        super().__init__()
        self.geocoder = GeocodingService()

    def execute(self, state: AgentState) -> AgentState:
        start = time.time()
        raw_query = state["raw_query"]
        logger.info("[parser] Processing query: %r", raw_query[:80])

        # Step 1: LLM extracts constraints
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Extract constraints from: {raw_query}"},
        ]

        raw_json = self.llm.complete_json(messages, temperature=0.0)

        try:
            extracted = json.loads(raw_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM returned invalid JSON: {e}\nRaw: {raw_json}")

        confidence = float(extracted.get("confidence", 0.5))
        clarification_needed = bool(extracted.get("clarification_needed", False))
        clarification_needed = clarification_needed or confidence < CLARIFICATION_THRESHOLD

        duration_ms = int((time.time() - start) * 1000)

        if clarification_needed:
            question = extracted.get("clarification_question") or (
                "Could you provide more details? What category of supplier are you looking for, "
                "and in which country or region?"
            )
            logger.info("[parser] Query ambiguous (confidence=%.2f), requesting clarification", confidence)

            self._log_audit(
                state,
                action="clarification_needed",
                input_summary=raw_query,
                output_summary=f"Confidence={confidence:.2f}. Question: {question}",
                duration_ms=duration_ms,
                reasoning=extracted.get("reasoning"),
            )

            state["needs_clarification"] = True
            state["clarification_question"] = question
            state["detected_language"] = extracted.get("original_language", "en")
            state["pipeline_status"] = "needs_clarification"
            return state

        # Step 2: Geocode location name → coordinates
        constraints: ParsedConstraints = {
            "category": extracted.get("category"),
            "location_name": extracted.get("location_name"),
            "certifications": extracted.get("certifications") or [],
            "capacity_min": extracted.get("capacity_min"),
            "capacity_unit": extracted.get("capacity_unit"),
            "lead_time_max_days": extracted.get("lead_time_max_days"),
            "budget_note": extracted.get("budget_note"),
            "location_radius_km": extracted.get("location_radius_km"),
            "original_language": extracted.get("original_language", "en"),
        }

        location_name = constraints.get("location_name")
        if location_name:
            coords = self.geocoder.geocode(location_name)
            if coords:
                constraints["location_lat"] = coords[0]
                constraints["location_lng"] = coords[1]
                logger.info(
                    "[parser] Geocoded %r → (%.4f, %.4f)", location_name, coords[0], coords[1]
                )
            else:
                logger.warning("[parser] Could not geocode location: %r", location_name)

        # Build human-readable summary for audit log
        summary_parts = []
        if constraints.get("category"):
            summary_parts.append(f"category={constraints['category']}")
        if constraints.get("location_name"):
            radius = constraints.get("location_radius_km")
            loc = constraints["location_name"]
            summary_parts.append(f"location={loc}" + (f" (radius={radius}km)" if radius else ""))
        if constraints.get("certifications"):
            summary_parts.append(f"certs={constraints['certifications']}")
        if constraints.get("capacity_min"):
            summary_parts.append(f"capacity>={constraints['capacity_min']} {constraints.get('capacity_unit','')}")
        if constraints.get("lead_time_max_days"):
            summary_parts.append(f"lead_time<={constraints['lead_time_max_days']}d")

        duration_ms = int((time.time() - start) * 1000)
        self._log_audit(
            state,
            action="constraints_extracted",
            input_summary=raw_query,
            output_summary=", ".join(summary_parts) or "no constraints found",
            duration_ms=duration_ms,
            reasoning=extracted.get("reasoning"),
        )

        state["parsed_constraints"] = constraints
        state["detected_language"] = extracted.get("original_language", "en")
        state["needs_clarification"] = False
        state["clarification_question"] = None
        state["pipeline_status"] = "running"
        return state
