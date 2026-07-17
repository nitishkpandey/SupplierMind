"""
app/services/geocoding.py — Location name to coordinates using Nominatim.

Cache strategy:
1. Check PostgreSQL geocode_cache table first
2. On miss: call Nominatim API
3. Store result in cache forever (city coordinates don't change)

Rate limit: Nominatim allows 1 req/sec. We cache aggressively so
in practice we'll only call Nominatim for unique location names.
"""

import logging
import time
from dataclasses import dataclass
from typing import Optional

from geopy.exc import GeocoderServiceError, GeocoderTimedOut
from geopy.geocoders import Nominatim

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GeocodeResult:
    lat: float
    lng: float
    city: str | None = None
    country: str | None = None
    region: str | None = None
    display_name: str | None = None


# In-memory cache for the current session (fast lookup before DB check)
_memory_cache: dict[str, GeocodeResult] = {}


class GeocodingService:
    """
    Converts location names to (latitude, longitude) coordinates.

    Uses a two-level cache:
    1. In-memory dict (fastest — no DB round trip)
    2. PostgreSQL geocode_cache table (persists across restarts)
    3. Nominatim API (only on cache miss)
    """

    def __init__(self) -> None:
        self._geolocator = Nominatim(
            user_agent=settings.NOMINATIM_USER_AGENT,
            timeout=10,
        )

    def geocode(self, location_name: str) -> Optional[tuple[float, float]]:
        """
        Convert a location name to (lat, lng) coordinates.

        Args:
            location_name: e.g. "Bremen", "Bremen, Germany", "Germany"

        Returns:
            (latitude, longitude) tuple, or None if not found
        """
        result = self.geocode_details(location_name)
        if not result:
            return None
        return (result.lat, result.lng)

    def geocode_details(self, location_name: str) -> GeocodeResult | None:
        """Convert a location name to coordinates plus normalized address parts."""
        # Normalise the key
        key = location_name.strip().lower()

        # Level 1: in-memory cache
        if key in _memory_cache:
            logger.debug("[geocoding] Memory cache hit: %r", location_name)
            return _memory_cache[key]

        # Level 2: Call Nominatim (DB cache check happens in sync routes)
        # For the agents, we use the in-memory cache + API only
        # (DB cache is populated via the admin ingestion flow)
        result = self._call_nominatim(location_name)
        if result:
            _memory_cache[key] = result

        return result

    def _call_nominatim(self, location_name: str) -> GeocodeResult | None:
        """Call the Nominatim API with rate limit respect."""
        try:
            logger.info("[geocoding] Calling Nominatim for: %r", location_name)
            # Nominatim rate limit: 1 request per second
            time.sleep(1.1)
            location = self._geolocator.geocode(
                location_name,
                addressdetails=True,
                language="en",
            )
            if location:
                address = (location.raw or {}).get("address") or {}
                result = GeocodeResult(
                    lat=location.latitude,
                    lng=location.longitude,
                    city=_first_text(
                        address,
                        "city",
                        "town",
                        "village",
                        "municipality",
                        "county",
                    ),
                    country=_first_text(address, "country"),
                    region=_first_text(address, "state", "region"),
                    display_name=getattr(location, "address", None),
                )
                logger.info(
                    "[geocoding] Found: %r → (%.4f, %.4f), city=%r, country=%r",
                    location_name, result.lat, result.lng, result.city, result.country
                )
                return result
            else:
                logger.warning("[geocoding] No result for: %r", location_name)
                return None
        except (GeocoderTimedOut, GeocoderServiceError) as e:
            logger.error("[geocoding] API error for %r: %s", location_name, e)
            return None


def _first_text(mapping: dict, *keys: str) -> str | None:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
