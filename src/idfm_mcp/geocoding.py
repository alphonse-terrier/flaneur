"""Résolution d'adresses et de lieux en coordonnées.

Deux sources complémentaires :
- Le géocodeur national (Base Adresse Nationale via Géoplateforme, sans clé) pour
  les adresses postales — durable et précis.
- L'autocomplétion Navitia ``/places`` de PRIM pour les noms d'arrêts/gares.

``resolve_place`` tente d'abord le géocodeur BAN ; si aucun résultat probant, il
se rabat sur Navitia (utile pour un simple nom de station comme « Châtelet »).
"""

from __future__ import annotations

import re
from typing import Any

from idfm_mcp.config import get_settings
from idfm_mcp.models import GeoLocation
from idfm_mcp.prim_client import PrimError, prim_get, public_get

# Une entrée "lon;lat" déjà fournie par l'utilisateur (deux flottants séparés par ;).
_LONLAT_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*;\s*(-?\d+(?:\.\d+)?)\s*$")


def _parse_lonlat(query: str) -> GeoLocation | None:
    match = _LONLAT_RE.match(query)
    if not match:
        return None
    lon, lat = float(match.group(1)), float(match.group(2))
    return GeoLocation(label=f"{lon};{lat}", longitude=lon, latitude=lat, kind="coord")


async def _geocode_ban(query: str) -> GeoLocation | None:
    """Géocode une adresse via Géoplateforme, avec repli sur api-adresse.data.gouv.fr."""
    settings = get_settings()
    endpoints = [
        (f"{settings.geocoder_base}/search", "Géocodeur Géoplateforme"),
        (f"{settings.geocoder_fallback_base}/search", "Géocodeur BAN"),
    ]
    last_error: PrimError | None = None
    for url, source in endpoints:
        try:
            data = await public_get(url, {"q": query, "limit": 1}, source=source)
        except PrimError as exc:  # essaie l'endpoint suivant
            last_error = exc
            continue
        location = _parse_ban_feature(data)
        if location is not None:
            return location
    if last_error is not None:
        raise last_error
    return None


def _parse_ban_feature(data: Any) -> GeoLocation | None:
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
    """Autocomplétion Navitia ``/places`` (adresses, arrêts, POIs)."""
    # httpx sérialise une valeur de type liste en répétant le paramètre (type[]=a&type[]=b),
    # ce qu'attend Navitia.
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
    """Résout une entrée libre (adresse, nom d'arrêt, ou `lon;lat`) en coordonnées.

    Lève ``PrimError`` si rien n'est trouvé.
    """
    query = query.strip()
    if not query:
        raise PrimError("Lieu vide : fournissez une adresse, un nom d'arrêt ou des coordonnées.")

    direct = _parse_lonlat(query)
    if direct is not None:
        return direct

    if prefer_stops:
        navitia = await _geocode_navitia(query, types=["stop_area", "address"])
        if navitia is not None:
            return navitia

    ban = await _geocode_ban(query)
    if ban is not None:
        return ban

    # Dernier recours : autocomplétion Navitia (nom d'arrêt/POI sans adresse postale).
    navitia = await _geocode_navitia(query, types=["stop_area", "poi", "address"])
    if navitia is not None:
        return navitia

    raise PrimError(f"Aucun lieu trouvé pour « {query} ».")
