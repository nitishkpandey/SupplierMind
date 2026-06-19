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
from urllib.parse import urljoin, urlparse

from app.agents.compliance_agent import CERT_TAXONOMY
from app.core.llm import get_llm_client
from app.services.page_fetcher import fetch_page_content
from app.utils.text_normalization import clean_optional_text, clean_text_list

logger = logging.getLogger(__name__)

# Hosts that are aggregators/directories/news/social, never a supplier's own
# site. Used as a fallback classifier when the stage-1 LLM call fails, so
# throttling or transient provider errors do not silently drop real candidates.
_DIRECTORY_HOST_MARKERS = (
    "wikipedia.org", "linkedin.com", "facebook.com", "twitter.com", "x.com",
    "youtube.com", "instagram.com", "reddit.com", "quora.com", "medium.com",
    "thomasnet.com", "kompass.com", "europages.", "yellowpages.", "yelp.com",
    "alibaba.com", "made-in-china.com", "indiamart.com", "amazon.", "ebay.",
    "crunchbase.com", "bloomberg.com", "reuters.com", "glassdoor.",
    "g2.com", "capterra.com", "trustpilot.com", "clutch.co", "gartner.com",
)
_DIRECTORY_PATH_MARKERS = ("/blog/", "/news/", "/article", "/press", "/wiki/")
_QUALITY_PAGE_PATHS = (
    "/quality",
    "/quality-management",
    "/certifications",
    "/certificates",
    "/downloads",
    "/about",
    "/about-us",
    "/company",
)
_LOCATION_PAGE_PATHS = (
    "/contact",
    "/kontakt",
    "/imprint",
    "/impressum",
    "/legal-notice",
    "/company/contact",
)
_CERT_PAGE_FETCH_LIMIT = 4
_LOCATION_PAGE_FETCH_LIMIT = 6
_DISCOVERY_CERT_SKIP = {"GDPR"}
_SPECIAL_CERT_PATTERNS = {
    "CE": re.compile(
        r"\bCE(?:\s+(?:certified|certification|compliance|conformity|mark(?:ing)?)|-mark(?:ing)?)\b",
        re.IGNORECASE,
    ),
    "ISO 9001": re.compile(r"\bISO(?:/IEC)?[\s/-]*9001(?:\s*:\s*\d{4})?\b", re.IGNORECASE),
    "ISO 14001": re.compile(r"\bISO(?:/IEC)?[\s/-]*14001(?:\s*:\s*\d{4})?\b", re.IGNORECASE),
    "ISO 27001": re.compile(r"\bISO(?:/IEC)?[\s/-]*27001(?:\s*:\s*\d{4})?\b", re.IGNORECASE),
    "ISO 45001": re.compile(r"\bISO(?:/IEC)?[\s/-]*45001(?:\s*:\s*\d{4})?\b", re.IGNORECASE),
    "ISO 22000": re.compile(r"\bISO(?:/IEC)?[\s/-]*22000(?:\s*:\s*\d{4})?\b", re.IGNORECASE),
    "IATF 16949": re.compile(r"\bIATF[\s/-]*16949(?:\s*:\s*\d{4})?\b", re.IGNORECASE),
    "AS9100": re.compile(r"\bAS[\s/-]*9100[A-Z]?\b", re.IGNORECASE),
    "OEKO-TEX Standard 100": re.compile(
        r"\bOEKO[\s-]*TEX(?:\s+Standard)?\s*100\b",
        re.IGNORECASE,
    ),
}


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
1. Only extract facts EXPLICITLY stated in the source text. If you can't find it, use JSON null, never the string "null".
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
            # LLM unavailable. Do NOT auto-reject —
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
        verified = self._normalise_extracted_fields(
            self._verify_facts(parsed, full_content)
        )

        location_evidence = {}
        if not verified.get("city") and not verified.get("address"):
            location_evidence = self._discover_location_from_site(url)
            if location_evidence:
                verified["city"] = verified.get("city") or location_evidence.get("city")
                verified["country"] = verified.get("country") or location_evidence.get("country")
                verified["address"] = verified.get("address") or location_evidence.get("address")

        # Validate name
        if not verified.get("name"):
            return None

        cert_evidence = self._find_certification_mentions(
            full_content,
            url,
            verified.get("certifications") or None,
        )
        if not verified.get("certifications"):
            cert_evidence = self._discover_certifications_from_site(url, full_content)
            verified["certifications"] = list(cert_evidence.keys())

        # Build source_citations dict
        citations_dict = {}
        raw_citations = verified.get("citations") or {}
        for field in ("name", "description", "certifications", "capacity", "lead_time_days"):
            source_phrase = clean_optional_text(raw_citations.get(field))
            if source_phrase:
                citations_dict[field] = {
                    "url": url,
                    "source_phrase": source_phrase[:300],
                }
        if location_evidence:
            citations_dict["location"] = {
                "url": location_evidence["url"],
                "source_phrase": location_evidence["source_phrase"],
            }
        if cert_evidence:
            first = next(iter(cert_evidence.values()))
            summary_phrase = "; ".join(
                f"{cert}: {evidence['source_phrase']}"
                for cert, evidence in cert_evidence.items()
            )
            existing = citations_dict.get("certifications") or {}
            citations_dict["certifications"] = {
                "url": existing.get("url") or first["url"],
                "source_phrase": existing.get("source_phrase") or summary_phrase[:300],
                "certifications": cert_evidence,
            }

        return {
            "name": verified["name"],
            "description": verified.get("description") or "",
            "primary_products": verified.get("primary_products") or [],
            "industries_served": verified.get("industries_served") or [],
            "category": self._infer_category(verified),
            "country": verified.get("country"),
            "city": verified.get("city"),
            "address": verified.get("address"),
            "latitude": None,
            "longitude": None,
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
            cert_evidence = self._find_certification_mentions(
                source_text,
                "",
                verified.get("certifications") or [],
            )
            dropped = set(map(str, verified.get("certifications") or [])) - set(cert_evidence)
            for cert in sorted(dropped):
                logger.info(
                    "[extraction] Hallucination guard: cert %r is not a verified known standard",
                    cert,
                )
            verified["certifications"] = list(cert_evidence.keys())

        return verified

    @classmethod
    def _normalise_extracted_fields(cls, parsed: dict) -> dict:
        cleaned = dict(parsed)

        for field in (
            "name",
            "description",
            "country",
            "city",
            "address",
            "capacity_unit",
            "website",
            "contact_email",
        ):
            cleaned[field] = clean_optional_text(cleaned.get(field))

        cleaned["primary_products"] = clean_text_list(cleaned.get("primary_products"))
        cleaned["industries_served"] = clean_text_list(cleaned.get("industries_served"))
        cleaned["certifications"] = clean_text_list(cleaned.get("certifications"))

        if cleaned.get("capacity_value") is None:
            cleaned["capacity_unit"] = None

        return cleaned

    def _discover_certifications_from_site(
        self,
        source_url: str,
        source_text: str,
    ) -> dict[str, dict]:
        evidence = self._find_certification_mentions(source_text, source_url)
        if evidence:
            return evidence

        for url in self._quality_page_candidates(source_url)[:_CERT_PAGE_FETCH_LIMIT]:
            page_text = fetch_page_content(url)
            if not page_text:
                continue
            evidence.update(self._find_certification_mentions(page_text, url))
            if evidence:
                break
        return evidence

    @classmethod
    def _find_certification_mentions(
        cls,
        text: str,
        url: str,
        target_certs: Optional[list[str]] = None,
    ) -> dict[str, dict]:
        if not text:
            return {}

        cert_names = target_certs or list(CERT_TAXONOMY.keys())
        evidence: dict[str, dict] = {}
        for cert in cert_names:
            cert_name = str(cert).strip()
            if not cert_name or cert_name in _DISCOVERY_CERT_SKIP:
                continue
            canonical = cls._canonical_discovery_cert(cert_name)
            if canonical is None:
                logger.info(
                    "[extraction] Dropping non-standard certification phrase: %r",
                    cert_name,
                )
                continue
            pattern = cls._cert_pattern(canonical)
            match = pattern.search(text)
            if not match:
                continue
            evidence[canonical] = {
                "url": url,
                "source_phrase": cls._source_phrase(text, match.start(), match.end()),
            }
        return evidence

    @staticmethod
    def _canonical_discovery_cert(cert_name: str) -> str | None:
        compact = re.sub(r":\s*\d{4}", "", cert_name.strip(), flags=re.IGNORECASE)
        compact = re.sub(r"\s+", " ", compact).strip()
        for known in CERT_TAXONOMY:
            if compact.casefold() == known.casefold():
                return known
            if SupplierExtractionService._cert_pattern(known).search(compact):
                return known
        for known in _SPECIAL_CERT_PATTERNS:
            if SupplierExtractionService._cert_pattern(known).search(compact):
                return known
        return None

    @staticmethod
    def _cert_pattern(cert_name: str) -> re.Pattern:
        special = _SPECIAL_CERT_PATTERNS.get(cert_name)
        if special is not None:
            return special
        parts = re.findall(r"[A-Za-z0-9]+", cert_name)
        if not parts:
            return re.compile(r"a^")
        pattern = r"\b" + r"[\s/-]*".join(re.escape(part) for part in parts) + r"\b"
        return re.compile(pattern, re.IGNORECASE)

    @staticmethod
    def _source_phrase(text: str, start: int, end: int) -> str:
        left = max(text.rfind(".", 0, start), text.rfind("\n", 0, start))
        right_candidates = [
            pos for pos in (text.find(".", end), text.find("\n", end)) if pos != -1
        ]
        phrase_start = left + 1 if left != -1 else max(0, start - 100)
        phrase_end = min(right_candidates) + 1 if right_candidates else min(len(text), end + 160)
        phrase = clean_optional_text(text[phrase_start:phrase_end]) or text[start:end]
        return phrase[:300]

    @staticmethod
    def _quality_page_candidates(source_url: str) -> list[str]:
        parsed = urlparse(source_url)
        if not parsed.scheme or not parsed.netloc:
            return []

        base = f"{parsed.scheme}://{parsed.netloc}"
        paths = list(_QUALITY_PAGE_PATHS)
        first_segment = next((p for p in parsed.path.split("/") if p), "")
        if first_segment in {"en", "de", "fr", "es", "it"}:
            paths = [f"/{first_segment}{path}" for path in _QUALITY_PAGE_PATHS] + paths

        candidates: list[str] = []
        seen: set[str] = {source_url.rstrip("/")}
        for path in paths:
            candidate = urljoin(base, path).rstrip("/")
            if candidate in seen:
                continue
            seen.add(candidate)
            candidates.append(candidate)
        return candidates

    def _discover_location_from_site(self, source_url: str) -> dict:
        candidates = self._site_page_candidates(source_url, _LOCATION_PAGE_PATHS)
        for url in candidates[:_LOCATION_PAGE_FETCH_LIMIT]:
            page_text = fetch_page_content(url)
            if not page_text:
                continue
            location = self._find_german_address(page_text, url)
            if location:
                return location
        return {}

    @staticmethod
    def _site_page_candidates(source_url: str, paths: tuple[str, ...]) -> list[str]:
        parsed = urlparse(source_url)
        if not parsed.scheme or not parsed.netloc:
            return []

        base = f"{parsed.scheme}://{parsed.netloc}"
        first_segment = next((p for p in parsed.path.split("/") if p), "")
        candidate_paths = list(paths)
        if first_segment in {"en", "de", "fr", "es", "it", "en_us", "en-gb"}:
            candidate_paths = [f"/{first_segment}{path}" for path in paths] + candidate_paths

        candidates: list[str] = []
        seen: set[str] = {source_url.rstrip("/")}
        for path in candidate_paths:
            candidate = urljoin(base, path).rstrip("/")
            if candidate in seen:
                continue
            seen.add(candidate)
            candidates.append(candidate)
        return candidates

    @staticmethod
    def _find_german_address(text: str, url: str) -> dict:
        pattern = re.compile(
            r"(?P<street>[A-ZÄÖÜ][A-Za-zÄÖÜäöüß .'-]{2,80}?"
            r"(?:straße|strasse|str\.|weg|allee|platz|ring|damm|gasse|ufer)"
            r"\s+\d+[A-Za-z]?)?[,\s]{0,12}"
            r"(?P<postcode>\b\d{5}\b)\s+"
            r"(?P<city>[A-ZÄÖÜ][A-Za-zÄÖÜäöüß.'-]+"
            r"(?:\s+(?:am|an|im|in|ob|unter|[A-ZÄÖÜ][A-Za-zÄÖÜäöüß.'-]+)){0,4})",
            re.IGNORECASE,
        )
        for match in pattern.finditer(text):
            city = clean_optional_text(match.group("city"))
            if not city:
                continue
            city = SupplierExtractionService._clean_german_city(city)
            if not city:
                continue
            street = SupplierExtractionService._clean_german_street(
                clean_optional_text(match.group("street")) or ""
            )
            postcode = match.group("postcode")
            address_parts = [
                part for part in (street, f"{postcode} {city}", "Germany") if part
            ]
            source_phrase = clean_optional_text(
                text[max(0, match.start() - 60): match.end() + 80]
            )
            return {
                "city": city,
                "country": "Germany",
                "address": ", ".join(address_parts),
                "url": url,
                "source_phrase": (source_phrase or f"{postcode} {city}")[:300],
            }
        return {}

    @staticmethod
    def _clean_german_city(city: str) -> str:
        cleaned = re.sub(
            r"\s+(Germany|Deutschland|Tel|Phone|Fax|Email|E-Mail).*$",
            "",
            city,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"\s+(GmbH|AG|KG|Co\.?|Ltd\.?|Limited|Inc\.?).*$",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"\s+[A-ZÄÖÜ][A-Za-zÄÖÜäöüß.'-]*"
            r"(straße|strasse|str\.|weg|allee|platz|ring|damm|gasse|ufer).*$",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        return cleaned.strip(" ,.-")

    @staticmethod
    def _clean_german_street(street: str) -> str:
        cleaned = re.sub(
            r"^.*\b(?:GmbH|AG|KG|Co\.?|Ltd\.?|Limited|Inc\.?)\s+",
            "",
            street,
            flags=re.IGNORECASE,
        )
        return cleaned.strip(" ,.-")

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
