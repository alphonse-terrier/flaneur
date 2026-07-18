"""Real-time next departures via PRIM's SIRI Lite ``stop-monitoring``."""

from __future__ import annotations

from typing import Any

from flaneur.config import get_settings
from flaneur.models import Departure, DeparturesResult
from flaneur.prim_client import PrimError, prim_get


async def _resolve_stop(stop: str) -> tuple[str, str]:
    """Resolves a stop name into (SIRI MonitoringRef, label).

    Accepts an id directly (``STIF:StopArea:SP:...`` or ``stop_area:IDFM:...``),
    otherwise queries Navitia ``/places`` to find the stop area.
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
        raise PrimError(f"No stop found for \"{stop}\".")
    place = places[0]
    stop_area = place.get("stop_area") or {}
    navitia_id = stop_area.get("id") or place.get("id") or ""
    label = place.get("name") or stop
    monitoring_ref = _navitia_id_to_monitoring_ref(navitia_id)
    if not monitoring_ref:
        raise PrimError(
            f"Could not convert the stop \"{label}\" into a SIRI reference "
            "(MonitoringRef)."
        )
    return monitoring_ref, label


def _navitia_id_to_monitoring_ref(navitia_id: str) -> str | None:
    """Converts a Navitia id (stop_area:IDFM:<n>) into a SIRI MonitoringRef.

    E.g. ``stop_area:IDFM:71517`` → ``STIF:StopArea:SP:71517:``.
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
    """Extracts the MonitoredStopVisit entries from a SIRI Lite stop-monitoring response."""
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
    """SIRI often encodes labels as [{'value': '...'}]."""
    if isinstance(value, list) and value:
        first = value[0]
        return first.get("value") if isinstance(first, dict) else str(first)
    if isinstance(value, dict):
        return value.get("value")
    if isinstance(value, str):
        return value
    return None


def _short_line(line_ref: Any) -> str | None:
    """Extracts a human-readable line identifier from a SIRI LineRef."""
    if not isinstance(line_ref, str):
        return None
    # E.g. STIF:Line::C01371: → C01371
    parts = [p for p in line_ref.split(":") if p]
    return parts[-1] if parts else line_ref


async def next_departures(stop: str, limit: int = 10) -> DeparturesResult:
    """Returns the next real-time departures at a stop."""
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
        note = "No real-time departure currently available for this stop."

    return DeparturesResult(
        stop_label=label,
        stop_id=monitoring_ref,
        departures=departures,
        note=note,
    )
