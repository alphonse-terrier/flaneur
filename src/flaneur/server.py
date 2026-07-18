"""Flâneur MCP server: Île-de-France journeys, disruptions, cycling and weather.

Exposes six tools:
- ``geocode_address``: address/place → coordinates;
- ``plan_journey``: full public-transit journey with real-time disruptions;
- ``line_traffic``: traffic info (roadworks/incidents), network-wide or per line;
- ``next_departures``: real-time next departures at a stop;
- ``bike_route``: cycling route (via BRouter — PRIM doesn't route cycling);
- ``weather``: current weather and forecast for an address (via OpenWeatherMap).

The first four rely on Île-de-France Mobilités' PRIM API.
"""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

from flaneur.bike import bike_route as _bike_route
from flaneur.config import get_settings
from flaneur.departures import next_departures as _next_departures
from flaneur.disruptions import global_disruptions, line_disruptions
from flaneur.geocoding import resolve_place
from flaneur.journeys import plan_journey as _plan_journey
from flaneur.models import (
    BikeRoute,
    DeparturesResult,
    Disruption,
    GeoLocation,
    JourneyResult,
    WeatherResult,
)
from flaneur.weather import weather as _weather


def _transport_security() -> TransportSecuritySettings:
    """HTTP transport security (anti DNS-rebinding protection).

    Passed explicitly to override the SDK's default, which only allows
    localhost and returns 421 for a remote host (e.g. Render). Empty = the
    protection is disabled (fine for a public server behind HTTPS); otherwise
    it's locked down to the hosts declared in ALLOWED_HOSTS.
    """
    hosts = [h.strip() for h in get_settings().allowed_hosts.split(",") if h.strip()]
    if hosts:
        return TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=hosts + ["127.0.0.1:*", "localhost:*"],
        )
    return TransportSecuritySettings(enable_dns_rebinding_protection=False)


mcp = FastMCP(
    "flaneur",
    instructions=(
        "A mobility server for Île-de-France (Paris and its region), built on "
        "Île-de-France Mobilités' PRIM API. Use `plan_journey` to compute a "
        "public-transit route between two addresses with the impact of roadworks "
        "and incidents, `line_traffic` for a line's traffic info, `next_departures` "
        "for real-time next departures at a stop, `bike_route` for a cycling route "
        "(duration and distance), and `weather` for an address's weather."
    ),
    transport_security=_transport_security(),
)


@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(request: Request) -> JSONResponse:
    """Public health check for Render (the /mcp endpoint returns 406 to a bare GET)."""
    return JSONResponse({"status": "ok", "service": "flaneur"})


@mcp.tool()
async def geocode_address(query: str) -> GeoLocation:
    """Converts an address or place name into geographic coordinates.

    Args:
        query: Postal address, stop/station name, or `longitude;latitude` coordinates.

    Returns:
        The resolved place with its coordinates and normalized label.
    """
    return await resolve_place(query)


@mcp.tool()
async def plan_journey(
    origin: str,
    destination: str,
    when: str | None = None,
    arrive_by: bool = False,
    max_journeys: int = 3,
) -> JourneyResult:
    """Computes the best public-transit journey(s) between two places.

    The journey is computed in real time: every leg affected by roadworks or
    an incident carries the corresponding disruptions, and each journey
    reports its overall status (significant delays, service interruption, etc.).

    Args:
        origin: Starting place — address, stop name, or `lon;lat` coordinates.
        destination: Ending place — same formats as `origin`.
        when: Date/time in ISO 8601 format (e.g. `2026-07-18T08:30:00`). Default: now.
        arrive_by: If true, `when` is the desired arrival time (instead of departure).
        max_journeys: Maximum number of proposed journeys (1 to 5).

    Returns:
        The resolved places and the list of detailed journeys with disruptions.
    """
    return await _plan_journey(
        origin=origin,
        destination=destination,
        when=when,
        arrive_by=arrive_by,
        max_journeys=max_journeys,
    )


@mcp.tool()
async def line_traffic(line: str | None = None) -> list[Disruption]:
    """Returns traffic info: current and upcoming roadworks, incidents and disruptions.

    Args:
        line: Line name/number (e.g. `6`, `RER A`, `T3a`) or Navitia id
            (`line:IDFM:...`). If omitted, returns all network-wide disruptions.

    Returns:
        The list of disruptions (cause, effect, period, message, impacted objects).
    """
    if line:
        return await line_disruptions(line)
    return await global_disruptions()


@mcp.tool()
async def next_departures(stop: str, limit: int = 10) -> DeparturesResult:
    """Returns the next real-time departures at a stop.

    Args:
        stop: Stop/station name (e.g. `Châtelet`) or SIRI reference `STIF:StopArea:SP:...`.
        limit: Maximum number of departures to return.

    Returns:
        The resolved stop and the list of next departures (line, destination, time).
    """
    return await _next_departures(stop, limit=limit)


@mcp.tool()
async def bike_route(
    origin: str, destination: str, profile: str = "trekking"
) -> BikeRoute:
    """Computes a cycling route between two places (duration and distance).

    Complements `plan_journey`: PRIM doesn't compute cycling routes, so this
    tool relies on the BRouter cycling router. Use it for any "how long by
    bike from A to B?" question.

    Args:
        origin: Starting place — address, stop name, or `lon;lat` coordinates.
        destination: Ending place — same formats as `origin`.
        profile: Cycling profile — `trekking` (balanced, default), `fastbike` (faster),
            `shortest` (shortest distance).

    Returns:
        The resolved places, the distance (km) and the estimated cycling duration (minutes).
    """
    return await _bike_route(origin, destination, profile=profile)


@mcp.tool()
async def weather(location: str, days: int = 3) -> WeatherResult:
    """Fetches the weather (current + forecast) for an address or place.

    Useful for choosing between walking, cycling and transit based on the
    weather. Relies on OpenWeatherMap: send your key in the
    'X-OpenWeather-Api-Key' header (or set OPENWEATHER_API_KEY server-side).

    Args:
        location: Address, stop/city name, or `lon;lat` coordinates.
        days: Number of forecast days (1 to 5, default 3).

    Returns:
        The resolved place, current conditions and the daily forecast.
    """
    return await _weather(location, days=days)


def main() -> None:
    """Entry point: runs the server over HTTP transport (streamable-http).

    The port is read from $PORT (provided by Render), falling back to config.
    """
    settings = get_settings()
    mcp.settings.host = settings.host
    mcp.settings.port = int(os.environ.get("PORT", settings.port))
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
