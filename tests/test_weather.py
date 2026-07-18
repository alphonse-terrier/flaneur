"""OpenWeatherMap weather tests: parsing, daily aggregation, cache, API key."""

import httpx
import pytest
import respx

from flaneur import config
from flaneur.models import GeoLocation
from flaneur.prim_client import PrimError, close_client
from flaneur.weather import (
    _aggregate_daily,
    _parse_current,
    clear_cache,
    weather,
)

# OWM /weather response (units=metric, lang=en).
CURRENT = {
    "weather": [{"id": 803, "main": "Clouds", "description": "cloudy"}],
    "main": {"temp": 27.9, "feels_like": 28.3, "humidity": 34},
    "wind": {"speed": 2.5},  # m/s
    "rain": {"1h": 0.4},
    "dt": 1_752_840_000,
}

# OWM /forecast response: 3-hour slots.
FORECAST = {
    "list": [
        {
            "dt_txt": "2026-07-18 12:00:00",
            "main": {"temp": 28.0, "temp_min": 25.0, "temp_max": 29.5},
            "weather": [{"id": 800, "description": "clear sky"}],
            "pop": 0.1,
        },
        {
            "dt_txt": "2026-07-18 15:00:00",
            "main": {"temp": 30.0, "temp_min": 27.0, "temp_max": 31.0},
            "weather": [{"id": 500, "description": "light rain"}],
            "pop": 0.4,
            "rain": {"3h": 1.2},
        },
        {
            "dt_txt": "2026-07-19 12:00:00",
            "main": {"temp": 20.0, "temp_min": 16.0, "temp_max": 22.0},
            "weather": [{"id": 501, "description": "moderate rain"}],
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
    assert cur.condition == "Cloudy"  # first letter capitalized
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
    assert d0.temp_min_c == 25.0  # min of the day's temp_min values
    assert d0.temp_max_c == 31.0  # max of the day's temp_max values
    assert d0.precipitation_mm == 1.2  # sum of 3h rain
    assert d0.precipitation_probability_pct == 40  # max pop
    assert d0.condition == "Clear sky"  # slot closest to noon
    assert d1.date == "2026-07-19"
    assert d1.precipitation_probability_pct == 80


def test_aggregate_daily_respects_max_days():
    assert len(_aggregate_daily(FORECAST, 1)) == 1


@pytest.fixture
def _fixed_location(monkeypatch):
    async def _fake_resolve(query, prefer_stops=False):
        return GeoLocation(label="Paris", longitude=2.3522, latitude=48.8566)

    monkeypatch.setattr("flaneur.weather.resolve_place", _fake_resolve)


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    clear_cache()
    monkeypatch.setattr(
        "flaneur.weather.get_settings",
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
    await weather("Paris")  # served from cache
    assert w.call_count == 1
    await close_client()


@respx.mock
async def test_key_from_header_used(monkeypatch, _fixed_location):
    # No env key: the key must come from the request header.
    monkeypatch.setattr(
        "flaneur.weather.get_settings",
        lambda: config.Settings(_env_file=None, openweather_api_key=""),
    )
    monkeypatch.setattr("flaneur.weather.api_key_from_request", lambda names: "header-key")
    route = respx.get(url__startswith="https://api.openweathermap.org/data/2.5/weather").mock(
        return_value=httpx.Response(200, json=CURRENT)
    )
    respx.get(url__startswith="https://api.openweathermap.org/data/2.5/forecast").mock(
        return_value=httpx.Response(200, json=FORECAST)
    )
    await close_client()
    await weather("Paris")
    assert "appid=header-key" in str(route.calls[0].request.url)
    await close_client()


async def test_missing_key_raises(monkeypatch, _fixed_location):
    monkeypatch.setattr(
        "flaneur.weather.get_settings",
        lambda: config.Settings(_env_file=None, openweather_api_key=""),
    )
    monkeypatch.setattr("flaneur.weather.api_key_from_request", lambda names: None)
    with pytest.raises(PrimError, match="No OpenWeatherMap key"):
        await weather("Paris")
