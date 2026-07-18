"""Tests for the HTTP client: per-source error messages and 429/503 retry."""

import httpx
import pytest
import respx

from flaneur import prim_client
from flaneur.prim_client import PrimError, _explain_status, close_client, public_get


def _status_error(status: int) -> httpx.HTTPStatusError:
    req = httpx.Request("GET", "https://x")
    resp = httpx.Response(status, request=req)
    return httpx.HTTPStatusError("err", request=req, response=resp)


def test_429_message_is_source_specific_for_third_party():
    msg = str(_explain_status(_status_error(429), "OpenWeatherMap"))
    assert "429" in msg
    assert "PRIM" not in msg  # must not mention PRIM for a third-party source


def test_429_message_mentions_prim_for_navitia():
    msg = str(_explain_status(_status_error(429), "Navitia /journeys"))
    assert "PRIM" in msg


@respx.mock
async def test_retry_then_success(monkeypatch):
    monkeypatch.setattr(prim_client, "_RETRY_BACKOFF", 0)
    respx.get("https://svc.test/data").mock(
        side_effect=[httpx.Response(429), httpx.Response(200, json={"ok": True})]
    )
    await close_client()  # new client, intercepted by respx
    result = await public_get("https://svc.test/data", None, source="Test")
    assert result == {"ok": True}
    await close_client()


@respx.mock
async def test_retry_exhausted_raises(monkeypatch):
    monkeypatch.setattr(prim_client, "_RETRY_BACKOFF", 0)
    respx.get("https://svc.test/down").mock(return_value=httpx.Response(429))
    await close_client()
    with pytest.raises(PrimError, match="429"):
        await public_get("https://svc.test/down", None, source="Test")
    await close_client()
