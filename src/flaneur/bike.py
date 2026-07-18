"""Cycling route calculation via BRouter (free, no-key cycling router).

PRIM/Navitia only routes walking: cycling/car modes are ignored there. For a
real cycling travel time, we query BRouter (https://brouter.de), which
returns distance and estimated duration as GeoJSON.
"""

from __future__ import annotations

from typing import Any

from flaneur.config import get_settings
from flaneur.geocoding import resolve_place
from flaneur.models import BikeRoute, GeoLocation
from flaneur.prim_client import PrimError, public_get

# Available BRouter profiles. trekking = balanced (default), fastbike =
# prioritizes speed, shortest = shortest distance.
_PROFILES = {"trekking", "fastbike", "shortest"}


async def bike_route(
    origin: str, destination: str, profile: str = "trekking"
) -> BikeRoute:
    """Computes a cycling route between two places (duration and distance)."""
    prof = (profile or "trekking").strip().lower()
    if prof not in _PROFILES:
        raise PrimError(
            f"Unknown cycling profile: \"{profile}\". Accepted values: "
            f"{', '.join(sorted(_PROFILES))}."
        )

    origin_loc = await resolve_place(origin)
    destination_loc = await resolve_place(destination)

    # BRouter expects lonlats=lon,lat|lon,lat.
    lonlats = (
        f"{origin_loc.longitude},{origin_loc.latitude}"
        f"|{destination_loc.longitude},{destination_loc.latitude}"
    )
    data = await public_get(
        get_settings().brouter_base,
        {"lonlats": lonlats, "profile": prof, "alternativeidx": 0, "format": "geojson"},
        source="BRouter",
    )
    return _parse_brouter(data, origin_loc, destination_loc, prof)


def _parse_brouter(
    data: Any,
    origin_loc: GeoLocation,
    destination_loc: GeoLocation,
    profile: str,
) -> BikeRoute:
    features = (data or {}).get("features") or []
    if not features:
        raise PrimError(
            "BRouter did not return a cycling route (points outside covered area?)."
        )
    props = features[0].get("properties") or {}
    length_m = _to_int(props.get("track-length"))
    time_s = _to_int(props.get("total-time"))
    return BikeRoute(
        origin=origin_loc,
        destination=destination_loc,
        profile=profile,
        distance_km=round(length_m / 1000, 2),
        duration_minutes=round(time_s / 60),
    )


def _to_int(value: Any) -> int:
    """BRouter returns its metrics as strings (e.g. "11463")."""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0
