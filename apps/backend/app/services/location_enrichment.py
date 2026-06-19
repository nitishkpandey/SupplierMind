"""Geoapify-backed supplier location validation and enrichment."""

import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings
from app.utils.text_normalization import clean_optional_text

logger = logging.getLogger(__name__)

GEOCODING_URL = "https://api.geoapify.com/v1/geocode/search"
PLACES_URL = "https://api.geoapify.com/v2/places"

_LOCATION_RECTS = {
    "germany": "rect:5.866,47.270,15.042,55.058",
    "deutschland": "rect:5.866,47.270,15.042,55.058",
    "bavaria": "rect:8.976,47.270,13.839,50.565",
    "bayern": "rect:8.976,47.270,13.839,50.565",
}


@dataclass(frozen=True)
class VerifiedLocation:
    city: str
    country: str
    latitude: float
    longitude: float
    formatted_address: str | None
    source: str
    confidence: float


class GeoapifyLocationService:
    """Resolve supplier locations using exactly two Geoapify paths.

    Path 1: validate extracted location text or query-bounded company text via Geocoding.
    Path 2: if the page has no usable location, search Places by company name
    with country/region context from the query.
    """

    def __init__(
        self,
        *,
        geocoding_api_key: str | None = None,
        places_api_key: str | None = None,
        client: Any | None = None,
        timeout_seconds: float | None = None,
        min_confidence: float | None = None,
    ) -> None:
        self.geocoding_api_key = geocoding_api_key if geocoding_api_key is not None else settings.GEOAPIFY_GEOCODING_API_KEY
        self.places_api_key = places_api_key if places_api_key is not None else settings.GEOAPIFY_PLACES_API_KEY
        self.client = client or httpx.Client()
        self.timeout_seconds = timeout_seconds or settings.GEOAPIFY_TIMEOUT_SECONDS
        self.min_confidence = min_confidence if min_confidence is not None else settings.GEOAPIFY_MIN_CONFIDENCE

    @property
    def is_available(self) -> bool:
        return bool(self.geocoding_api_key or self.places_api_key)

    def enrich(self, supplier: dict, constraints: dict | None = None) -> VerifiedLocation | None:
        constraints = constraints or {}
        if self._supplier_conflicts_with_constraints(supplier, constraints):
            return None

        if self.geocoding_api_key:
            query, expected_name = self._build_geocoding_query(supplier, constraints)
            if query:
                location = self._geocode(query, expected_name=expected_name)
                if location and self._matches_constraints(location, constraints):
                    return location

        if self.places_api_key:
            location = self._places_lookup(
                name=clean_optional_text(supplier.get("name")),
                constraints=constraints,
            )
            if location and self._matches_constraints(location, constraints):
                return location

        return None

    def _build_geocoding_query(
        self,
        supplier: dict,
        constraints: dict,
    ) -> tuple[str | None, str | None]:
        address = clean_optional_text(supplier.get("address"))
        city = clean_optional_text(supplier.get("city"))
        country = clean_optional_text(supplier.get("country"))

        if address:
            address_lower = address.casefold()
            parts = [address]
            for value in (city, country):
                if value and value.casefold() not in address_lower:
                    parts.append(value)
            return ", ".join(parts), None

        name = clean_optional_text(supplier.get("name"))
        region = clean_optional_text(
            constraints.get("location_city") or constraints.get("location_name")
        )
        constraint_country = clean_optional_text(
            constraints.get("location_country") or constraints.get("country")
        )

        if city:
            parts = [value for value in (city, country or constraint_country) if value]
            return ", ".join(parts), None

        context = self._dedupe_location_parts([region, constraint_country])
        if name and context:
            return ", ".join([name, *context]), name

        if name and country:
            return ", ".join([name, country]), name

        return None, None

    def _geocode(self, text: str, *, expected_name: str | None = None) -> VerifiedLocation | None:
        try:
            response = self.client.get(
                GEOCODING_URL,
                params={
                    "text": text,
                    "limit": 1,
                    "format": "geojson",
                    "apiKey": self.geocoding_api_key,
                },
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            features = response.json().get("features") or []
            if not features:
                return None
            return self._location_from_feature(
                features[0],
                source="geoapify_geocoding",
                expected_name=expected_name,
            )
        except Exception as e:
            logger.info("[geoapify] Geocoding failed for %r: %s", text, e)
            return None

    def _places_lookup(
        self,
        *,
        name: str | None,
        constraints: dict,
    ) -> VerifiedLocation | None:
        if not name:
            return None

        country = clean_optional_text(
            constraints.get("location_country") or constraints.get("country")
        )
        region = clean_optional_text(
            constraints.get("location_city") or constraints.get("location_name")
        )
        location_filter = self._location_filter(region=region, country=country)
        if not location_filter:
            return None

        params = {
            "categories": settings.GEOAPIFY_PLACES_CATEGORIES,
            "name": name,
            "limit": 1,
            "apiKey": self.places_api_key,
            "filter": location_filter,
        }

        try:
            response = self.client.get(
                PLACES_URL,
                params=params,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            features = response.json().get("features") or []
            if not features:
                return None
            return self._location_from_feature(
                features[0],
                source="geoapify_places",
                expected_name=name,
            )
        except Exception as e:
            logger.info("[geoapify] Places lookup failed for %r: %s", name, e)
            return None

    def _location_from_feature(
        self,
        feature: dict,
        *,
        source: str,
        expected_name: str | None = None,
    ) -> VerifiedLocation | None:
        props = feature.get("properties") or {}
        if expected_name and not self._name_matches(expected_name, props):
            return None

        city = clean_optional_text(
            props.get("city")
            or props.get("town")
            or props.get("village")
            or props.get("municipality")
            or props.get("county")
        )
        country = clean_optional_text(props.get("country"))
        confidence = self._confidence(props)
        coords = (feature.get("geometry") or {}).get("coordinates") or []

        if not city or not country or len(coords) < 2 or confidence < self.min_confidence:
            return None

        return VerifiedLocation(
            city=city,
            country=country,
            latitude=float(coords[1]),
            longitude=float(coords[0]),
            formatted_address=clean_optional_text(props.get("formatted")),
            source=source,
            confidence=confidence,
        )

    @staticmethod
    def _confidence(props: dict) -> float:
        rank = props.get("rank") or {}
        value = rank.get("confidence")
        try:
            return float(value)
        except (TypeError, ValueError):
            return 1.0

    @staticmethod
    def _name_matches(expected_name: str, props: dict) -> bool:
        place_name = clean_optional_text(props.get("name") or props.get("address_line1"))
        if not place_name:
            return False

        expected_normalized = _normalize_name(expected_name)
        place_normalized = _normalize_name(place_name)
        if not expected_normalized or not place_normalized:
            return False
        if expected_normalized in place_normalized or place_normalized in expected_normalized:
            return True

        return bool(_significant_name_tokens(expected_normalized) & _significant_name_tokens(place_normalized))

    @staticmethod
    def _location_filter(region: str | None, country: str | None) -> str | None:
        for value in (region, country):
            if not value:
                continue
            rect = _LOCATION_RECTS.get(value.casefold())
            if rect:
                return rect
        return None

    @staticmethod
    def _dedupe_location_parts(values: list[str | None]) -> list[str]:
        parts: list[str] = []
        seen: set[str] = set()
        for value in values:
            cleaned = clean_optional_text(value)
            if not cleaned:
                continue
            key = cleaned.casefold()
            if key in seen:
                continue
            seen.add(key)
            parts.append(cleaned)
        return parts

    @staticmethod
    def _matches_constraints(location: VerifiedLocation, constraints: dict) -> bool:
        requested_country = clean_optional_text(
            constraints.get("location_country") or constraints.get("country")
        )
        if requested_country and location.country.casefold() != requested_country.casefold():
            return False
        return True

    @staticmethod
    def _supplier_conflicts_with_constraints(supplier: dict, constraints: dict) -> bool:
        requested_country = clean_optional_text(
            constraints.get("location_country") or constraints.get("country")
        )
        supplier_country = clean_optional_text(supplier.get("country"))
        if (
            requested_country
            and supplier_country
            and supplier_country.casefold() != requested_country.casefold()
        ):
            return True
        return False


def _normalize_name(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def _significant_name_tokens(value: str) -> set[str]:
    legal_suffixes = {
        "ag",
        "co",
        "company",
        "gmbh",
        "group",
        "inc",
        "kg",
        "limited",
        "llc",
        "ltd",
        "sa",
        "sarl",
        "srl",
    }
    return {
        token
        for token in value.split()
        if len(token) >= 3 and token not in legal_suffixes
    }


def get_location_enrichment_service() -> GeoapifyLocationService:
    return GeoapifyLocationService()
