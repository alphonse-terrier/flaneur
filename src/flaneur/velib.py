"""Real-time Vélib' Métropole availability via the public GBFS feed (no key).

Given a location, returns the nearest Vélib' stations with live counts of
available bikes (mechanical vs electric) and free docks — the natural companion
to ``bike_route`` ("find a bike near me, then ride"). PRIM doesn't expose this,
so we read the open Vélib' Métropole GBFS feed directly.
"""

from __future__ import annotations

from math import asin, cos, radians, sin, sqrt
from typing import Any

from flaneur.config import get_settings
from flaneur.geocoding import resolve_place
from flaneur.models import GeoLocation, VelibResult, VelibStation
from flaneur.prim_client import public_get


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    """Great-circle distance in meters."""
    r = 6_371_000
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    h = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return int(r * 2 * asin(sqrt(h)))


def _bike_type_counts(entry: dict[str, Any]) -> tuple[int | None, int | None]:
    """Parse num_bikes_available_types = [{'mechanical': n}, {'ebike': m}]."""
    types = entry.get("num_bikes_available_types")
    if not isinstance(types, list):
        return None, None
    counts: dict[str, int] = {}
    for item in types:
        if isinstance(item, dict):
            counts.update({k: v for k, v in item.items() if isinstance(v, int)})
    mechanical = counts.get("mechanical")
    electric = counts.get("ebike", counts.get("electric"))
    return mechanical, electric


async def velib_nearby(location: str, limit: int = 5) -> VelibResult:
    """Returns the nearest Vélib' stations with real-time availability."""
    loc = await resolve_place(location)
    base = get_settings().velib_base

    info = await public_get(f"{base}/station_information.json", source="Vélib' GBFS")
    status = await public_get(f"{base}/station_status.json", source="Vélib' GBFS")

    info_stations = (info or {}).get("data", {}).get("stations", []) or []
    status_by_id = {
        s.get("station_id"): s for s in (status or {}).get("data", {}).get("stations", []) or []
    }

    stations = _nearest_stations(loc, info_stations, status_by_id, limit)
    note = None if stations else "No Vélib' station found near this location."
    return VelibResult(location=loc, stations=stations, note=note)


def _nearest_stations(
    loc: GeoLocation,
    info_stations: list[dict[str, Any]],
    status_by_id: dict[Any, dict[str, Any]],
    limit: int,
) -> list[VelibStation]:
    scored: list[tuple[int, VelibStation]] = []
    for info in info_stations:
        lat, lon = info.get("lat"), info.get("lon")
        if lat is None or lon is None:
            continue
        dist = _haversine_m(loc.latitude, loc.longitude, lat, lon)
        st = status_by_id.get(info.get("station_id")) or {}
        mechanical, electric = _bike_type_counts(st)
        scored.append(
            (
                dist,
                VelibStation(
                    name=info.get("name") or "Vélib' station",
                    station_code=info.get("stationCode"),
                    distance_m=dist,
                    bikes_available=st.get("numBikesAvailable")
                    or st.get("num_bikes_available")
                    or 0,
                    mechanical_bikes=mechanical,
                    electric_bikes=electric,
                    docks_available=st.get("numDocksAvailable")
                    or st.get("num_docks_available")
                    or 0,
                    capacity=info.get("capacity"),
                ),
            )
        )
    scored.sort(key=lambda pair: pair[0])
    return [station for _, station in scored[: max(1, limit)]]
