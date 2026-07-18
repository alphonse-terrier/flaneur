"""Météo pour une adresse via l'API OpenWeatherMap.

Géocode l'adresse (Base Adresse Nationale) puis interroge OpenWeatherMap :
- ``/weather`` pour les conditions actuelles ;
- ``/forecast`` (créneaux de 3 h sur 5 jours) agrégé en prévisions journalières.

OpenWeatherMap exige une clé : chaque client peut l'envoyer dans l'en-tête
``X-OpenWeather-Api-Key`` ; sinon on utilise la variable ``OPENWEATHER_API_KEY``.
Les réponses sont mises en cache quelques minutes pour limiter les appels.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from idfm_mcp.config import Settings, get_settings
from idfm_mcp.geocoding import resolve_place
from idfm_mcp.models import WeatherCurrent, WeatherDay, WeatherResult
from idfm_mcp.prim_client import PrimError, api_key_from_request, public_get

# En-têtes acceptés pour transmettre la clé OpenWeatherMap par requête.
OPENWEATHER_HEADERS = ("x-openweather-api-key", "openweather-api-key")

# Cache mémoire : (lat arrondie, lon arrondie, jours) -> (expiration, (current, daily)).
_cache: dict[tuple[float, float, int], tuple[float, tuple[Any, list[Any]]]] = {}


def clear_cache() -> None:
    """Vide le cache météo (utile pour les tests)."""
    _cache.clear()


def _resolve_key(settings: Settings) -> str:
    key = api_key_from_request(OPENWEATHER_HEADERS)
    if not key:
        key = settings.openweather_api_key.strip() or None
    if not key:
        raise PrimError(
            "Aucune clé OpenWeatherMap fournie. Envoyez-la dans l'en-tête "
            "'X-OpenWeather-Api-Key' (ou définissez OPENWEATHER_API_KEY). "
            "Créez une clé gratuite sur https://openweathermap.org/api."
        )
    return key


async def weather(location: str, days: int = 3) -> WeatherResult:
    """Récupère la météo (actuelle + prévisions) pour une adresse ou un lieu."""
    settings = get_settings()
    key = _resolve_key(settings)
    loc = await resolve_place(location)
    forecast_days = max(1, min(days, 5))  # OWM (offre gratuite) : 5 jours max

    cache_key = (round(loc.latitude, 2), round(loc.longitude, 2), forecast_days)
    now = time.monotonic()
    cached = _cache.get(cache_key)
    if cached and cached[0] > now:
        current, daily = cached[1]
        return WeatherResult(location=loc, current=current, daily=daily)

    common = {
        "lat": loc.latitude,
        "lon": loc.longitude,
        "appid": key,
        "units": "metric",
        "lang": "fr",
    }
    current_data = await public_get(
        f"{settings.openweather_base}/weather", common, source="OpenWeatherMap"
    )
    forecast_data = await public_get(
        f"{settings.openweather_base}/forecast", common, source="OpenWeatherMap"
    )

    current = _parse_current(current_data)
    daily = _aggregate_daily(forecast_data, forecast_days)
    _cache[cache_key] = (now + settings.weather_cache_ttl, (current, daily))

    return WeatherResult(location=loc, current=current, daily=daily)


def _cap(text: Any) -> str | None:
    if not isinstance(text, str) or not text:
        return None
    return text[0].upper() + text[1:]


def _first_weather(item: dict[str, Any]) -> dict[str, Any]:
    weather_list = item.get("weather") or []
    return weather_list[0] if weather_list else {}


def _parse_current(data: Any) -> WeatherCurrent | None:
    if not isinstance(data, dict) or not data.get("main"):
        return None
    main = data.get("main") or {}
    wind = data.get("wind") or {}
    w = _first_weather(data)
    precip = _precip(data, "1h")
    dt = data.get("dt")
    return WeatherCurrent(
        time=_iso(dt),
        condition=_cap(w.get("description")),
        weather_code=w.get("id"),
        temperature_c=main.get("temp"),
        apparent_temperature_c=main.get("feels_like"),
        precipitation_mm=precip,
        wind_speed_kmh=round(wind["speed"] * 3.6, 1) if wind.get("speed") is not None else None,
        humidity_pct=main.get("humidity"),
    )


def _aggregate_daily(data: Any, max_days: int) -> list[WeatherDay]:
    items = (data or {}).get("list") or []
    by_date: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        date = (item.get("dt_txt") or "")[:10]
        if date:
            by_date.setdefault(date, []).append(item)

    days: list[WeatherDay] = []
    for date in sorted(by_date)[:max_days]:
        group = by_date[date]
        mins = [_temp_min(g) for g in group if _temp_min(g) is not None]
        maxs = [_temp_max(g) for g in group if _temp_max(g) is not None]
        precip = sum(_precip(g, "3h") or 0.0 for g in group)
        pops = [g.get("pop") for g in group if g.get("pop") is not None]
        midday = _closest_to_noon(group)
        w = _first_weather(midday)
        days.append(
            WeatherDay(
                date=date,
                condition=_cap(w.get("description")),
                weather_code=w.get("id"),
                temp_min_c=round(min(mins), 1) if mins else None,
                temp_max_c=round(max(maxs), 1) if maxs else None,
                precipitation_mm=round(precip, 1),
                precipitation_probability_pct=round(max(pops) * 100) if pops else None,
            )
        )
    return days


def _temp_min(item: dict[str, Any]) -> float | None:
    main = item.get("main") or {}
    return main.get("temp_min", main.get("temp"))


def _temp_max(item: dict[str, Any]) -> float | None:
    main = item.get("main") or {}
    return main.get("temp_max", main.get("temp"))


def _precip(item: dict[str, Any], window: str) -> float | None:
    rain = (item.get("rain") or {}).get(window) or 0.0
    snow = (item.get("snow") or {}).get(window) or 0.0
    total = rain + snow
    return round(total, 1) if total else (0.0 if item.get("rain") or item.get("snow") else None)


def _closest_to_noon(group: list[dict[str, Any]]) -> dict[str, Any]:
    def hour_gap(item: dict[str, Any]) -> int:
        txt = item.get("dt_txt") or ""
        try:
            return abs(int(txt[11:13]) - 12)
        except (ValueError, IndexError):
            return 99

    return min(group, key=hour_gap)


def _iso(dt: Any) -> str | None:
    try:
        return datetime.fromtimestamp(int(dt), tz=timezone.utc).isoformat()
    except (TypeError, ValueError):
        return None
