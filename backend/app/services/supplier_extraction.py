"""
app/services/supplier_extraction.py — Two-stage sync extraction with citations.

STAGE 1 (cheap, fast): Determine if a search result is a supplier.
STAGE 2 (rich, slow): For confirmed suppliers, fetch the full page and
                     extract structured data with citations and verification.

HALLUCINATION GUARDS:
- Numeric claims (capacity, lead time) must appear verbatim in source text
- Certifications must match source text
- Unverifiable facts are set to None with a log message
"""

import json
import logging
import re
from typing import Optional
from urllib.parse import urlparse

from app.core.llm import get_llm_client
from app.services.geocoding import GeocodingService
from app.services.page_fetcher import fetch_page_content

logger = logging.getLogger(__name__)

# Hosts that are aggregators/directories/news/social, never a supplier's own
# site. Used as a fallback classifier when the stage-1 LLM call fails (e.g.
# Groq rate-limit), so throttling doesn't silently drop real candidates.
_DIRECTORY_HOST_MARKERS = (
    "wikipedia.org", "linkedin.com", "facebook.com", "twitter.com", "x.com",
    "youtube.com", "instagram.com", "reddit.com", "quora.com", "medium.com",
    "thomasnet.com", "kompass.com", "europages.", "yellowpages.", "yelp.com",
    "alibaba.com", "made-in-china.com", "indiamart.com", "amazon.", "ebay.",
    "crunchbase.com", "bloomberg.com", "reuters.com", "glassdoor.",
    "g2.com", "capterra.com", "trustpilot.com", "clutch.co", "gartner.com",
)
_DIRECTORY_PATH_MARKERS = ("/blog/", "/news/", "/article", "/press", "/wiki/")


STAGE_1_PROMPT = """You are evaluating whether a web search result is a supplier company.

Look at the page title, URL, and snippet. Decide:
- Is this a supplier/manufacturer/distributor's own website? (NOT a directory, blog, news article, marketplace listing)
- What is the company's name?

Reject (is_supplier=false):
- Directories listing many suppliers
- News articles, blogs, press releases
- Marketplace category pages
- Government databases, Wikipedia

Accept (is_supplier=true):
- Company's own website (homepage, about, products)
- Manufacturer profile pages
- Distributor/reseller official pages

Return JSON only:
{
  "is_supplier": true | false,
  "company_name": "name or null",
  "confidence": 0.0 to 1.0,
  "rejection_reason": "if false, brief reason"
}"""


STAGE_2_PROMPT = """You are extracting structured supplier data from a company's webpage.

CRITICAL RULES:
1. Only extract facts EXPLICITLY stated in the source text. If you can't find it, use null.
2. Quote source text for each non-trivial field in the "citations" object.
3. Numeric values MUST appear verbatim in source text — do not infer or estimate.
4. The "description" field is critical for semantic search — write 2-4 rich sentences.
5. Return ONLY JSON, no markdown.

DESCRIPTION REQUIREMENTS (most important):
Write 2-4 sentences that include:
- WHAT they make/sell (be specific: not "tools" but "precision torque screwdrivers")
- WHO they serve (industries, regions)
- HOW they differentiate (technical capabilities, certifications, history)

Good example:
"Manufactures precision electric and pneumatic screwdrivers for industrial assembly, with torque ranges from 0.1 to 50 Nm. Specializes in automotive and aerospace manufacturing applications across European markets. Founded 1936; family-owned with ISO 9001:2015 and IATF 16949 certification."

Bad examples (rejected):
"Manufacturer of tools."
"German company offering various products."

OUTPUT JSON:

{
  "name": "exact company name",
  "description": "2-4 sentence rich description",
  "primary_products": ["specific product type 1", "type 2"],
  "industries_served": ["automotive", "aerospace"] or [],

  "country": "country name or null",
  "city": "city name or null",
  "address": "full address if listed, or null",

  "certifications": ["ISO 9001", ...] or [],

  "capacity_value": number or null,
  "capacity_unit": "unit string or null",
  "lead_time_days": number or null,

  "website": "homepage URL",
  "contact_email": "email or null",

  "citations": {
    "name": "exact source phrase",
    "description": "exact source phrase or 'composed from multiple sentences'",
    "certifications": "exact phrase where certs are mentioned, or null",
    "capacity": "exact phrase where capacity number appears, or null",
    "lead_time_days": "exact phrase, or null"
  },

  "confidence": 0.0 to 1.0
}"""


