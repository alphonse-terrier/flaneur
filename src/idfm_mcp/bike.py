"""Calcul d'itinéraire à vélo via BRouter (routeur cyclable gratuit, sans clé).

PRIM/Navitia ne route que la marche : les modes vélo/voiture y sont ignorés. Pour
un vrai temps de trajet à vélo, on interroge BRouter (https://brouter.de), qui
renvoie distance et durée estimée en GeoJSON.
"""

from __future__ import annotations

from typing import Any

from idfm_mcp.config import get_settings
from idfm_mcp.geocoding import resolve_place
from idfm_mcp.models import BikeRoute, GeoLocation
from idfm_mcp.prim_client import PrimError, public_get

# Profils BRouter proposés (adaptés au vélo). trekking = équilibré (défaut),
# fastbike = privilégie la vitesse, shortest = plus court.
_PROFILES = {"trekking", "fastbike", "shortest"}


async def bike_route(
    origin: str, destination: str, profile: str = "trekking"
) -> BikeRoute:
    """Calcule un itinéraire à vélo entre deux lieux (durée et distance)."""
    prof = (profile or "trekking").strip().lower()
    if prof not in _PROFILES:
        raise PrimError(
            f"Profil vélo inconnu : « {profile} ». Valeurs acceptées : "
            f"{', '.join(sorted(_PROFILES))}."
        )

    origin_loc = await resolve_place(origin)
    destination_loc = await resolve_place(destination)

    # BRouter attend lonlats=lon,lat|lon,lat.
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
            "BRouter n'a pas retourné d'itinéraire vélo (points hors zone couverte ?)."
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
    """BRouter renvoie ses métriques sous forme de chaînes (« 11463 »)."""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0
