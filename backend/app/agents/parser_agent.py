"""
app/agents/parser_agent.py — Production v2: Product intent extraction with memory.

KEY CHANGES FROM v1:
- No hardcoded categories — extracts free-form product_type + keywords
- Uses user's recent query history as memory context
- Tool use: geocoder called dynamically when location is present
- Classifies query_type for downstream ranking

This agent is the cornerstone of the production upgrade.
"""

import json
import logging
import time
import uuid
from typing import Optional

from app.agents.base import BaseAgent
from app.agents.state import AgentState
from app.services.geocoding import GeocodingService
from app.db.session import SyncSessionLocal
from app.db.repositories.query_repo import QueryRepository

logger = logging.getLogger(__name__)

CLARIFICATION_THRESHOLD = 0.5

SYSTEM_PROMPT = """You are an expert procurement query analyzer for an enterprise supplier discovery system.

YOUR JOB: Extract a rich, structured representation of what the user wants to source.

KEY PRINCIPLES:
1. Do NOT force the query into fixed categories. Extract the actual product/service.
2. Generate diverse search keywords a procurement expert would Google.
3. Identify the buyer's INTENT (manufacturer? distributor? service provider?).
4. Detect explicit constraints (certifications, location, capacity) AND implicit ones.
5. If query is multilingual, translate to English first, but preserve original_language.

OUTPUT JSON SCHEMA:

{
  "product_type": "specific product or service name",
  "product_keywords": ["3-7 diverse search terms"],
  "industry_context": "industry/use-case, or null",
  "buyer_intent": "manufacturer" | "distributor" | "service_provider" | "any",
  "category_hint": "one of: metals, electronics, tools_hardware, logistics, textiles, chemicals, machinery, packaging, food_ingredients, software_services, construction_materials, office_supplies, OR null",

  "location": {
    "city": "city name or null",
    "country": "country name or null",
    "region": "broader region or null",
    "radius_km": number or null
  },

  "certifications": ["explicit certs only, e.g. ISO 9001, CE, GDPR"],
  "capacity": {
    "min_value": number or null,
    "unit": "unit string or null"
  },
  "lead_time_max_days": number or null,

  "query_type": "geographic_priority" | "compliance_critical" | "capability_match" | "general",
  "complexity": "simple" | "medium" | "complex",

  "original_language": "en" | "de" | "hi" | "other",
  "confidence": 0.0 to 1.0,
  "clarification_needed": boolean,
  "clarification_question": "specific question if confidence < 0.5, else null",

  "reasoning": "2-3 sentences explaining your extraction choices"
}

PRODUCT KEYWORD GUIDELINES (most important field):
- Include product name, synonyms, related terms, technical specs
- Example: "screwdriving tools" → ["screwdriver", "torque wrench", "fastener tools", "assembly tools", "industrial screwdriving"]
- Example: "lithium batteries for drones" → ["lithium polymer battery", "LiPo battery", "UAV battery", "drone power supply"]
- Quality of keywords determines whether real suppliers are found.

QUERY TYPE CLASSIFICATION:
- "geographic_priority": location/radius is critical
- "compliance_critical": certifications are the main filter
- "capability_match": specific technical capability needed
- "general": balanced or unclear priority

If user's recent queries are provided, use them as CONTEXT to interpret ambiguous parts.
Do NOT override explicit query content, just enrich.

Return ONLY valid JSON. No markdown, no preamble."""


