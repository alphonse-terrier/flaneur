"""Resolving addresses and places into coordinates.

Two complementary sources:
- The national geocoder (French national address database via Géoplateforme,
  no key) for postal addresses — durable and precise.
- PRIM's Navitia ``/places`` autocomplete for stop/station names.

``resolve_place`` tries the national geocoder first; if there's no solid
match, it falls back to Navitia (useful for a bare station name like
"Châtelet").
"""

from __future__ import annotations

import re
from typing import Any

from flaneur.config import get_settings
from flaneur.models import GeoLocation
from flaneur.prim_client import PrimError, prim_get, public_get

# A "lon;lat" entry already supplied by the user (two floats separated by ;).
_LONLAT_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*;\s*(-?\d+(?:\.\d+)?)\s*$")


def _parse_lonlat(query: str) -> GeoLocation | None:
    match = _LONLAT_RE.match(query)
    if not match:
        return None
    lon, lat = float(match.group(1)), float(match.group(2))
    return GeoLocation(label=f"{lon};{lat}", longitude=lon, latitude=lat, kind="coord")


async def _geocode_national(query: str) -> GeoLocation | None:
    """Geocodes an address via Géoplateforme, falling back to api-adresse.data.gouv.fr."""
    settings = get_settings()
    endpoints = [
        (f"{settings.geocoder_base}/search", "Géoplateforme geocoder"),
        (f"{settings.geocoder_fallback_base}/search", "National address geocoder"),
    ]
    last_error: PrimError | None = None
    for url, source in endpoints:
        try:
            data = await public_get(url, {"q": query, "limit": 1}, source=source)
        except PrimError as exc:  # try the next endpoint
            last_error = exc
            continue
        location = _parse_geocoder_feature(data)
        if location is not None:
            return location
    if last_error is not None:
        raise last_error
    return None


def _parse_geocoder_feature(data: Any) -> GeoLocation | None:
    features = (data or {}).get("features") or []
    if not features:
        return None
    feature = features[0]
    coords = (feature.get("geometry") or {}).get("coordinates") or []
    if len(coords) < 2:
        return None
    props = feature.get("properties") or {}
    lon, lat = float(coords[0]), float(coords[1])
    return GeoLocation(
        label=props.get("label") or f"{lon};{lat}",
        longitude=lon,
        latitude=lat,
        city=props.get("city"),
        postcode=props.get("postcode"),
        kind=props.get("type"),
    )


async def _geocode_navitia(query: str, *, types: list[str]) -> GeoLocation | None:
    """Navitia ``/places`` autocomplete (addresses, stops, POIs)."""
    # httpx serializes a list value by repeating the parameter (type[]=a&type[]=b),
    # which is what Navitia expects.
    data = await prim_get(
        "places",
        {"q": query, "type[]": types},
        source="Navitia /places",
    )
    places = (data or {}).get("places") or []
    if not places:
        return None
    return _parse_navitia_place(places[0])


def _parse_navitia_place(place: dict[str, Any]) -> GeoLocation | None:
    embedded_type = place.get("embedded_type")
    embedded = place.get(embedded_type) if embedded_type else None
    coord = (embedded or {}).get("coord") or {}
    lon, lat = coord.get("lon"), coord.get("lat")
    if lon is None or lat is None:
        return None
    return GeoLocation(
        label=place.get("name") or place.get("id") or f"{lon};{lat}",
        longitude=float(lon),
        latitude=float(lat),
        kind=embedded_type,
    )


async def resolve_place(query: str, *, prefer_stops: bool = False) -> GeoLocation:
    """Resolves a free-form entry (address, stop name, or `lon;lat`) into coordinates.

    Raises ``PrimError`` if nothing is found.
    """
    query = query.strip()
    if not query:
        raise PrimError("Empty location: provide an address, a stop name, or coordinates.")

    direct = _parse_lonlat(query)
    if direct is not None:
        return direct

    if prefer_stops:
        navitia = await _geocode_navitia(query, types=["stop_area", "address"])
        if navitia is not None:
            return navitia

    national = await _geocode_national(query)
    if national is not None:
        return national

    # Last resort: Navitia autocomplete (stop/POI name without a postal address).
    navitia = await _geocode_navitia(query, types=["stop_area", "poi", "address"])
    if navitia is not None:
        return navitia

    raise PrimError(f'No location found for "{query}".')
