"""Location serialization and geographic math shared by API and matching stages."""

from __future__ import annotations

import math
from .models import Item, ItemLocation, ItemType

# Service envelope, including offshore islands. This is not a national boundary polygon.
SG_BOUNDS = (1.13, 103.50, 1.57, 104.12)  # south, west, north, east
SEARCH_RADII = {500, 1000, 2000, 5000}


def in_service_area(latitude: float, longitude: float) -> bool:
    south, west, north, east = SG_BOUNDS
    return south <= latitude <= north and west <= longitude <= east


def location_to_dict(location: ItemLocation | None) -> dict | None:
    if location is None:
        return None
    return {
        "name": location.name,
        "latitude": location.latitude,
        "longitude": location.longitude,
        "address": location.address,
        "provider": location.provider,
        "selectionMethod": location.selection_method,
        "providerPlaceId": location.provider_place_id,
        "note": location.note,
    }


def location_from_dict(data: dict | None) -> ItemLocation | None:
    if data is None:
        return None
    return ItemLocation(
        name=data["name"], latitude=float(data["latitude"]),
        longitude=float(data["longitude"]), address=data.get("address"),
        provider=data.get("provider", "manual"),
        selection_method=data.get("selectionMethod", "map"),
        provider_place_id=data.get("providerPlaceId"), note=data.get("note"),
    )


def distance_metres(a: ItemLocation, b: ItemLocation) -> float:
    """Haversine great-circle distance; clamp rounding at antipodal points."""
    lat_a, lat_b = math.radians(a.latitude), math.radians(b.latitude)
    dlat = lat_b - lat_a
    dlon = math.radians(b.longitude - a.longitude)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat_a) * math.cos(lat_b) * math.sin(dlon / 2) ** 2
    return 2 * 6_371_008.8 * math.asin(math.sqrt(max(0.0, min(1.0, h))))


def within_search_radius(a: Item, b: Item) -> bool:
    """Apply the LOST side's optional radius in either job orientation."""
    lost = a if a.item_type is ItemType.LOST else b
    if lost.search_radius_metres is None:
        return True
    if not a.location or not b.location:
        return False
    return distance_metres(a.location, b.location) <= lost.search_radius_metres
