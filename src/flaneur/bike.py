"""Cycling route calculation via BRouter (free, no-key cycling router).

PRIM/Navitia only routes walking: cycling/car modes are ignored there. For a
real cycling travel time, we query BRouter (https://brouter.de), which
returns distance and estimated duration as GeoJSON.

BRouter's raw duration assumes near-uninterrupted road cycling (~19-21 km/h in
Paris testing) and only applies a token cost at signalized intersections
(~6.5 s on average) — nowhere near the real average wait at a traffic light
for a random arrival (roughly a quarter of the signal cycle, ~15-20 s for a
typical 60-90 s urban cycle). Left uncorrected, this systematically
underestimates travel time for dense urban routes, which defeats the purpose
of planning a journey to arrive on time. We therefore add a documented delay
per traffic-signal crossing actually present on the route (BRouter already
reports each crossing's tags in its ``messages`` table, at no extra cost).

The ``shortest`` profile is intentionally not exposed: it minimizes raw
distance regardless of way type and can route onto ``highway=footway`` paths,
where BRouter's time model assumes walking pace (observed: ~5 km/h) — a
misleading result for a tool that reports a cycling duration.
"""

from __future__ import annotations

from typing import Any

from flaneur.config import get_settings
from flaneur.geocoding import resolve_place
from flaneur.models import BikeRoute, GeoLocation
from flaneur.prim_client import PrimError, public_get

# Available BRouter profiles. trekking = balanced (default), fastbike =
# prioritizes speed. ("shortest" is excluded — see module docstring.)
_PROFILES = {"trekking", "fastbike"}

# Assumed average wait time for a random arrival at a signalized intersection,
# in seconds. Rule of thumb: roughly a quarter of the signal cycle length for
# a typical urban cycle of 60-90 s. Applied on top of BRouter's own (much
# smaller) intersection cost, which is more of a turn-penalty than a realistic
# traffic-light wait.
_TRAFFIC_SIGNAL_DELAY_S = 15
# Assumed wait at an unsignalized stop sign (rarer in France; give-way is more
# common), in seconds.
_STOP_SIGN_DELAY_S = 5


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
    signals, stops = _count_intersections(props)
    traffic_delay_s = signals * _TRAFFIC_SIGNAL_DELAY_S + stops * _STOP_SIGN_DELAY_S

    return BikeRoute(
        origin=origin_loc,
        destination=destination_loc,
        profile=profile,
        distance_km=round(length_m / 1000, 2),
        duration_minutes=round((time_s + traffic_delay_s) / 60),
    )


def _count_intersections(props: dict[str, Any]) -> tuple[int, int]:
    """Counts traffic-signal and stop-sign crossings from BRouter's message table.

    ``properties.messages`` is a table (header row + data rows) included by
    default in the GeoJSON response; each row's ``NodeTags`` column carries
    OSM tags for that waypoint, e.g. ``crossing=traffic_signals``.
    """
    messages = props.get("messages") or []
    if len(messages) < 2:
        return 0, 0
    header = messages[0]
    try:
        tag_idx = header.index("NodeTags")
    except ValueError:
        return 0, 0

    signals = stops = 0
    for row in messages[1:]:
        if tag_idx >= len(row):
            continue
        tags = row[tag_idx] or ""
        if "traffic_signals" in tags:
            signals += 1
        elif "highway=stop" in tags:
            stops += 1
    return signals, stops


def _to_int(value: Any) -> int:
    """BRouter returns its metrics as strings (e.g. "11463")."""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0
