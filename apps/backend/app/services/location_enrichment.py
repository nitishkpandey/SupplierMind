"""Geoapify-backed supplier location validation and enrichment."""

import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings
from app.utils.text_normalization import clean_optional_text, strip_accents

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
    confidence: float | None


@dataclass(frozen=True)
class LocationResolution:
    location: VerifiedLocation | None
    rejection_reasons: tuple[str, ...] = ()


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
        places_categories: str | None = None,
    ) -> None:
        self.geocoding_api_key = geocoding_api_key if geocoding_api_key is not None else settings.GEOAPIFY_GEOCODING_API_KEY
        self.places_api_key = places_api_key if places_api_key is not None else settings.GEOAPIFY_PLACES_API_KEY
        self.client = client or httpx.Client()
        self.timeout_seconds = timeout_seconds or settings.GEOAPIFY_TIMEOUT_SECONDS
        self.min_confidence = min_confidence if min_confidence is not None else settings.GEOAPIFY_MIN_CONFIDENCE
        self.places_categories = places_categories or settings.GEOAPIFY_PLACES_CATEGORIES

    @property
    def is_available(self) -> bool:
        return bool(self.geocoding_api_key or self.places_api_key)

    def enrich(
        self,
        supplier: dict,
        constraints: Mapping[str, Any] | None = None,
    ) -> VerifiedLocation | None:
        return self.resolve(supplier, constraints).location

    def resolve(
        self,
        supplier: dict,
        constraints: Mapping[str, Any] | None = None,
    ) -> LocationResolution:
        constraints = constraints or {}
        if self._supplier_conflicts_with_constraints(supplier, constraints):
            return LocationResolution(
                location=None,
                rejection_reasons=("supplier_country_conflict",),
            )

        rejection_reasons: list[str] = []

        if self.geocoding_api_key:
            query, expected_name = self._build_geocoding_query(supplier, constraints)
            if query:
                resolution = self._geocode(query, expected_name=expected_name)
                if resolution.location:
                    constraint_reason = self._constraint_rejection_reason(
                        resolution.location,
                        constraints,
                        path="geocoding",
                    )
                    if constraint_reason is None:
                        return resolution
                    rejection_reasons.append(constraint_reason)
                rejection_reasons.extend(resolution.rejection_reasons)
            else:
                rejection_reasons.append("geocoding_query_unavailable")

        if self.places_api_key:
            resolution = self._places_lookup(
                name=clean_optional_text(supplier.get("name")),
                constraints=constraints,
            )
            if resolution.location:
                constraint_reason = self._constraint_rejection_reason(
                    resolution.location,
                    constraints,
                    path="places",
                )
                if constraint_reason is None:
                    return resolution
                rejection_reasons.append(constraint_reason)
            rejection_reasons.extend(resolution.rejection_reasons)

        if not rejection_reasons:
            rejection_reasons.append("location_service_unavailable")
        return LocationResolution(
            location=None,
            rejection_reasons=tuple(dict.fromkeys(rejection_reasons)),
        )

    def _build_geocoding_query(
        self,
        supplier: dict,
        constraints: Mapping[str, Any],
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

    def _geocode(
        self,
        text: str,
        *,
        expected_name: str | None = None,
    ) -> LocationResolution:
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
                return LocationResolution(
                    location=None,
                    rejection_reasons=("geocoding_no_feature",),
                )
            return self._location_from_feature(
                features[0],
                source="geoapify_geocoding",
                path="geocoding",
                expected_name=expected_name,
                require_confidence=True,
            )
        except Exception as e:
            logger.info("[geoapify] Geocoding failed for %r: %s", text, e)
            return LocationResolution(
                location=None,
                rejection_reasons=("geocoding_request_failed",),
            )

    def _places_lookup(
        self,
        *,
        name: str | None,
        constraints: Mapping[str, Any],
    ) -> LocationResolution:
        if not name:
            return LocationResolution(
                location=None,
                rejection_reasons=("places_company_name_missing",),
            )

        country = clean_optional_text(
            constraints.get("location_country") or constraints.get("country")
        )
        region = clean_optional_text(
            constraints.get("location_city") or constraints.get("location_name")
        )
        location_filter = self._location_filter(region=region, country=country)
        if not location_filter:
            return LocationResolution(
                location=None,
                rejection_reasons=("places_context_unbounded",),
            )

        params: dict[str, str | int] = {
            "categories": self.places_categories,
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
                return LocationResolution(
                    location=None,
                    rejection_reasons=("places_no_feature",),
                )
            return self._location_from_feature(
                features[0],
                source="geoapify_places",
                path="places",
                expected_name=name,
                require_confidence=False,
            )
        except Exception as e:
            logger.info("[geoapify] Places lookup failed for %r: %s", name, e)
            return LocationResolution(
                location=None,
                rejection_reasons=("places_request_failed",),
            )

    def _location_from_feature(
        self,
        feature: dict,
        *,
        source: str,
        path: str,
        expected_name: str | None = None,
        require_confidence: bool,
    ) -> LocationResolution:
        props = feature.get("properties") or {}
        rejection_reasons: list[str] = []
        if expected_name and not self._name_matches(expected_name, props):
            rejection_reasons.append(f"{path}_company_name_mismatch")

        city = clean_optional_text(
            props.get("city")
            or props.get("town")
            or props.get("village")
            or props.get("municipality")
            or props.get("county")
        )
        country = clean_optional_text(props.get("country"))
        coords = (feature.get("geometry") or {}).get("coordinates") or []
        confidence, confidence_valid = self._confidence(props)

        if not city:
            rejection_reasons.append(f"{path}_city_missing")
        if not country:
            rejection_reasons.append(f"{path}_country_missing")
        if len(coords) < 2:
            rejection_reasons.append(f"{path}_coordinates_missing")
        if require_confidence:
            if confidence is None and confidence_valid:
                rejection_reasons.append(f"{path}_confidence_missing")
            elif not confidence_valid:
                rejection_reasons.append(f"{path}_confidence_invalid")
            elif confidence is not None and confidence < self.min_confidence:
                rejection_reasons.append(f"{path}_confidence_below_threshold")

        if rejection_reasons:
            return LocationResolution(
                location=None,
                rejection_reasons=tuple(rejection_reasons),
            )

        assert city is not None
        assert country is not None
        return LocationResolution(
            location=VerifiedLocation(
                city=city,
                country=country,
                latitude=float(coords[1]),
                longitude=float(coords[0]),
                formatted_address=clean_optional_text(props.get("formatted")),
                source=source,
                confidence=confidence,
            ),
        )

    @staticmethod
    def _confidence(props: dict) -> tuple[float | None, bool]:
        rank = props.get("rank") or {}
        value = rank.get("confidence")
        if value is None:
            return None, True
        try:
            return float(value), True
        except (TypeError, ValueError):
            return None, False

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
    def _matches_constraints(location: VerifiedLocation, constraints: Mapping[str, Any]) -> bool:
        return GeoapifyLocationService._constraint_rejection_reason(
            location,
            constraints,
            path="location",
        ) is None

    @staticmethod
    def _constraint_rejection_reason(
        location: VerifiedLocation,
        constraints: Mapping[str, Any],
        *,
        path: str,
    ) -> str | None:
        requested_country = clean_optional_text(
            constraints.get("location_country") or constraints.get("country")
        )
        if requested_country and location.country.casefold() != requested_country.casefold():
            return f"{path}_country_conflict"
        requested_city = clean_optional_text(constraints.get("location_city"))
        if (
            requested_city
            and not constraints.get("location_radius_km")
            and not _is_region_filter(requested_city)
            and _normalize_location_name(location.city) != _normalize_location_name(requested_city)
        ):
            return f"{path}_city_conflict"
        return None

    @staticmethod
    def _supplier_conflicts_with_constraints(supplier: dict, constraints: Mapping[str, Any]) -> bool:
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


def _normalize_location_name(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", strip_accents(value).casefold()))


def _is_region_filter(value: str) -> bool:
    return bool(clean_optional_text(value)) and value.casefold() in _LOCATION_RECTS


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
