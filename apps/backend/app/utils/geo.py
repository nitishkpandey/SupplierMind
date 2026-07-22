"""Shared geographic helpers."""

import math

EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """
    Distance in km between two lat/lng coordinates.

    Formula:
    a = sin²(Δlat/2) + cos(lat1) × cos(lat2) × sin²(Δlng/2)
    distance = 2R × arcsin(√a)   where R = 6371km (Earth radius)
    """
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlng / 2) ** 2
    )
    return EARTH_RADIUS_KM * 2 * math.asin(math.sqrt(a))
