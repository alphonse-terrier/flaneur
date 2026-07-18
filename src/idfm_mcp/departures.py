"""Prochains passages temps réel via SIRI Lite ``stop-monitoring`` de PRIM."""

from __future__ import annotations

from typing import Any

from idfm_mcp.config import get_settings
from idfm_mcp.models import Departure, DeparturesResult
from idfm_mcp.prim_client import PrimError, prim_get


async def _resolve_stop(stop: str) -> tuple[str, str]:
    """Résout un nom d'arrêt en (MonitoringRef SIRI, libellé).

    Accepte directement un id (``STIF:StopArea:SP:...`` ou ``stop_area:IDFM:...``),
    sinon interroge Navitia ``/places`` pour trouver la zone d'arrêt.
    """
    stop = stop.strip()
    if stop.startswith("STIF:StopArea:SP:"):
        return stop, stop

    location = await _resolve_stop_via_navitia(stop)
    return location


async def _resolve_stop_via_navitia(stop: str) -> tuple[str, str]:
    data = await prim_get(
        "places",
        {"q": stop, "type[]": ["stop_area"]},
        source="Navitia /places",
    )
    places = (data or {}).get("places") or []
    if not places:
        raise PrimError(f"Aucun arrêt trouvé pour « {stop} ».")
    place = places[0]
    stop_area = place.get("stop_area") or {}
    navitia_id = stop_area.get("id") or place.get("id") or ""
    label = place.get("name") or stop
    monitoring_ref = _navitia_id_to_monitoring_ref(navitia_id)
    if not monitoring_ref:
        raise PrimError(
            f"Impossible de convertir l'arrêt « {label} » en référence SIRI "
            "(MonitoringRef)."
        )
    return monitoring_ref, label


def _navitia_id_to_monitoring_ref(navitia_id: str) -> str | None:
    """Convertit un id Navitia (stop_area:IDFM:<n>) en MonitoringRef SIRI.

    Ex. ``stop_area:IDFM:71517`` → ``STIF:StopArea:SP:71517:``.
    """
    if not navitia_id:
        return None
    if navitia_id.startswith("STIF:StopArea:SP:"):
        return navitia_id
    parts = navitia_id.split(":")
    numeric = parts[-1]
    if numeric.isdigit():
        return f"STIF:StopArea:SP:{numeric}:"
    return None


def _parse_visits(payload: Any) -> list[Departure]:
    """Extrait les MonitoredStopVisit d'une réponse SIRI Lite stop-monitoring."""
    departures: list[Departure] = []
    try:
        delivery = (
            payload["Siri"]["ServiceDelivery"]["StopMonitoringDelivery"]
        )
    except (KeyError, TypeError):
        return departures

    if isinstance(delivery, list):
        deliveries = delivery
    else:
        deliveries = [delivery]

    for d in deliveries:
        for visit in d.get("MonitoredStopVisit") or []:
            journey = visit.get("MonitoredVehicleJourney") or {}
            call = journey.get("MonitoredCall") or {}
            line = journey.get("LineRef", {})
            line_val = line.get("value") if isinstance(line, dict) else line
            destination = _siri_text(journey.get("DestinationName"))
            departures.append(
                Departure(
                    line=_short_line(line_val),
                    destination=destination,
                    expected=call.get("ExpectedDepartureTime")
                    or call.get("ExpectedArrivalTime"),
                    aimed=call.get("AimedDepartureTime") or call.get("AimedArrivalTime"),
                    status=call.get("DepartureStatus") or call.get("ArrivalStatus"),
                )
            )
    return departures


def _siri_text(value: Any) -> str | None:
    """SIRI encode souvent les libellés en [{'value': '...'}]."""
    if isinstance(value, list) and value:
        first = value[0]
        return first.get("value") if isinstance(first, dict) else str(first)
    if isinstance(value, dict):
        return value.get("value")
    if isinstance(value, str):
        return value
    return None


def _short_line(line_ref: Any) -> str | None:
    """Extrait un identifiant de ligne lisible d'un LineRef SIRI."""
    if not isinstance(line_ref, str):
        return None
    # Ex. STIF:Line::C01371: → C01371
    parts = [p for p in line_ref.split(":") if p]
    return parts[-1] if parts else line_ref


async def next_departures(stop: str, limit: int = 10) -> DeparturesResult:
    """Retourne les prochains passages temps réel à un arrêt."""
    monitoring_ref, label = await _resolve_stop(stop)

    url = f"{get_settings().prim_marketplace_base}/stop-monitoring"
    payload = await prim_get(
        url,
        {"MonitoringRef": monitoring_ref},
        source="SIRI stop-monitoring",
    )
    departures = _parse_visits(payload)[: max(1, limit)]

    note = None
    if not departures:
        note = "Aucun passage temps réel disponible pour cet arrêt actuellement."

    return DeparturesResult(
        stop_label=label,
        stop_id=monitoring_ref,
        departures=departures,
        note=note,
    )
