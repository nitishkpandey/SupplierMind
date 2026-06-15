"""geocode_location tool — wraps GeocodingService for the ReAct Parser."""

from __future__ import annotations

from typing import Any

from app.agents.tools.registry import Tool
from app.services.geocoding import GeocodingService

_DESCRIPTION = (
    "Convert a location name (city, region, or country) to latitude/longitude "
    "plus a normalised country and city. Use this when the query mentions a "
    "specific place that the downstream geospatial filter will need to score."
)

_ARGS_SCHEMA = {
    "type": "object",
    "properties": {
        "location_name": {
            "type": "string",
            "description": "Free-form location, e.g. 'Bremen', 'Bavaria, Germany', 'Germany'."
        }
    },
    "required": ["location_name"],
}


def _run(location_name: str, *, _geocoder: GeocodingService | None = None) -> dict[str, Any]:
    name = (location_name or "").strip()
    if not name:
        return {"found": False, "reason": "empty location_name"}

    geocoder = _geocoder or GeocodingService()
    coords = geocoder.geocode(name)
    if not coords:
        return {"found": False, "reason": f"no geocode result for {name!r}"}

    lat, lng = coords
    # Best-effort split on a single comma to surface city + country to the LLM.
    city: str | None = None
    country: str | None = None
    if "," in name:
        parts = [p.strip() for p in name.split(",", 1)]
        if len(parts) == 2:
            city, country = parts[0] or None, parts[1] or None
    if city is None and country is None:
        country = name
    return {"found": True, "lat": lat, "lng": lng, "city": city, "country": country}


def geocode_location_tool(*, _geocoder: GeocodingService | None = None) -> Tool:
    """Build the geocode_location Tool.

    The optional _geocoder kwarg exists so tests can inject a fake. Production
    code calls the no-arg form, which lazily constructs a real GeocodingService.
    """
    def _fn(location_name: str) -> dict[str, Any]:
        return _run(location_name, _geocoder=_geocoder)

    return Tool(
        name="geocode_location",
        description=_DESCRIPTION,
        args_schema=_ARGS_SCHEMA,
        fn=_fn,
    )