class ParserAgent(BaseAgent):
    """Production Parser Agent with product intent extraction and user memory."""

    agent_name = "parser"

    def __init__(self) -> None:
        super().__init__()
        self.geocoder = GeocodingService()

    def execute(self, state: AgentState) -> AgentState:
        start = time.time()
        raw_query = state["raw_query"]
        user_id = state.get("user_id", "")

        # Step 1: Load user memory (recent queries)
        memory_context = self._load_user_memory(user_id)

        # Step 2: LLM extraction with memory context
        user_message = f"User query: {raw_query}"
        if memory_context:
            user_message = (
                f"User's recent successful queries (for context, do not copy):\n"
                f"{memory_context}\n\n"
                f"Current query to analyze: {raw_query}"
            )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]

        try:
            raw_json = self.llm.complete_json(messages, temperature=0.0)
            extracted = json.loads(raw_json)
        except (json.JSONDecodeError, Exception) as e:
            raise ValueError(f"Parser LLM failed: {e}")

        confidence = float(extracted.get("confidence", 0.5))
        clarification_needed = (
            bool(extracted.get("clarification_needed"))
            or confidence < CLARIFICATION_THRESHOLD
        )

        # Step 3: Handle ambiguous queries
        if clarification_needed:
            question = extracted.get("clarification_question") or (
                "Could you provide more details about the product type, "
                "location preference, or any required certifications?"
            )
            duration_ms = int((time.time() - start) * 1000)
            self._log_audit(
                state,
                action="clarification_needed",
                input_summary=raw_query,
                output_summary=f"confidence={confidence:.2f}, question={question}",
                duration_ms=duration_ms,
                reasoning=extracted.get("reasoning"),
            )
            state["needs_clarification"] = True
            state["clarification_question"] = question
            state["detected_language"] = extracted.get("original_language", "en")
            state["pipeline_status"] = "needs_clarification"
            return state

        # Step 4: Build the parsed constraints dict
        location = extracted.get("location") or {}
        capacity = extracted.get("capacity") or {}

        constraints = {
            "product_type": extracted.get("product_type"),
            "product_keywords": extracted.get("product_keywords") or [],
            "industry_context": extracted.get("industry_context"),
            "buyer_intent": extracted.get("buyer_intent") or "any",
            "category_hint": extracted.get("category_hint"),

            "location_name": location.get("city") or location.get("country"),
            "location_city": location.get("city"),
            "location_country": location.get("country"),
            "location_region": location.get("region"),
            "location_radius_km": location.get("radius_km"),

            "certifications": extracted.get("certifications") or [],
            "capacity_min": capacity.get("min_value"),
            "capacity_unit": capacity.get("unit"),
            "lead_time_max_days": extracted.get("lead_time_max_days"),

            "query_type": extracted.get("query_type") or "general",
            "complexity": extracted.get("complexity") or "medium",
            "original_language": extracted.get("original_language", "en"),
        }

        # Step 5: Geocode location if present
        if constraints["location_city"] or constraints["location_country"]:
            geocode_query = (
                f"{constraints['location_city']}, {constraints['location_country']}"
                if constraints['location_city'] and constraints['location_country']
                else constraints['location_city'] or constraints['location_country']
            )
            coords = self.geocoder.geocode(geocode_query)
            if coords:
                constraints["location_lat"] = coords[0]
                constraints["location_lng"] = coords[1]
                logger.info(
                    "[parser] Geocoded %r → (%.4f, %.4f)",
                    geocode_query, coords[0], coords[1]
                )

        # Step 6: Build audit summary
        summary_parts = [
            f"product={constraints['product_type']}",
            f"keywords={constraints['product_keywords'][:3]}",
            f"type={constraints['query_type']}",
        ]
        if constraints.get("location_name"):
            summary_parts.append(f"loc={constraints['location_name']}")
        if constraints.get("certifications"):
            summary_parts.append(f"certs={constraints['certifications']}")

        duration_ms = int((time.time() - start) * 1000)
        self._log_audit(
            state,
            action="constraints_extracted_v2",
            input_summary=raw_query[:200],
            output_summary=" | ".join(summary_parts),
            duration_ms=duration_ms,
            reasoning=extracted.get("reasoning"),
        )

        state["parsed_constraints"] = constraints
        state["detected_language"] = extracted.get("original_language", "en")
        state["needs_clarification"] = False
        state["clarification_question"] = None
        state["pipeline_status"] = "running"

        logger.info(
            "[parser] product=%r certs=%s loc=%s type=%s",
            constraints.get("product_type"),
            constraints.get("certifications") or [],
            constraints.get("location_name") or constraints.get("location_country"),
            constraints.get("query_type"),
        )
        return state

    def _load_user_memory(self, user_id: str) -> Optional[str]:
        """Load user's recent successful queries as memory context."""
        if not user_id or user_id == "":
            return None

        try:
            user_uuid = uuid.UUID(user_id)
            with SyncSessionLocal() as db:
                recent = QueryRepository.get_user_recent_queries_sync(
                    db, user_uuid, limit=5
                )
                if not recent:
                    return None

                memory_lines = []
                for q in recent[:3]:
                    memory_lines.append(f"  • {q.raw_query[:100]}")
                return "\n".join(memory_lines)
        except Exception as e:
            logger.debug("[parser] Memory load failed: %s", e)
            return None
