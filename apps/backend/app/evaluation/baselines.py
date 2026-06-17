"""
app/evaluation/baselines.py — Baseline systems for thesis evaluation.

BASELINE A: Keyword SQL Search
  - Extracts raw words from query
  - SQL LIKE search on name + description + category
  - No preprocessing, no ML, no constraint understanding
  - Represents: a simple searchable database

BASELINE B: Manual Discovery Simulation
  - Keyword extraction with stopword removal + domain synonym mapping
  - Category + country extraction via pattern matching (no LLM)
  - Structured SQL filter on category/country
  - Represents: a skilled human using a supplier directory with filters

Neither baseline has:
  - LLM reasoning
  - Vector embeddings
  - Geospatial radius search
  - Agentic retry
  - Compliance checking
  - Explainability

This makes the comparison fair and the SupplierMind advantages clear.
"""

from __future__ import annotations

import logging
import re
import time

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Supplier, SupplierStatus

logger = logging.getLogger(__name__)

# ── Stopwords (words to remove from keyword search) ───────────────────
STOPWORDS = {
    "find", "get", "need", "looking", "want", "supplier", "suppliers",
    "supply", "provide", "provider", "company", "companies", "vendor",
    "vendors", "within", "near", "around", "radius", "certified",
    "certification", "certifications", "with", "and", "or", "the",
    "for", "from", "that", "have", "has", "can", "per", "day", "month",
    "days", "months", "over", "above", "below", "under", "minimum",
    "maximum", "least", "most", "some", "any", "all", "high", "low",
    "good", "best", "quality", "standard", "capacity", "volume",
    "time", "lead", "delivery", "iso", "budget", "cost",
}

# ── Domain synonym map (product → category) ───────────────────────────
# This is what a skilled human would know, implemented as a lookup table
DOMAIN_SYNONYMS: dict[str, str] = {
    # Metals
    "steel": "metals", "aluminum": "metals", "aluminium": "metals",
    "bronze": "metals", "copper": "metals", "iron": "metals",
    "metal": "metals", "alloy": "metals", "brass": "metals",
    "titanium": "metals", "nickel": "metals",
    # Electronics
    "pcb": "electronics", "circuit": "electronics", "sensor": "electronics",
    "electronic": "electronics", "semiconductor": "electronics",
    "component": "electronics", "chip": "electronics",
    # Logistics
    "freight": "logistics", "shipping": "logistics", "transport": "logistics",
    "delivery": "logistics", "courier": "logistics", "cargo": "logistics",
    # Textiles
    "fabric": "textiles", "textile": "textiles", "fiber": "textiles",
    "cloth": "textiles", "garment": "textiles", "yarn": "textiles",
    # Chemicals
    "chemical": "chemicals", "solvent": "chemicals", "reagent": "chemicals",
    "compound": "chemicals", "adhesive": "chemicals",
    # Machinery
    "machine": "machinery", "equipment": "machinery", "automation": "machinery",
    "conveyor": "machinery", "industrial": "machinery", "pump": "machinery",
    # Packaging
    "packaging": "packaging", "box": "packaging", "carton": "packaging",
    "container": "packaging", "pallet": "packaging", "wrap": "packaging",
    # Food
    "ingredient": "food_ingredients", "flavour": "food_ingredients",
    "flavor": "food_ingredients", "additive": "food_ingredients",
    "food": "food_ingredients", "spice": "food_ingredients",
    # Software
    "software": "software_services", "it": "software_services",
    "digital": "software_services", "cloud": "software_services",
    "erp": "software_services", "development": "software_services",
    # Construction
    "concrete": "construction_materials", "insulation": "construction_materials",
    "building": "construction_materials", "construction": "construction_materials",
    "cement": "construction_materials",
}

# ── Country keywords ───────────────────────────────────────────────────
COUNTRY_KEYWORDS: dict[str, str] = {
    "germany": "Germany", "german": "Germany", "deutschland": "Germany",
    "netherlands": "Netherlands", "dutch": "Netherlands", "holland": "Netherlands",
    "poland": "Poland", "polish": "Poland",
    "france": "France", "french": "France",
    "austria": "Austria", "austrian": "Austria",
    "belgium": "Belgium", "belgian": "Belgium",
    "sweden": "Sweden", "swedish": "Sweden",
    "czech": "Czech Republic", "czechia": "Czech Republic",
    "uk": "United Kingdom", "britain": "United Kingdom", "british": "United Kingdom",
    "europe": None,   # Too broad — don't filter by country
    "eu": None,
}


# ═════════════════════════════════════════════════════════════════════
# BASELINE A: Keyword SQL Search
# ═════════════════════════════════════════════════════════════════════

async def keyword_baseline_search(
    raw_query: str,
    db: AsyncSession,
    top_k: int = 5,
) -> tuple[list[dict], int]:
    """
    Baseline A: Pure SQL keyword search.

    Strategy:
    1. Split query into words
    2. SQL LIKE '%word%' on name, description, category fields
    3. OR logic: any match = included
    4. Sort by supplier name (alphabetical — no ranking intelligence)
    5. Return top_k results

    This represents the SIMPLEST possible supplier search tool.
    No preprocessing, no ML, no domain knowledge.

    Returns:
        (list of supplier dicts, execution_time_ms)
    """
    start = time.time()

    # Extract words (raw, no preprocessing)
    words = [
        w for w in re.findall(r'\b[a-zA-Z]{3,}\b', raw_query.lower())
        if len(w) >= 3
    ][:8]  # Use max 8 keywords

    if not words:
        return [], 0

    # Build OR conditions
    conditions = []
    for word in words:
        conditions.append(Supplier.name.ilike(f"%{word}%"))
        conditions.append(Supplier.description.ilike(f"%{word}%"))
        conditions.append(Supplier.category.ilike(f"%{word}%"))
        conditions.append(Supplier.country.ilike(f"%{word}%"))

    result = await db.execute(
        select(Supplier)
        .where(
            and_(
                Supplier.is_active == True,  # noqa: E712
                # Sprint A: pending_review suppliers are HITL-held and must be
                # excluded from baselines so SupplierBench-25 stays reproducible.
                Supplier.status != SupplierStatus.pending_review,
                or_(*conditions),
            )
        )
        .order_by(Supplier.name)   # Alphabetical — simulates "list all matches"
        .limit(top_k)
    )
    suppliers = result.scalars().all()

    exec_ms = int((time.time() - start) * 1000)
    logger.debug(
        "[baseline_a] Query=%r, words=%s, results=%d, time=%dms",
        raw_query[:40], words, len(suppliers), exec_ms
    )

    return [_supplier_to_dict(s) for s in suppliers], exec_ms


