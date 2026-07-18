"""Tests météo : parsing Open-Meteo, cache mémoire et routage clé API."""

import httpx
import pytest
import respx

from idfm_mcp import config
from idfm_mcp.prim_client import close_client
from idfm_mcp.weather import (
    _describe,
    _parse_current,
    _parse_daily,
    clear_cache,
    weather,
)

SAMPLE = {
    "current": {
        "time": "2026-07-18T13:45",
        "temperature_2m": 27.9,
        "apparent_temperature": 28.3,
        "precipitation": 0.0,
        "weather_code": 2,
        "wind_speed_10m": 8.2,
        "relative_humidity_2m": 34,
    },
    "daily": {
        "time": ["2026-07-18", "2026-07-19"],
        "weather_code": [3, 61],
        "temperature_2m_max": [29.6, 24.1],
        "temperature_2m_min": [18.7, 16.2],
        "precipitation_sum": [0.0, 5.4],
        "precipitation_probability_max": [3, 80],
    },
}


def test_describe_wmo():
    assert _describe(0) == "Ciel dégagé"
    assert _describe(2) == "Partiellement nuageux"
    assert _describe(61) == "Pluie légère"
    assert _describe(95) == "Orage"
    assert _describe(None) is None
    assert _describe("x") is None


def test_parse_current():
    cur = _parse_current(SAMPLE)
    assert cur is not None
    assert cur.temperature_c == 27.9
    assert cur.apparent_temperature_c == 28.3
    assert cur.condition == "Partiellement nuageux"
    assert cur.weather_code == 2
    assert cur.wind_speed_kmh == 8.2
    assert cur.humidity_pct == 34


def test_parse_current_missing():
    assert _parse_current({}) is None


def test_parse_daily():
    days = _parse_daily(SAMPLE)
    assert len(days) == 2
    d0, d1 = days
    assert d0.date == "2026-07-18"
    assert d0.condition == "Couvert"
    assert d0.temp_max_c == 29.6
    assert d0.temp_min_c == 18.7
    assert d1.condition == "Pluie légère"
    assert d1.precipitation_mm == 5.4
    assert d1.precipitation_probability_pct == 80


def test_parse_daily_empty():
    assert _parse_daily({}) == []


@pytest.fixture
def _fixed_location(monkeypatch):
    """Évite l'appel réseau du géocodeur : lieu figé."""
    from idfm_mcp.models import GeoLocation

    async def _fake_resolve(query, prefer_stops=False):
        return GeoLocation(label="Paris", longitude=2.3522, latitude=48.8566)

    monkeypatch.setattr("idfm_mcp.weather.resolve_place", _fake_resolve)


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    clear_cache()
    # weather.py utilise sa propre référence get_settings : c'est elle qu'on patche.
    monkeypatch.setattr(
        "idfm_mcp.weather.get_settings", lambda: config.Settings(_env_file=None)
    )
    yield
    clear_cache()


@respx.mock
async def test_cache_avoids_second_call(_fixed_location):
    route = respx.get(url__startswith="https://api.open-meteo.com").mock(
        return_value=httpx.Response(200, json={"current": {"temperature_2m": 20}, "daily": {}})
    )
    await close_client()
    r1 = await weather("Paris")
    r2 = await weather("Paris")  # servi par le cache
    assert r1.current.temperature_c == 20
    assert r2.current.temperature_c == 20
    assert route.call_count == 1  # un seul appel réseau grâce au cache
    await close_client()


@respx.mock
async def test_api_key_uses_customer_endpoint(monkeypatch, _fixed_location):
    monkeypatch.setattr(
        "idfm_mcp.weather.get_settings",
        lambda: config.Settings(_env_file=None, openmeteo_api_key="secret-key"),
    )
    route = respx.get(url__startswith="https://customer-api.open-meteo.com").mock(
        return_value=httpx.Response(200, json={"current": {"temperature_2m": 15}, "daily": {}})
    )
    await close_client()
    r = await weather("Paris")
    assert r.current.temperature_c == 15
    assert route.called
    assert "apikey=secret-key" in str(route.calls[0].request.url)
    await close_client()
