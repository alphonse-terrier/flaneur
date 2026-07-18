"""Tests météo OpenWeatherMap : parsing, agrégation journalière, cache, clé API."""

import httpx
import pytest
import respx

from idfm_mcp import config
from idfm_mcp.models import GeoLocation
from idfm_mcp.prim_client import PrimError, close_client
from idfm_mcp.weather import (
    _aggregate_daily,
    _parse_current,
    clear_cache,
    weather,
)

# Réponse OWM /weather (units=metric, lang=fr).
CURRENT = {
    "weather": [{"id": 803, "main": "Clouds", "description": "nuageux"}],
    "main": {"temp": 27.9, "feels_like": 28.3, "humidity": 34},
    "wind": {"speed": 2.5},  # m/s
    "rain": {"1h": 0.4},
    "dt": 1_752_840_000,
}

# Réponse OWM /forecast : créneaux de 3 h.
FORECAST = {
    "list": [
        {
            "dt_txt": "2026-07-18 12:00:00",
            "main": {"temp": 28.0, "temp_min": 25.0, "temp_max": 29.5},
            "weather": [{"id": 800, "description": "ciel dégagé"}],
            "pop": 0.1,
        },
        {
            "dt_txt": "2026-07-18 15:00:00",
            "main": {"temp": 30.0, "temp_min": 27.0, "temp_max": 31.0},
            "weather": [{"id": 500, "description": "légère pluie"}],
            "pop": 0.4,
            "rain": {"3h": 1.2},
        },
        {
            "dt_txt": "2026-07-19 12:00:00",
            "main": {"temp": 20.0, "temp_min": 16.0, "temp_max": 22.0},
            "weather": [{"id": 501, "description": "pluie modérée"}],
            "pop": 0.8,
            "rain": {"3h": 4.0},
        },
    ]
}


def test_parse_current():
    cur = _parse_current(CURRENT)
    assert cur is not None
    assert cur.temperature_c == 27.9
    assert cur.apparent_temperature_c == 28.3
    assert cur.condition == "Nuageux"  # 1re lettre en majuscule
    assert cur.weather_code == 803
    assert cur.wind_speed_kmh == 9.0  # 2.5 m/s -> 9 km/h
    assert cur.humidity_pct == 34
    assert cur.precipitation_mm == 0.4


def test_parse_current_missing():
    assert _parse_current({}) is None


def test_aggregate_daily():
    days = _aggregate_daily(FORECAST, 5)
    assert len(days) == 2
    d0, d1 = days
    assert d0.date == "2026-07-18"
    assert d0.temp_min_c == 25.0  # min des temp_min du jour
    assert d0.temp_max_c == 31.0  # max des temp_max du jour
    assert d0.precipitation_mm == 1.2  # somme rain 3h
    assert d0.precipitation_probability_pct == 40  # max pop
    assert d0.condition == "Ciel dégagé"  # créneau le plus proche de midi
    assert d1.date == "2026-07-19"
    assert d1.precipitation_probability_pct == 80


def test_aggregate_daily_respects_max_days():
    assert len(_aggregate_daily(FORECAST, 1)) == 1


@pytest.fixture
def _fixed_location(monkeypatch):
    async def _fake_resolve(query, prefer_stops=False):
        return GeoLocation(label="Paris", longitude=2.3522, latitude=48.8566)

    monkeypatch.setattr("idfm_mcp.weather.resolve_place", _fake_resolve)


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    clear_cache()
    monkeypatch.setattr(
        "idfm_mcp.weather.get_settings",
        lambda: config.Settings(_env_file=None, openweather_api_key="env-key"),
    )
    yield
    clear_cache()


def _mock_owm():
    respx.get(url__startswith="https://api.openweathermap.org/data/2.5/weather").mock(
        return_value=httpx.Response(200, json=CURRENT)
    )
    respx.get(url__startswith="https://api.openweathermap.org/data/2.5/forecast").mock(
        return_value=httpx.Response(200, json=FORECAST)
    )


@respx.mock
async def test_weather_end_to_end(_fixed_location):
    _mock_owm()
    await close_client()
    r = await weather("Paris", days=2)
    assert r.current.temperature_c == 27.9
    assert len(r.daily) == 2
    await close_client()


@respx.mock
async def test_cache_avoids_second_call(_fixed_location):
    w = respx.get(url__startswith="https://api.openweathermap.org/data/2.5/weather").mock(
        return_value=httpx.Response(200, json=CURRENT)
    )
    respx.get(url__startswith="https://api.openweathermap.org/data/2.5/forecast").mock(
        return_value=httpx.Response(200, json=FORECAST)
    )
    await close_client()
    await weather("Paris")
    await weather("Paris")  # servi par le cache
    assert w.call_count == 1
    await close_client()


@respx.mock
async def test_key_from_header_used(monkeypatch, _fixed_location):
    # Pas de clé env : la clé doit venir de l'en-tête de requête.
    monkeypatch.setattr(
        "idfm_mcp.weather.get_settings",
        lambda: config.Settings(_env_file=None, openweather_api_key=""),
    )
    monkeypatch.setattr(
        "idfm_mcp.weather.api_key_from_request", lambda names: "header-key"
    )
    route = respx.get(
        url__startswith="https://api.openweathermap.org/data/2.5/weather"
    ).mock(return_value=httpx.Response(200, json=CURRENT))
    respx.get(url__startswith="https://api.openweathermap.org/data/2.5/forecast").mock(
        return_value=httpx.Response(200, json=FORECAST)
    )
    await close_client()
    await weather("Paris")
    assert "appid=header-key" in str(route.calls[0].request.url)
    await close_client()


async def test_missing_key_raises(monkeypatch, _fixed_location):
    monkeypatch.setattr(
        "idfm_mcp.weather.get_settings",
        lambda: config.Settings(_env_file=None, openweather_api_key=""),
    )
    monkeypatch.setattr("idfm_mcp.weather.api_key_from_request", lambda names: None)
    with pytest.raises(PrimError, match="Aucune clé OpenWeatherMap"):
        await weather("Paris")
