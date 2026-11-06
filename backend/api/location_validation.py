"""Validate the location contract once for individual and staff handlers."""

import math
from .auth import AuthError
from pipeline.location import SEARCH_RADII, in_service_area, location_from_dict


def _text(data, key, limit, required=False):
    value = data.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise AuthError(400, f"location.{key} must be {'a non-empty' if required else 'a'} string of at most {limit} characters.")
    return value.strip() or None


def parse_location(value):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise AuthError(400, "location must be an object.")
    data = {
        "name": _text(value, "name", 200, required=True),
        "address": _text(value, "address", 500),
        "note": _text(value, "note", 500),
        "providerPlaceId": _text(value, "providerPlaceId", 200),
    }
    for key in ("latitude", "longitude"):
        coordinate = value.get(key)
        if isinstance(coordinate, bool) or not isinstance(coordinate, (int, float)) or not math.isfinite(coordinate):
            raise AuthError(400, f"location.{key} must be a finite number.")
        data[key] = float(coordinate)
    if not in_service_area(data["latitude"], data["longitude"]):
        raise AuthError(400, "Choose a location within the Singapore service area.")
    data["provider"] = value.get("provider", "manual")
    data["selectionMethod"] = value.get("selectionMethod", "map")
    if data["provider"] not in ("onemap", "manual") or data["selectionMethod"] not in ("search", "map"):
        raise AuthError(400, "Invalid location provider or selection method.")
    return location_from_dict(data)


def parse_radius(value, location):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value not in SEARCH_RADII:
        raise AuthError(400, "searchRadiusMetres must be 500, 1000, 2000, 5000 or null.")
    if location is None:
        raise AuthError(400, "A confirmed location is required for a distance limit.")
    return value
