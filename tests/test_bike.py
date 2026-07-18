"""Tests for the cycling route (BRouter parsing, no network calls)."""

import pytest

from flaneur.bike import _count_intersections, _parse_brouter, bike_route
from flaneur.models import GeoLocation
from flaneur.prim_client import PrimError

A = GeoLocation(label="Bastille", longitude=2.3692, latitude=48.8531)
B = GeoLocation(label="La Défense", longitude=2.2377, latitude=48.8918)

# Typical BRouter response (GeoJSON): metrics as strings, no message table.
SAMPLE = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {"track-length": "11463", "total-time": "2181"},
            "geometry": {"type": "LineString", "coordinates": []},
        }
    ],
}

# Message table header, as returned by BRouter (real column order/names).
_HEADER = [
    "Longitude",
    "Latitude",
    "Elevation",
    "Distance",
    "CostPerKm",
    "ElevCost",
    "TurnCost",
    "NodeCost",
    "InitialCost",
    "WayTags",
    "NodeTags",
    "Time",
    "Energy",
]


def _row(node_tags: str = "") -> list[str]:
    return ["0", "0", "0", "0", "0", "0", "0", "0", "0", "", node_tags, "0", "0"]


def test_parse_brouter_without_signals():
    """No message table: no traffic-light correction, raw BRouter time is used."""
    route = _parse_brouter(SAMPLE, A, B, "trekking")
    assert route.distance_km == 11.46  # 11463 m
    assert route.duration_minutes == 36  # 2181 s ≈ 36 min, unchanged
    assert route.profile == "trekking"
    assert route.origin.label == "Bastille"
    assert route.destination.label == "La Défense"


def test_parse_brouter_applies_traffic_signal_delay():
    """Each traffic-signal crossing adds a realistic wait, not just BRouter's tiny cost."""
    data = {
        "features": [
            {
                "properties": {
                    "track-length": "1000",
                    "total-time": "180",  # 3 min raw
                    "messages": [
                        _HEADER,
                        _row(),
                        _row("highway=crossing crossing=traffic_signals"),
                        _row("highway=crossing crossing=traffic_signals"),
                        _row("highway=stop"),
                    ],
                }
            }
        ]
    }
    route = _parse_brouter(data, A, B, "trekking")
    # 180s + 2*15s (signals) + 1*5s (stop) = 215s -> round to 4 min.
    assert route.duration_minutes == 4


def test_count_intersections():
    props = {
        "messages": [
            _HEADER,
            _row("highway=crossing crossing=traffic_signals"),
            _row("highway=crossing"),
            _row("highway=stop"),
        ]
    }
    signals, stops = _count_intersections(props)
    assert signals == 1
    assert stops == 1


def test_count_intersections_no_messages():
    assert _count_intersections({}) == (0, 0)


def test_parse_brouter_empty():
    with pytest.raises(PrimError, match="did not return"):
        _parse_brouter({"features": []}, A, B, "trekking")


async def test_bike_route_rejects_unknown_profile():
    """Profile validation happens before any network call."""
    with pytest.raises(PrimError, match="Unknown cycling profile"):
        await bike_route("A", "B", profile="rocket")


async def test_bike_route_rejects_shortest_profile():
    """'shortest' is excluded: it can route onto footways at walking pace."""
    with pytest.raises(PrimError, match="Unknown cycling profile"):
        await bike_route("A", "B", profile="shortest")
