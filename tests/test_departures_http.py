"""End-to-end tests for next_departures with mocked SIRI HTTP (respx)."""

import httpx
import pytest
import respx

from flaneur import config
from flaneur.departures import next_departures
from flaneur.prim_client import close_client

_SM_URL = "https://prim.iledefrance-mobilites.fr/marketplace/stop-monitoring"

SIRI = {
    "Siri": {
        "ServiceDelivery": {
            "StopMonitoringDelivery": [
                {
                    "MonitoredStopVisit": [
                        {
                            "MonitoredVehicleJourney": {
                                "LineRef": {"value": "STIF:Line::C01742:"},
                                "DestinationName": [{"value": "La Défense"}],
                                "MonitoredCall": {
                                    "ExpectedDepartureTime": "2026-07-18T12:10:00Z",
                                    "AimedDepartureTime": "2026-07-18T12:08:00Z",
                                    "DepartureStatus": "delayed",
                                },
                            }
                        }
                    ]
                }
            ]
        }
    }
}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    from mcp.server.lowlevel.server import request_ctx

    request_ctx.set(None)
    monkeypatch.setattr(
        "flaneur.prim_client.get_settings",
        lambda: config.Settings(_env_file=None, prim_api_key="test-key"),
    )
    yield
    request_ctx.set(None)


@respx.mock
async def test_next_departures_parses_siri():
    route = respx.get(url__startswith=_SM_URL).mock(return_value=httpx.Response(200, json=SIRI))
    await close_client()
    # A direct STIF ref skips the Navitia /places stop resolution.
    result = await next_departures("STIF:StopArea:SP:71517:")
    assert len(result.departures) == 1
    dep = result.departures[0]
    assert dep.line == "C01742"
    assert dep.destination == "La Défense"
    assert dep.status == "delayed"
    assert route.calls[0].request.url.params["MonitoringRef"] == "STIF:StopArea:SP:71517:"
    await close_client()


@respx.mock
async def test_next_departures_empty_returns_note():
    respx.get(url__startswith=_SM_URL).mock(return_value=httpx.Response(200, json={"Siri": {}}))
    await close_client()
    result = await next_departures("STIF:StopArea:SP:71517:")
    assert result.departures == []
    assert result.note
    await close_client()