# ═════════════════════════════════════════════════════════════════════
# BASELINE B: Manual Discovery Simulation
# ═════════════════════════════════════════════════════════════════════

def _extract_category_manual(query_lower: str) -> str | None:
    """
    Extract product category using domain synonym lookup.
    This is what a skilled human would do when using a supplier directory:
    recognize that "bronze" belongs under "metals".
    No LLM — just a lookup table.
    """
    for keyword, category in DOMAIN_SYNONYMS.items():
        if re.search(rf'\b{re.escape(keyword)}\b', query_lower):
            return category
    return None


def _extract_country_manual(query_lower: str) -> str | None:
    """
    Extract country from query using keyword matching.
    """
    for keyword, country in COUNTRY_KEYWORDS.items():
        if re.search(rf'\b{re.escape(keyword)}\b', query_lower):
            return country  # Returns None for "europe"/"eu" — too broad
    return None


def _extract_keywords_manual(raw_query: str) -> list[str]:
    """
    Extract meaningful keywords after removing stopwords.
    Represents a human's keyword selection when using a search tool.
    """
    words = re.findall(r'\b[a-zA-Z]{3,}\b', raw_query.lower())
    # Remove stopwords and domain-specific terms already handled
    filtered = [
        w for w in words
        if w not in STOPWORDS
        and w not in DOMAIN_SYNONYMS
        and w not in COUNTRY_KEYWORDS
        and len(w) >= 4
    ]
    return list(dict.fromkeys(filtered))[:5]  # Deduplicate, max 5


async def manual_baseline_search(
    raw_query: str,
    db: AsyncSession,
    top_k: int = 5,
) -> tuple[list[dict], int]:
    """
    Baseline B: Manual discovery simulation.

    Strategy:
    1. Extract category using domain synonym lookup (no LLM)
    2. Extract country using pattern matching (no LLM)
    3. Extract remaining keywords after stopword removal
    4. SQL filter: category + country + keyword LIKE search
    5. Sort by lead_time ascending (simulates "I want fastest delivery")
    6. Return top_k results

    This represents what a procurement professional does manually:
    - Knows their product categories
    - Can identify country requirements
    - Does keyword search in a supplier directory
    - Manually picks the fastest suppliers

    What it CANNOT do (unlike SupplierMind):
    - Geospatial radius search
    - Certification validation
    - Agentic retry on low results
    - Semantic understanding ("bronze" ≠ "metal" for keyword search)
    - Explainability
    - Confidence scoring

    Returns:
        (list of supplier dicts, execution_time_ms)
    """
    start = time.time()
    query_lower = raw_query.lower()

    # Step 1: Category extraction (domain knowledge lookup)
    category = _extract_category_manual(query_lower)

    # Step 2: Country extraction
    country = _extract_country_manual(query_lower)

    # Step 3: Additional keywords
    extra_keywords = _extract_keywords_manual(raw_query)

    # Step 4: Build query
    conditions = [
        Supplier.is_active == True,  # noqa: E712
        # Sprint A: exclude HITL-held pending_review suppliers from the
        # benchmark baseline to keep SupplierBench-25 reproducible.
        Supplier.status != SupplierStatus.pending_review,
    ]

    if category:
        conditions.append(Supplier.category == category)

    if country:
        conditions.append(Supplier.country == country)

    # Add keyword conditions for remaining terms
    if extra_keywords and not (category and country):
        # Use keywords only if we don't have strong structured filters
        kw_conditions = []
        for kw in extra_keywords:
            kw_conditions.append(Supplier.description.ilike(f"%{kw}%"))
        if kw_conditions:
            conditions.append(or_(*kw_conditions))

    result = await db.execute(
        select(Supplier)
        .where(and_(*conditions))
        .order_by(Supplier.lead_time_days.asc().nullslast())  # Sort by fastest delivery
        .limit(top_k)
    )
    suppliers = result.scalars().all()

    exec_ms = int((time.time() - start) * 1000)
    logger.debug(
        "[baseline_b] Query=%r, category=%s, country=%s, keywords=%s, results=%d, time=%dms",
        raw_query[:40], category, country, extra_keywords, len(suppliers), exec_ms
    )

    return [_supplier_to_dict(s) for s in suppliers], exec_ms


def _supplier_to_dict(supplier: Supplier) -> dict:
    """Convert SQLAlchemy Supplier model to plain dict."""
    return {
        "id": str(supplier.id),
        "name": supplier.name,
        "description": supplier.description,
        "category": supplier.category,
        "country": supplier.country,
        "city": supplier.city,
        "latitude": supplier.latitude,
        "longitude": supplier.longitude,
        "certifications": supplier.certifications or [],
        "capacity_value": supplier.capacity_value,
        "capacity_unit": supplier.capacity_unit,
        "lead_time_days": supplier.lead_time_days,
    }
