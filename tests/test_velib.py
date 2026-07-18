"""Tests for velib_nearby with mocked GBFS feeds (respx)."""

import httpx
import pytest
import respx

from flaneur.models import GeoLocation
from flaneur.prim_client import close_client
from flaneur.velib import _bike_type_counts, _haversine_m, velib_nearby

_BASE = "https://velib-metropole-opendata.smovengo.cloud/opendata/Velib_Metropole"

INFO = {
    "data": {
        "stations": [
            {
                "station_id": 1,
                "stationCode": "16107",
                "name": "Close",
                "lat": 48.8567,
                "lon": 2.3523,
                "capacity": 30,
            },
            {
                "station_id": 2,
                "stationCode": "16108",
                "name": "Far",
                "lat": 48.90,
                "lon": 2.50,
                "capacity": 20,
            },
        ]
    }
}
STATUS = {
    "data": {
        "stations": [
            {
                "station_id": 1,
                "numBikesAvailable": 5,
                "numDocksAvailable": 24,
                "num_bikes_available_types": [{"mechanical": 3}, {"ebike": 2}],
            },
            {"station_id": 2, "numBikesAvailable": 0, "numDocksAvailable": 20},
        ]
    }
}


@pytest.fixture(autouse=True)
def _fixed_location(monkeypatch):
    async def _fake_resolve(query, prefer_stops=False):
        return GeoLocation(label="Notre-Dame", longitude=2.3499, latitude=48.8530)

    monkeypatch.setattr("flaneur.velib.resolve_place", _fake_resolve)


def test_haversine_m():
    # ~1.1 km between two points ~0.01° apart in latitude.
    assert 1000 < _haversine_m(48.85, 2.35, 48.86, 2.35) < 1200


def test_bike_type_counts():
    mech, elec = _bike_type_counts({"num_bikes_available_types": [{"mechanical": 3}, {"ebike": 2}]})
    assert mech == 3
    assert elec == 2
    assert _bike_type_counts({}) == (None, None)


@respx.mock
async def test_velib_nearby_sorts_and_parses():
    respx.get(f"{_BASE}/station_information.json").mock(return_value=httpx.Response(200, json=INFO))
    respx.get(f"{_BASE}/station_status.json").mock(return_value=httpx.Response(200, json=STATUS))
    await close_client()
    result = await velib_nearby("Notre-Dame", limit=5)
    assert [s.name for s in result.stations] == ["Close", "Far"]  # nearest first
    close = result.stations[0]
    assert close.bikes_available == 5
    assert close.mechanical_bikes == 3
    assert close.electric_bikes == 2
    assert close.docks_available == 24
    await close_client()
