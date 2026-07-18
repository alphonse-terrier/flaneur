"""Composite mobility advice: fuse transit + bike + weather into one recommendation.

This is the skill's "get me there" logic exposed as a single server-side tool, so
any MCP client gets a ranked recommendation ("leave by bike — it's dry and your
line is disrupted") in one call, without orchestrating the tools itself.
"""

from __future__ import annotations

from flaneur.bike import bike_route
from flaneur.geocoding import resolve_place
from flaneur.journeys import plan_journey
from flaneur.models import MobilityAdvice, WeatherCurrent
from flaneur.prim_client import PrimError
from flaneur.weather import weather

# OpenWeatherMap condition codes that make cycling a bad idea.
_SEVERE_WEATHER = set(range(200, 233)) | {602} | set(range(611, 623)) | {762, 771, 781}
# Prefer the bike only for reasonably short rides.
_BIKE_MAX_MINUTES = 25


def _rain_expected(wx) -> bool:
    if wx is None:
        return False
    cur = wx.current
    if cur and cur.precipitation_mm and cur.precipitation_mm > 0.2:
        return True
    if wx.daily:
        pop = wx.daily[0].precipitation_probability_pct
        if pop is not None and pop >= 50:
            return True
    return False


def _bad_for_bike(wx) -> bool:
    if wx is None:
        return False
    cur = wx.current
    if cur and cur.weather_code in _SEVERE_WEATHER:
        return True
    # Meaningful rain during the window, not just a chance later.
    return bool(cur and cur.precipitation_mm and cur.precipitation_mm > 1)


async def mobility_advice(
    origin: str,
    destination: str,
    when: str | None = None,
    arrive_by: bool = False,
) -> MobilityAdvice:
    """Fuses transit, cycling and weather into a single recommendation."""
    origin_loc = await resolve_place(origin)
    destination_loc = await resolve_place(destination)
    oc, dc = origin_loc.lonlat, destination_loc.lonlat

    # Transit (real-time, with disruptions). Reuse geocoded coords to avoid re-geocoding.
    transit_result = await plan_journey(oc, dc, when=when, arrive_by=arrive_by, max_journeys=1)
    transit = transit_result.journeys[0] if transit_result.journeys else None

    # Bike (no key needed). Degrade gracefully if the router can't route it.
    try:
        bike = await bike_route(oc, dc)
    except PrimError:
        bike = None

    # Weather is optional (needs an OpenWeatherMap key); never let it block advice.
    wx = None
    weather_note = None
    try:
        wx = await weather(dc, days=1)
    except PrimError as exc:
        weather_note = f"Weather unavailable ({exc})."

    current: WeatherCurrent | None = wx.current if wx else None
    rain = _rain_expected(wx)
    bad_bike_weather = _bad_for_bike(wx)
    transit_ok = transit is not None and transit.status != "NO_SERVICE"

    mode, reasons = _decide(transit, transit_ok, bike, bad_bike_weather)
    summary = _summary(mode, transit, bike, rain)

    return MobilityAdvice(
        origin=origin_loc,
        destination=destination_loc,
        recommended_mode=mode,
        summary=summary,
        reasons=reasons,
        transit=transit,
        bike=bike,
        weather=current,
        rain_expected=rain,
        note=weather_note,
    )


def _decide(transit, transit_ok, bike, bad_bike_weather) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if transit and not transit_ok:
        reasons.append("The transit route is currently out of service.")
    if bad_bike_weather:
        reasons.append("Weather is poor for cycling.")

    bike_short = bike is not None and bike.duration_minutes <= _BIKE_MAX_MINUTES
    if bike is not None and bike_short and not bad_bike_weather:
        reasons.append(f"Bike is quick ({bike.duration_minutes} min) and the weather is fine.")
        return "bike", reasons
    if transit_ok:
        if bike is not None and not bike_short:
            reasons.append(f"Too far to cycle comfortably ({bike.duration_minutes} min).")
        return "public_transport", reasons
    if bike is not None:
        reasons.append("Falling back to the bike since transit is disrupted.")
        return "bike", reasons
    return "public_transport", reasons or ["No strong signal; defaulting to transit."]


def _summary(mode, transit, bike, rain) -> str:
    rain_tag = " ☔ rain expected — take a jacket." if rain else ""
    if mode == "bike" and bike is not None:
        return f"🚴 Bike is best: {bike.distance_km} km, ~{bike.duration_minutes} min.{rain_tag}"
    if transit is not None:
        fare = f", {transit.fare_eur:.2f} €" if transit.fare_eur is not None else ""
        status = ""
        if transit.status and transit.status != "":
            status = f" (status: {transit.status})"
        return (
            f"🚇 Take public transport: ~{transit.duration_minutes} min, "
            f"{transit.nb_transfers} transfer(s){fare}{status}.{rain_tag}"
        )
    return "No route could be computed for this trip." + rain_tag
