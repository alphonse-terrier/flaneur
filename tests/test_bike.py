"""Tests de l'itinéraire vélo (parsing BRouter, sans appel réseau)."""

import pytest

from idfm_mcp.bike import _parse_brouter, bike_route
from idfm_mcp.models import GeoLocation
from idfm_mcp.prim_client import PrimError

A = GeoLocation(label="Bastille", longitude=2.3692, latitude=48.8531)
B = GeoLocation(label="La Défense", longitude=2.2377, latitude=48.8918)

# Réponse BRouter typique (GeoJSON) : métriques sous forme de chaînes.
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


def test_parse_brouter():
    route = _parse_brouter(SAMPLE, A, B, "trekking")
    assert route.distance_km == 11.46  # 11463 m
    assert route.duration_minutes == 36  # 2181 s ≈ 36 min
    assert route.profile == "trekking"
    assert route.origin.label == "Bastille"
    assert route.destination.label == "La Défense"


def test_parse_brouter_empty():
    with pytest.raises(PrimError, match="n'a pas retourné"):
        _parse_brouter({"features": []}, A, B, "trekking")


async def test_bike_route_rejects_unknown_profile():
    """La validation du profil a lieu avant tout appel réseau."""
    with pytest.raises(PrimError, match="Profil vélo inconnu"):
        await bike_route("A", "B", profile="fusée")
