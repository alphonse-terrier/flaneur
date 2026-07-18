"""Météo pour une adresse via l'API Open-Meteo (gratuite, sans clé).

Géocode l'adresse (Base Adresse Nationale) puis interroge Open-Meteo pour les
conditions actuelles et les prévisions journalières. Utile pour arbitrer entre
marche, vélo et transports selon le temps.
"""

from __future__ import annotations

import time
from typing import Any

from idfm_mcp.config import get_settings
from idfm_mcp.geocoding import resolve_place
from idfm_mcp.models import GeoLocation, WeatherCurrent, WeatherDay, WeatherResult
from idfm_mcp.prim_client import public_get

# Cache mémoire : (lat arrondie, lon arrondie, jours) -> (expiration, (current, daily)).
# Arrondi à 2 décimales ≈ maille ~1 km, suffisant pour la météo.
_cache: dict[tuple[float, float, int], tuple[float, tuple[Any, list[Any]]]] = {}


def clear_cache() -> None:
    """Vide le cache météo (utile pour les tests)."""
    _cache.clear()

# Codes météo WMO → descriptions en français.
_WMO_CODES = {
    0: "Ciel dégagé",
    1: "Principalement dégagé",
    2: "Partiellement nuageux",
    3: "Couvert",
    45: "Brouillard",
    48: "Brouillard givrant",
    51: "Bruine légère",
    53: "Bruine modérée",
    55: "Bruine dense",
    56: "Bruine verglaçante légère",
    57: "Bruine verglaçante dense",
    61: "Pluie légère",
    63: "Pluie modérée",
    65: "Pluie forte",
    66: "Pluie verglaçante légère",
    67: "Pluie verglaçante forte",
    71: "Neige légère",
    73: "Neige modérée",
    75: "Neige forte",
    77: "Grains de neige",
    80: "Averses légères",
    81: "Averses modérées",
    82: "Averses violentes",
    85: "Averses de neige légères",
    86: "Averses de neige fortes",
    95: "Orage",
    96: "Orage avec grêle légère",
    99: "Orage avec grêle forte",
}

_CURRENT_FIELDS = (
    "temperature_2m",
    "apparent_temperature",
    "precipitation",
    "weather_code",
    "wind_speed_10m",
    "relative_humidity_2m",
)
_DAILY_FIELDS = (
    "weather_code",
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "precipitation_probability_max",
)


def _describe(code: Any) -> str | None:
    try:
        return _WMO_CODES.get(int(code))
    except (TypeError, ValueError):
        return None


async def weather(location: str, days: int = 3) -> WeatherResult:
    """Récupère la météo (actuelle + prévisions) pour une adresse ou un lieu.

    Les réponses sont mises en cache (par maille ~1 km) pendant quelques minutes
    pour limiter les appels à Open-Meteo. Si ``OPENMETEO_API_KEY`` est défini, on
    utilise l'endpoint client dédié (quota propre).
    """
    settings = get_settings()
    loc = await resolve_place(location)
    forecast_days = max(1, min(days, 7))

    key = (round(loc.latitude, 2), round(loc.longitude, 2), forecast_days)
    now = time.monotonic()
    cached = _cache.get(key)
    if cached and cached[0] > now:
        current, daily = cached[1]
        return WeatherResult(location=loc, current=current, daily=daily)

    params: dict[str, Any] = {
        "latitude": loc.latitude,
        "longitude": loc.longitude,
        "current": ",".join(_CURRENT_FIELDS),
        "daily": ",".join(_DAILY_FIELDS),
        "timezone": "Europe/Paris",
        "forecast_days": forecast_days,
    }
    if settings.openmeteo_api_key:
        base = settings.openmeteo_customer_base
        params["apikey"] = settings.openmeteo_api_key
    else:
        base = settings.openmeteo_base

    data = await public_get(base, params, source="Open-Meteo")
    current, daily = _parse_current(data), _parse_daily(data)
    _cache[key] = (now + settings.weather_cache_ttl, (current, daily))

    return WeatherResult(location=loc, current=current, daily=daily)


def _parse_current(data: Any) -> WeatherCurrent | None:
    current = (data or {}).get("current")
    if not current:
        return None
    return WeatherCurrent(
        time=current.get("time"),
        condition=_describe(current.get("weather_code")),
        weather_code=current.get("weather_code"),
        temperature_c=current.get("temperature_2m"),
        apparent_temperature_c=current.get("apparent_temperature"),
        precipitation_mm=current.get("precipitation"),
        wind_speed_kmh=current.get("wind_speed_10m"),
        humidity_pct=current.get("relative_humidity_2m"),
    )


def _parse_daily(data: Any) -> list[WeatherDay]:
    daily = (data or {}).get("daily") or {}
    dates = daily.get("time") or []
    days: list[WeatherDay] = []
    for i, date in enumerate(dates):
        code = _get(daily, "weather_code", i)
        days.append(
            WeatherDay(
                date=date,
                condition=_describe(code),
                weather_code=code,
                temp_min_c=_get(daily, "temperature_2m_min", i),
                temp_max_c=_get(daily, "temperature_2m_max", i),
                precipitation_mm=_get(daily, "precipitation_sum", i),
                precipitation_probability_pct=_get(daily, "precipitation_probability_max", i),
            )
        )
    return days


def _get(daily: dict[str, Any], key: str, i: int) -> Any:
    values = daily.get(key) or []
    return values[i] if i < len(values) else None