class SupplierExtractionService:
    """Two-stage sync LLM extraction with citation tracking and hallucination guards."""

    def __init__(self) -> None:
        self.llm = get_llm_client()
        self.geocoder = GeocodingService()

    def stage1_classify(
        self, title: str, url: str, snippet: str
    ) -> dict:
        """
        Stage 1: Cheap classification. SYNC.
        Returns: {is_supplier, company_name, confidence, rejection_reason}
        """
        text = f"TITLE: {title}\nURL: {url}\nSNIPPET: {snippet[:500]}"

        try:
            raw = self.llm.complete_json(
                [
                    {"role": "system", "content": STAGE_1_PROMPT},
                    {"role": "user", "content": text},
                ],
                temperature=0.0,
                max_tokens=200,
            )
            return json.loads(raw)
        except Exception as e:
            # LLM unavailable (commonly Groq rate-limit). Do NOT auto-reject —
            # that silently discards real suppliers when the API is throttled.
            # Fall back to a URL heuristic so only obvious directories drop.
            logger.warning("[extraction] Stage 1 LLM failed, using URL heuristic: %s", e)
            is_directory = self._looks_like_directory(url)
            return {
                "is_supplier": not is_directory,
                "company_name": title or None,
                "confidence": 0.0 if is_directory else 0.5,
                "rejection_reason": "directory/aggregator URL" if is_directory else None,
                "classification_error": True,
            }

    @staticmethod
    def _looks_like_directory(url: str) -> bool:
        """Heuristic: is this URL an aggregator/directory/news/social page?"""
        try:
            parsed = urlparse(url)
        except Exception:
            return True
        host = (parsed.netloc or "").lower()
        path = (parsed.path or "").lower()
        if any(marker in host for marker in _DIRECTORY_HOST_MARKERS):
            return True
        if any(marker in path for marker in _DIRECTORY_PATH_MARKERS):
            return True
        return False

    def stage2_extract(
        self, url: str
    ) -> Optional[dict]:
        """
        Stage 2: Rich extraction from full page content. SYNC.
        Fetches the page, runs LLM extraction, verifies facts.
        Returns enriched supplier dict or None on failure.
        """
        # Fetch the full page (sync)
        full_content = fetch_page_content(url)
        if not full_content:
            logger.debug("[extraction] Could not fetch %s for stage 2", url)
            return None

        text = f"SOURCE URL: {url}\n\nPAGE CONTENT:\n{full_content[:8000]}"

        try:
            raw = self.llm.complete_json(
                [
                    {"role": "system", "content": STAGE_2_PROMPT},
                    {"role": "user", "content": text},
                ],
                temperature=0.0,
                max_tokens=1500,
            )
            parsed = json.loads(raw)
        except Exception as e:
            logger.warning("[extraction] Stage 2 LLM failed: %s", e)
            return None

        # Verification: hallucination guards
        verified = self._verify_facts(parsed, full_content)

        # Validate name
        if not verified.get("name") or not isinstance(verified["name"], str):
            return None

        # Geocode if location available
        lat, lng = None, None
        if verified.get("city") and verified.get("country"):
            coords = self.geocoder.geocode(
                f"{verified['city']}, {verified['country']}"
            )
            if coords:
                lat, lng = coords

        # Build source_citations dict
        citations_dict = {}
        raw_citations = verified.get("citations") or {}
        for field in ("name", "description", "certifications", "capacity", "lead_time_days"):
            if raw_citations.get(field):
                citations_dict[field] = {
                    "url": url,
                    "source_phrase": str(raw_citations[field])[:300],
                }

        return {
            "name": verified["name"].strip(),
            "description": verified.get("description") or "",
            "primary_products": verified.get("primary_products") or [],
            "industries_served": verified.get("industries_served") or [],
            "category": self._infer_category(verified),
            "country": verified.get("country"),
            "city": verified.get("city"),
            "address": verified.get("address"),
            "latitude": lat,
            "longitude": lng,
            "certifications": verified.get("certifications") or [],
            "capacity_value": verified.get("capacity_value"),
            "capacity_unit": verified.get("capacity_unit"),
            "lead_time_days": verified.get("lead_time_days"),
            "website": verified.get("website") or url,
            "contact_email": verified.get("contact_email"),
            "source": "web_discovery",
            "source_url": url,
            "source_citations": citations_dict,
            "extraction_confidence": float(verified.get("confidence", 0.5)),
        }

    def _verify_facts(self, parsed: dict, source_text: str) -> dict:
        """
        Hallucination guard: verify numeric and certification claims appear
        in source text. Nullify unverifiable facts.
        """
        source_lower = source_text.lower()
        verified = dict(parsed)

        # Verify capacity_value
        if verified.get("capacity_value") is not None:
            cap_val = verified["capacity_value"]
            try:
                cap_num = float(cap_val)
                cap_int = int(cap_num) if cap_num == int(cap_num) else cap_num
                cap_str = str(cap_int)
                cap_formats = [cap_str]
                if cap_num >= 1000:
                    cap_formats.append(f"{int(cap_num):,}")
                if not any(c in source_text for c in cap_formats):
                    logger.info(
                        "[extraction] Hallucination guard: capacity %s not in source",
                        cap_str
                    )
                    verified["capacity_value"] = None
                    verified["capacity_unit"] = None
            except (TypeError, ValueError):
                verified["capacity_value"] = None
                verified["capacity_unit"] = None

        # Verify lead_time_days
        if verified.get("lead_time_days") is not None:
            lt = verified["lead_time_days"]
            text_around_leadtime = re.findall(
                r".{0,80}lead.{0,80}", source_lower
            )
            joined = " ".join(text_around_leadtime)
            if str(lt) not in joined:
                logger.info(
                    "[extraction] Hallucination guard: lead time %s not verifiable",
                    lt
                )
                verified["lead_time_days"] = None

        # Verify certifications
        if verified.get("certifications"):
            verified_certs = []
            for cert in verified["certifications"]:
                cert_clean = str(cert).lower().replace(":", "").replace(" ", "")
                source_clean = source_lower.replace(":", "").replace(" ", "")
                if cert_clean in source_clean or str(cert).lower() in source_lower:
                    verified_certs.append(cert)
                else:
                    logger.info(
                        "[extraction] Hallucination guard: cert %r not in source",
                        cert
                    )
            verified["certifications"] = verified_certs

        return verified

    def _infer_category(self, parsed: dict) -> Optional[str]:
        """Heuristic category from product/industry keywords."""
        text = (
            (parsed.get("description") or "") + " " +
            " ".join(parsed.get("primary_products") or []) + " " +
            " ".join(parsed.get("industries_served") or [])
        ).lower()

        category_keywords = {
            "metals": ["metal", "steel", "aluminum", "bronze", "copper", "iron", "alloy", "brass"],
            "electronics": ["pcb", "circuit", "sensor", "electronic", "semiconductor", "monitor", "display"],
            "tools_hardware": ["screwdriver", "drill", "wrench", "tool", "fastener", "screw"],
            "logistics": ["freight", "shipping", "transport", "logistics", "delivery"],
            "textiles": ["fabric", "textile", "fiber", "cloth"],
            "chemicals": ["chemical", "solvent", "reagent", "adhesive"],
            "machinery": ["machinery", "equipment", "automation", "conveyor"],
            "packaging": ["packaging", "carton", "container"],
            "food_ingredients": ["food", "ingredient", "additive"],
            "software_services": ["software", "saas", "platform", "cloud"],
            "construction_materials": ["concrete", "insulation", "building material"],
        }

        for category, keywords in category_keywords.items():
            if any(kw in text for kw in keywords):
                return category

        return None

    # Keep the old method name for backward compatibility
    def extract_from_web_result(
        self,
        title: str,
        url: str,
        content: str,
    ) -> Optional[dict]:
        """Legacy single-pass extraction. Delegates to two-stage internally."""
        stage1 = self.stage1_classify(title, url, content)
        if not stage1.get("is_supplier") or stage1.get("confidence", 0) < 0.5:
            return None
        return self.stage2_extract(url)
