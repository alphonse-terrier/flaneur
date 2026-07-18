"""Tests for resolving the PRIM key per request (HTTP header) or via env."""

import pytest
from starlette.datastructures import Headers

from flaneur import config
from flaneur.prim_client import PrimError, resolve_api_key


class _FakeRequest:
    def __init__(self, headers: dict[str, str]):
        self.headers = Headers(headers)


class _FakeCtx:
    def __init__(self, headers: dict[str, str]):
        self.request = _FakeRequest(headers)


def _set_request(headers: dict[str, str] | None):
    """Sets the MCP SDK's request ContextVar (or clears it)."""
    from mcp.server.lowlevel.server import request_ctx

    if headers is None:
        return request_ctx.set(None)
    return request_ctx.set(_FakeCtx(headers))


@pytest.fixture(autouse=True)
def _reset_request_ctx():
    from mcp.server.lowlevel.server import request_ctx

    yield
    # Clear any request context left behind by a test.
    request_ctx.set(None)


@pytest.fixture(autouse=True)
def _isolate_settings(monkeypatch):
    """Isolates tests from the .env file: config only reads os.environ."""
    import flaneur.prim_client as prim_client

    monkeypatch.delenv("PRIM_API_KEY", raising=False)

    def _fresh_settings():
        return config.Settings(_env_file=None)

    monkeypatch.setattr(prim_client, "get_settings", _fresh_settings)
    yield


def test_key_from_custom_header():
    _set_request({"X-PRIM-Api-Key": "header-token"})
    assert resolve_api_key() == "header-token"


def test_key_from_apikey_header():
    _set_request({"apikey": "legacy-token"})
    assert resolve_api_key() == "legacy-token"


def test_key_from_bearer():
    _set_request({"Authorization": "Bearer bearer-token"})
    assert resolve_api_key() == "bearer-token"


def test_header_takes_precedence_over_env(monkeypatch):
    monkeypatch.setenv("PRIM_API_KEY", "env-token")
    _set_request({"X-PRIM-Api-Key": "header-token"})
    assert resolve_api_key() == "header-token"


def test_env_fallback_without_request(monkeypatch):
    monkeypatch.setenv("PRIM_API_KEY", "env-token")
    _set_request(None)  # no HTTP request (stdio/local case)
    assert resolve_api_key() == "env-token"


def test_missing_key_raises():
    _set_request(None)
    with pytest.raises(PrimError, match="No PRIM key"):
        resolve_api_key()
