"""End-to-end tests for line_traffic (disruptions) with mocked PRIM HTTP (respx)."""

import httpx
import pytest
import respx

from flaneur import config
from flaneur.disruptions import global_disruptions, line_disruptions
from flaneur.prim_client import close_client

_BULK_URL = "https://prim.iledefrance-mobilites.fr/marketplace/disruptions_bulk"
_LINE_REPORTS_URL = (
    "https://prim.iledefrance-mobilites.fr/marketplace/v2/navitia/line_reports/line_reports"
)

DISRUPTIONS = {
    "disruptions": [
        {
            "id": "d1",
            "cause": "incident",
            "severity": {"name": "blocking", "effect": "NO_SERVICE"},
            "messages": [{"text": "Service interrupted."}],
            "impacted_objects": [{"pt_object": {"name": "6"}}],
        }
    ]
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
async def test_global_disruptions():
    respx.get(url__startswith=_BULK_URL).mock(return_value=httpx.Response(200, json=DISRUPTIONS))
    await close_client()
    result = await global_disruptions()
    assert len(result) == 1
    assert result[0].effect == "NO_SERVICE"
    await close_client()


@respx.mock
async def test_line_disruptions_filters_by_label():
    respx.get(url__startswith=_LINE_REPORTS_URL).mock(
        return_value=httpx.Response(200, json=DISRUPTIONS)
    )
    await close_client()
    result = await line_disruptions("6")
    assert len(result) == 1
    assert "6" in result[0].impacted_objects
    await close_client()


@respx.mock
async def test_line_disruptions_no_match_returns_empty():
    # A line with no matching disruption returns [] — not the whole network's list.
    respx.get(url__startswith=_LINE_REPORTS_URL).mock(
        return_value=httpx.Response(200, json=DISRUPTIONS)
    )
    await close_client()
    result = await line_disruptions("14")
    assert result == []
    await close_client()
