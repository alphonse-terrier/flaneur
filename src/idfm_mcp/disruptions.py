"""Info trafic : perturbations (travaux, incidents, retards) globales ou par ligne."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from idfm_mcp.models import Disruption
from idfm_mcp.prim_client import prim_get

_TAG_RE = re.compile(r"<[^>]+>")


def _clean_text(text: str | None) -> str | None:
    """Retire les balises HTML des messages voyageurs."""
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
    """Normalise un objet ``disruption`` Navitia en modèle compact."""
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
    """Extrait la liste de perturbations d'une réponse (formats variés)."""
    if not isinstance(payload, dict):
        return []
    # Format Navitia : liste de premier niveau "disruptions".
    raw_list = payload.get("disruptions")
    # Format disruptions_bulk : parfois imbriqué sous "disruptions" également.
    if not raw_list and isinstance(payload.get("data"), dict):
        raw_list = payload["data"].get("disruptions")
    return [parse_disruption(d) for d in (raw_list or [])]


async def global_disruptions() -> list[Disruption]:
    """Toutes les perturbations en cours et à venir (endpoint disruptions_bulk)."""
    from idfm_mcp.config import get_settings

    url = f"{get_settings().prim_marketplace_base}/disruptions_bulk"
    payload = await prim_get(url, source="PRIM disruptions_bulk")
    return _extract_disruptions(payload)


async def line_disruptions(line: str) -> list[Disruption]:
    """Perturbations d'une ligne donnée (nom/code ou id Navitia) via line_reports.

    Si ``line`` est un id Navitia (``line:IDFM:...``), on cible directement la ligne.
    Sinon on filtre le rapport global sur le libellé.
    """
    if line.startswith("line:"):
        # Chemin ciblé ; note : "line_reports" est dupliqué dans le chemin sur PRIM.
        path = f"lines/{line}/line_reports/line_reports"
        payload = await prim_get(path, {"count": 100}, source="Navitia line_reports")
        return _extract_disruptions(payload)

    # Rapport global puis filtrage sur le libellé de ligne impactée.
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
