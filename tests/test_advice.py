"""Tests for the composite mobility_advice tool (decision logic, no network)."""

from flaneur.advice import _bad_for_bike, _decide, _rain_expected, _summary
from flaneur.models import (
    BikeRoute,
    GeoLocation,
    Journey,
    WeatherCurrent,
    WeatherDay,
    WeatherResult,
)

A = GeoLocation(label="A", longitude=2.35, latitude=48.85)
B = GeoLocation(label="B", longitude=2.30, latitude=48.86)


def _bike(minutes: int) -> BikeRoute:
    return BikeRoute(
        origin=A, destination=B, profile="trekking", distance_km=3.0, duration_minutes=minutes
    )


def _transit(status: str = "", fare: float | None = 2.5) -> Journey:
    return Journey(status=status, duration_minutes=28, nb_transfers=1, fare_eur=fare)


def _wx(code=800, precip=0.0, pop=0) -> WeatherResult:
    return WeatherResult(
        location=A,
        current=WeatherCurrent(weather_code=code, precipitation_mm=precip, temperature_c=15),
        daily=[WeatherDay(date="2026-07-18", precipitation_probability_pct=pop)],
    )


def test_rain_expected():
    assert _rain_expected(_wx(precip=0.5)) is True
    assert _rain_expected(_wx(pop=70)) is True
    assert _rain_expected(_wx(precip=0.0, pop=10)) is False
    assert _rain_expected(None) is False


def test_bad_for_bike():
    assert _bad_for_bike(_wx(code=201)) is True  # thunderstorm
    assert _bad_for_bike(_wx(precip=2.0)) is True  # heavy rain
    assert _bad_for_bike(_wx(code=800, precip=0.0)) is False


def test_decide_prefers_bike_when_short_and_clear():
    mode, reasons = _decide(_transit(), True, _bike(15), bad_bike_weather=False)
    assert mode == "bike"
    assert any("quick" in r.lower() for r in reasons)


def test_decide_transit_when_bike_too_long():
    mode, _ = _decide(_transit(), True, _bike(40), bad_bike_weather=False)
    assert mode == "public_transport"


def test_decide_transit_when_weather_bad():
    mode, _ = _decide(_transit(), True, _bike(15), bad_bike_weather=True)
    assert mode == "public_transport"


def test_decide_falls_back_to_bike_when_transit_down():
    mode, reasons = _decide(_transit(status="NO_SERVICE"), False, _bike(40), bad_bike_weather=False)
    assert mode == "bike"
    assert any("disrupted" in r.lower() for r in reasons)


def test_summary_bike_and_transit():
    assert "Bike is best" in _summary("bike", _transit(), _bike(15), rain=False)
    s = _summary("public_transport", _transit(fare=2.5), _bike(40), rain=True)
    assert "public transport" in s.lower()
    assert "2.50" in s
    assert "rain" in s.lower()
