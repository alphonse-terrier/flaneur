"""Calcul d'itinéraires (Navitia ``/journeys``) et résumé enrichi des perturbations."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from idfm_mcp.disruptions import parse_disruption
from idfm_mcp.geocoding import resolve_place
from idfm_mcp.models import Disruption, GeoLocation, Journey, JourneyResult, JourneySection
from idfm_mcp.prim_client import PrimError, prim_get

# Libellés lisibles pour les types de section Navitia.
_MODE_LABELS = {
    "public_transport": "Transport",
    "street_network": "Marche",
    "transfer": "Correspondance",
    "waiting": "Attente",
    "crow_fly": "Trajet direct",
    "on_demand_transport": "Transport à la demande",
}


def _to_iso(navitia_dt: str | None) -> str | None:
    """Convertit un datetime Navitia (YYYYMMDDTHHMMSS) en ISO 8601."""
    if not navitia_dt:
        return None
    try:
        return datetime.strptime(navitia_dt, "%Y%m%dT%H%M%S").isoformat()
    except ValueError:
        return navitia_dt


def _from_iso_to_navitia(value: str) -> str:
    """Convertit une entrée utilisateur ISO 8601 en datetime Navitia."""
    try:
        return datetime.fromisoformat(value).strftime("%Y%m%dT%H%M%S")
    except ValueError as exc:
        raise PrimError(
            f"Date/heure invalide : « {value} ». Utilisez le format ISO 8601 "
            "(ex. 2026-07-18T08:30:00)."
        ) from exc


def _index_disruptions(payload: dict[str, Any]) -> dict[str, Disruption]:
    """Indexe les perturbations de premier niveau par id, pour rattachement aux sections."""
    result: dict[str, Disruption] = {}
    for raw in payload.get("disruptions") or []:
        disruption = parse_disruption(raw)
        if disruption.id:
            result[disruption.id] = disruption
    return result


def _section_disruptions(
    section: dict[str, Any], index: dict[str, Disruption]
) -> list[Disruption]:
    infos = section.get("display_informations") or {}
    found: list[Disruption] = []
    seen: set[str] = set()
    for link in infos.get("links") or []:
        if link.get("type") == "disruption":
            did = link.get("id")
            if did and did in index and did not in seen:
                seen.add(did)
                found.append(index[did])
    return found


def _summarize_section(
    section: dict[str, Any], index: dict[str, Disruption]
) -> JourneySection:
    section_type = section.get("type", "")
    infos = section.get("display_informations") or {}
    line = infos.get("label") or infos.get("code") or infos.get("line")
    network = infos.get("network")
    direction = infos.get("direction")
    from_name = (section.get("from") or {}).get("name")
    to_name = (section.get("to") or {}).get("name")
    duration_min = round((section.get("duration") or 0) / 60)

    mode_label = _MODE_LABELS.get(section_type, section_type or "Étape")
    if section_type == "public_transport" and line:
        commercial = infos.get("commercial_mode") or "Ligne"
        label = f"{commercial} {line}"
        if direction:
            label += f" → {direction}"
    elif section_type == "street_network":
        walk_mode = section.get("mode", "walking")
        label = f"{mode_label} ({walk_mode}, {duration_min} min)"
    else:
        label = mode_label
        if from_name and to_name:
            label += f" : {from_name} → {to_name}"

    return JourneySection(
        mode=section_type or "unknown",
        label=label,
        line=str(line) if line is not None else None,
        network=network,
        direction=direction,
        from_name=from_name,
        to_name=to_name,
        departure=_to_iso(section.get("departure_date_time")),
        arrival=_to_iso(section.get("arrival_date_time")),
        duration_minutes=duration_min,
        disruptions=_section_disruptions(section, index),
    )


def _summarize_journey(journey: dict[str, Any], index: dict[str, Disruption]) -> Journey:
    sections = [_summarize_section(s, index) for s in journey.get("sections") or []]
    walking = sum(
        s.duration_minutes for s in sections if s.mode == "street_network"
    )
    has_disruptions = any(s.disruptions for s in sections)
    return Journey(
        type=journey.get("type"),
        status=journey.get("status"),
        departure=_to_iso(journey.get("departure_date_time")),
        arrival=_to_iso(journey.get("arrival_date_time")),
        duration_minutes=round((journey.get("duration") or 0) / 60),
        nb_transfers=journey.get("nb_transfers") or 0,
        walking_minutes=walking,
        sections=sections,
        has_disruptions=has_disruptions,
    )


async def plan_journey(
    origin: str,
    destination: str,
    when: str | None = None,
    arrive_by: bool = False,
    max_journeys: int = 3,
) -> JourneyResult:
    """Calcule des itinéraires entre deux lieux, avec perturbations temps réel.

    ``origin`` / ``destination`` : adresse, nom d'arrêt, ou coordonnées ``lon;lat``.
    ``when`` : date/heure ISO 8601 (défaut = maintenant).
    ``arrive_by`` : si True, ``when`` est l'heure d'arrivée souhaitée.
    """
    origin_loc = await resolve_place(origin)
    destination_loc = await resolve_place(destination)

    params: dict[str, Any] = {
        "from": origin_loc.lonlat,
        "to": destination_loc.lonlat,
        "datetime_represents": "arrival" if arrive_by else "departure",
        "data_freshness": "realtime",
        "count": max(1, min(max_journeys, 5)),
    }
    if when:
        params["datetime"] = _from_iso_to_navitia(when)

    payload = await prim_get("journeys", params, source="Navitia /journeys")

    index = _index_disruptions(payload)
    journeys = [_summarize_journey(j, index) for j in payload.get("journeys") or []]

    note = None
    if not journeys:
        note = (
            "Aucun itinéraire trouvé. Vérifiez que le départ et l'arrivée sont bien "
            "en Île-de-France et desservis par les transports en commun."
        )

    return JourneyResult(
        origin=origin_loc,
        destination=destination_loc,
        journeys=journeys,
        note=note,
    )
