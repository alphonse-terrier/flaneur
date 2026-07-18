"""Traffic info: disruptions (roadworks, incidents, delays), network-wide or per line."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from flaneur.models import Disruption
from flaneur.prim_client import prim_get

_TAG_RE = re.compile(r"<[^>]+>")


def _clean_text(text: str | None) -> str | None:
    """Strips HTML tags from rider-facing messages."""
    if not text:
        return None
    stripped = _TAG_RE.sub(" ", text)
    return " ".join(stripped.split()) or None


def _to_iso(navitia_dt: str | None) -> str | None:
    if not navitia_dt:
        return None
    try:
        return datetime.strptime(navitia_dt, "%Y%m%dT%H%M%S").isoformat()
    except ValueError:
        return navitia_dt


def parse_disruption(raw: dict[str, Any]) -> Disruption:
    """Normalizes a Navitia ``disruption`` object into a compact model."""
    severity = raw.get("severity") or {}
    periods = raw.get("application_periods") or []
    first_period = periods[0] if periods else {}

    messages = raw.get("messages") or []
    message = _clean_text(messages[0].get("text")) if messages else None

    impacted: list[str] = []
    for obj in raw.get("impacted_objects") or []:
        pt = obj.get("pt_object") or {}
        name = pt.get("name")
        if name and name not in impacted:
            impacted.append(name)

    return Disruption(
        id=raw.get("id") or raw.get("disruption_id"),
        cause=raw.get("cause"),
        effect=severity.get("effect"),
        severity=severity.get("name"),
        status=raw.get("status"),
        begin=_to_iso(first_period.get("begin")),
        end=_to_iso(first_period.get("end")),
        message=message,
        impacted_objects=impacted,
    )


def _extract_disruptions(payload: Any) -> list[Disruption]:
    """Extracts the list of disruptions from a response (varying formats)."""
    if not isinstance(payload, dict):
        return []
    # Navitia format: top-level "disruptions" list.
    raw_list = payload.get("disruptions")
    # disruptions_bulk format: sometimes nested under "disruptions" too.
    if not raw_list and isinstance(payload.get("data"), dict):
        raw_list = payload["data"].get("disruptions")
    return [parse_disruption(d) for d in (raw_list or [])]


async def global_disruptions() -> list[Disruption]:
    """All current and upcoming disruptions (disruptions_bulk endpoint)."""
    from flaneur.config import get_settings

    url = f"{get_settings().prim_marketplace_base}/disruptions_bulk"
    payload = await prim_get(url, source="PRIM disruptions_bulk")
    return _extract_disruptions(payload)


async def line_disruptions(line: str) -> list[Disruption]:
    """Disruptions for a given line (name/code or Navitia id) via line_reports.

    If ``line`` is a Navitia id (``line:IDFM:...``), the line is targeted
    directly. Otherwise the global report is filtered by label.
    """
    if line.startswith("line:"):
        # Targeted path; note: "line_reports" is duplicated in the path on PRIM.
        path = f"lines/{line}/line_reports/line_reports"
        payload = await prim_get(path, {"count": 100}, source="Navitia line_reports")
        return _extract_disruptions(payload)

    # Global report, then filter by impacted line label.
    payload = await prim_get(
        "line_reports/line_reports",
        {"count": 100},
        source="Navitia line_reports",
    )
    all_disruptions = _extract_disruptions(payload)
    needle = line.strip().lower()
    filtered = [
        d
        for d in all_disruptions
        if any(needle == obj.lower() or needle in obj.lower() for obj in d.impacted_objects)
    ]
    return filtered or all_disruptions
