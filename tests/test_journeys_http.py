"""End-to-end tests for plan_journey with mocked PRIM HTTP (respx)."""

import httpx
import pytest
import respx

from flaneur import config
from flaneur.journeys import plan_journey
from flaneur.prim_client import close_client

_JOURNEYS_URL = "https://prim.iledefrance-mobilites.fr/marketplace/v2/navitia/journeys"

PAYLOAD = {
    "journeys": [
        {
            "duration": 1560,
            "nb_transfers": 0,
            "type": "best",
            "status": "SIGNIFICANT_DELAYS",
            "departure_date_time": "20260718T120500",
            "arrival_date_time": "20260718T123100",
            "sections": [
                {
                    "type": "public_transport",
                    "duration": 1560,
                    "from": {"name": "Bercy"},
                    "to": {"name": "Bir-Hakeim"},
                    "display_informations": {
                        "label": "6",
                        "commercial_mode": "Metro",
                        "direction": "Charles de Gaulle — Étoile",
                        "links": [{"type": "disruption", "id": "d1"}],
                    },
                }
            ],
        }
    ],
    "disruptions": [
        {
            "id": "d1",
            "cause": "roadworks",
            "severity": {"name": "disrupted", "effect": "SIGNIFICANT_DELAYS"},
            "messages": [{"text": "<p>Delays on line 6.</p>"}],
            "impacted_objects": [{"pt_object": {"name": "6"}}],
        }
    ],
}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    from mcp.server.lowlevel.server import request_ctx

    request_ctx.set(None)  # no inbound HTTP request → env key is used
    monkeypatch.setattr(
        "flaneur.prim_client.get_settings",
        lambda: config.Settings(_env_file=None, prim_api_key="test-key"),
    )
    yield
    request_ctx.set(None)


@respx.mock
async def test_plan_journey_attaches_disruptions():
    route = respx.get(url__startswith=_JOURNEYS_URL).mock(
        return_value=httpx.Response(200, json=PAYLOAD)
    )
    await close_client()
    # Coordinates short-circuit geocoding (no BAN call needed).
    result = await plan_journey("2.3735;48.8443", "2.2945;48.8584")
    assert len(result.journeys) == 1
    j = result.journeys[0]
    assert j.status == "SIGNIFICANT_DELAYS"
    assert j.has_disruptions is True
    assert j.sections[0].disruptions[0].cause == "roadworks"
    # apikey header was injected.
    assert route.calls[0].request.headers.get("apikey") == "test-key"
    await close_client()


@respx.mock
async def test_plan_journey_arrive_by_passthrough():
    route = respx.get(url__startswith=_JOURNEYS_URL).mock(
        return_value=httpx.Response(200, json=PAYLOAD)
    )
    await close_client()
    await plan_journey("2.37;48.84", "2.29;48.85", when="2026-07-18T14:00:00", arrive_by=True)
    q = route.calls[0].request.url.params
    assert q["datetime_represents"] == "arrival"
    assert q["datetime"] == "20260718T140000"
    await close_client()


@respx.mock
async def test_plan_journey_no_results_returns_note():
    respx.get(url__startswith=_JOURNEYS_URL).mock(
        return_value=httpx.Response(200, json={"journeys": []})
    )
    await close_client()
    result = await plan_journey("2.37;48.84", "2.29;48.85")
    assert result.journeys == []
    assert result.note and "No journey" in result.note
    await close_client()
