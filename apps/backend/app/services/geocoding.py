"""
app/services/geocoding.py — Location name to coordinates using Nominatim.

Cache strategy: a process-wide in-memory dict, keyed by the normalised
location name. On miss we call the Nominatim API and cache the result for
the lifetime of the process (city coordinates don't change).

Rate limit: Nominatim allows 1 req/sec. We cache aggressively so
in practice we'll only call Nominatim for unique location names.
"""

import logging
import time
from dataclasses import dataclass

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
    # Ordered south, west, north, east. Nominatim emits south, north, west, east.
    bounds: tuple[float, float, float, float] | None = None


# Process-wide in-memory cache; lives for the lifetime of the process.
_memory_cache: dict[str, GeocodeResult] = {}


class GeocodingService:
    """
    Converts location names to (latitude, longitude) coordinates.

    In-memory dict cache first; Nominatim API only on cache miss.
    """

    def __init__(self) -> None:
        self._geolocator = Nominatim(
            user_agent=settings.NOMINATIM_USER_AGENT,
            timeout=10,
        )

    def geocode(self, location_name: str) -> tuple[float, float] | None:
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

        # In-memory cache
        if key in _memory_cache:
            logger.debug("[geocoding] Memory cache hit: %r", location_name)
            return _memory_cache[key]

        # Cache miss: call Nominatim
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
                    bounds=_normalise_bounding_box(
                        (location.raw or {}).get("boundingbox")
                    ),
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


def _normalise_bounding_box(value: object) -> tuple[float, float, float, float] | None:
    """Convert Nominatim's south/north/west/east box to south/west/north/east."""
    if not isinstance(value, list | tuple) or len(value) != 4:
        return None
    try:
        south, north, west, east = (float(item) for item in value)
    except (TypeError, ValueError):
        return None
    if south > north or west > east:
        return None
    return south, west, north, east
