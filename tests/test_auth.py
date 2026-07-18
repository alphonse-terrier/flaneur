"""Tests de la résolution de la clé PRIM par requête (en-tête HTTP) ou par env."""

import pytest
from starlette.datastructures import Headers

from idfm_mcp import config
from idfm_mcp.prim_client import PrimError, resolve_api_key


class _FakeRequest:
    def __init__(self, headers: dict[str, str]):
        self.headers = Headers(headers)


class _FakeCtx:
    def __init__(self, headers: dict[str, str]):
        self.request = _FakeRequest(headers)


def _set_request(headers: dict[str, str] | None):
    """Positionne la ContextVar de requête du SDK MCP (ou l'efface)."""
    from mcp.server.lowlevel.server import request_ctx

    if headers is None:
        return request_ctx.set(None)
    return request_ctx.set(_FakeCtx(headers))


@pytest.fixture(autouse=True)
def _reset_request_ctx():
    from mcp.server.lowlevel.server import request_ctx

    yield
    # Efface tout contexte de requête laissé par un test.
    request_ctx.set(None)


@pytest.fixture(autouse=True)
def _isolate_settings(monkeypatch):
    """Isole les tests du fichier .env : la config ne lit que os.environ."""
    import idfm_mcp.prim_client as prim_client

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
    _set_request(None)  # aucune requête HTTP (cas stdio/local)
    assert resolve_api_key() == "env-token"


def test_missing_key_raises():
    _set_request(None)
    with pytest.raises(PrimError, match="Aucune clé PRIM"):
        resolve_api_key()
