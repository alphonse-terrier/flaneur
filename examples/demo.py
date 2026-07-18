#!/usr/bin/env python
"""Flâneur demo — call the live (or local) MCP server and print a few results.

Run against the hosted server (default):

    uv run python examples/demo.py

Point it elsewhere and pass your keys via env vars:

    FLANEUR_URL=http://localhost:8000/mcp \
    PRIM_API_KEY=xxxx OPENWEATHER_API_KEY=yyyy \
    uv run python examples/demo.py

Keys are sent as per-request HTTP headers (the server is multi-user and stores
nothing). Without a PRIM key, the transit tools return a friendly auth error;
without an OpenWeatherMap key, weather-dependent output degrades gracefully.
"""

from __future__ import annotations

import asyncio
import json
import os

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

URL = os.environ.get("FLANEUR_URL", "https://idfm-mcp.onrender.com/mcp")

HEADERS = {}
if os.environ.get("PRIM_API_KEY"):
    HEADERS["X-PRIM-Api-Key"] = os.environ["PRIM_API_KEY"]
if os.environ.get("OPENWEATHER_API_KEY"):
    HEADERS["X-OpenWeather-Api-Key"] = os.environ["OPENWEATHER_API_KEY"]


def _result(call) -> dict | str:
    """Extract a tool result as structured data (or text)."""
    if getattr(call, "structuredContent", None):
        return call.structuredContent
    for block in call.content:
        text = getattr(block, "text", None)
        if text:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text
    return {}


async def main() -> None:
    print(f"Connecting to {URL} ...")
    if not HEADERS.get("X-PRIM-Api-Key"):
        print("(no PRIM_API_KEY set — transit tools will return an auth error)\n")

    async with streamablehttp_client(URL, headers=HEADERS) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("Tools:", ", ".join(t.name for t in tools.tools), "\n")

            # 1) One-call recommendation (transit vs bike, weather-aware).
            print("== mobility_advice: Gare de Lyon → La Défense ==")
            advice = _result(
                await session.call_tool(
                    "mobility_advice",
                    {"origin": "Gare de Lyon, Paris", "destination": "La Défense"},
                )
            )
            if isinstance(advice, dict):
                print(" ", advice.get("summary"))
                for r in advice.get("reasons", []):
                    print("   -", r)
            else:
                print(" ", advice)

            # 2) Real-time Vélib' availability (no key needed).
            print("\n== velib_nearby: Notre-Dame ==")
            velib = _result(
                await session.call_tool(
                    "velib_nearby", {"location": "Notre-Dame, Paris", "limit": 3}
                )
            )
            if isinstance(velib, dict):
                for s in velib.get("stations", []):
                    print(
                        f"   {s['name']} — {s['distance_m']} m — "
                        f"{s['bikes_available']} bikes, {s['docks_available']} docks"
                    )
            else:
                print(" ", velib)

            # 3) A full transit itinerary with real-time status + fare.
            print("\n== plan_journey: Châtelet → Charles de Gaulle - Étoile ==")
            jr = _result(
                await session.call_tool(
                    "plan_journey",
                    {
                        "origin": "Châtelet, Paris",
                        "destination": "Charles de Gaulle - Étoile, Paris",
                    },
                )
            )
            journeys = jr.get("journeys") if isinstance(jr, dict) else None
            if journeys:
                j = journeys[0]
                fare = f", {j['fare_eur']:.2f} €" if j.get("fare_eur") is not None else ""
                status = f" [{j['status']}]" if j.get("status") else ""
                print(
                    f"   {j['duration_minutes']} min, {j['nb_transfers']} transfer(s){fare}{status}"
                )
                for s in j.get("sections", []):
                    print("     ·", s.get("label"))
            else:
                print(" ", jr.get("note") if isinstance(jr, dict) else jr)


if __name__ == "__main__":
    asyncio.run(main())
