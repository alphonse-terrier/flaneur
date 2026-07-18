"""Shared HTTP client for calls to the PRIM API and the national geocoder.

A single ``httpx.AsyncClient`` is reused for the server's whole lifetime. The
PRIM key is resolved **per request**: each client sends its own via an HTTP
header (``X-PRIM-Api-Key``), falling back to the ``PRIM_API_KEY`` env var.
Network and HTTP errors are converted into ``PrimError`` with a clear message,
so MCP tools return an actionable explanation instead of a raw exception.
"""

from __future__ import annotations

import asyncio
from typing import Any, Mapping

import httpx

from flaneur.config import Settings, get_settings

# HTTP headers accepted for passing the PRIM key per request (case-insensitive).
API_KEY_HEADERS = ("x-prim-api-key", "apikey", "prim-api-key")

# Retry on transient status codes (rate limiting / momentary unavailability).
_RETRY_STATUS = {429, 503}
_MAX_RETRIES = 2
_RETRY_BACKOFF = 0.6  # seconds, multiplied by the attempt number


class PrimError(RuntimeError):
    """Actionable error surfaced to MCP tools (human-readable message)."""


_client: httpx.AsyncClient | None = None


def _build_client(settings: Settings) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=settings.http_timeout_seconds,
        headers={"Accept": "application/json"},
        follow_redirects=True,
    )


def get_client() -> httpx.AsyncClient:
    """Returns the shared HTTP client, creating it on first use."""
    global _client
    if _client is None or _client.is_closed:
        _client = _build_client(get_settings())
    return _client


async def close_client() -> None:
    """Closes the shared client (call this on server shutdown)."""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


def _current_request_headers() -> Mapping[str, str] | None:
    """Returns the HTTP headers of the current MCP request, if available.

    On HTTP transport, the MCP SDK stashes the Starlette request in a
    ``ContextVar``. On stdio transport (or outside a request), there is no
    request: returns None.
    """
    try:
        from mcp.server.lowlevel.server import request_ctx
    except Exception:  # pragma: no cover - SDK without this module
        return None
    try:
        ctx = request_ctx.get()
    except LookupError:
        return None
    request = getattr(ctx, "request", None)
    return getattr(request, "headers", None)


def api_key_from_request(header_names: tuple[str, ...]) -> str | None:
    """Reads a key from the current HTTP request's headers (any service)."""
    headers = _current_request_headers()
    if not headers:
        return None
    for name in header_names:
        value = headers.get(name)
        if value and value.strip():
            return value.strip()
    return None


def _api_key_from_request() -> str | None:
    """Extracts the PRIM key from an HTTP header of the current request (Bearer included)."""
    key = api_key_from_request(API_KEY_HEADERS)
    if key:
        return key
    headers = _current_request_headers()
    auth = headers.get("authorization") if headers else None
    if auth and auth.lower().startswith("bearer "):
        token = auth[len("bearer ") :].strip()
        if token:
            return token
    return None


def resolve_api_key() -> str:
    """PRIM key to use: request header first, then env var fallback.

    Raises ``PrimError`` with a helpful message if no key is available.
    """
    key = _api_key_from_request()
    if not key:
        env_key = get_settings().prim_api_key.strip()
        key = env_key or None
    if not key:
        raise PrimError(
            "No PRIM key was provided. Send your token in the 'X-PRIM-Api-Key' "
            "HTTP header (or 'apikey', or 'Authorization: Bearer <token>'). "
            "Get a free token at https://prim.iledefrance-mobilites.fr."
        )
    return key


def _explain_status(exc: httpx.HTTPStatusError, source: str) -> PrimError:
    status = exc.response.status_code
    if status in (401, 403):
        if "PRIM" in source or "Navitia" in source or "SIRI" in source:
            detail = "Check the PRIM key ('X-PRIM-Api-Key' header or the PRIM_API_KEY variable)."
        else:
            detail = "Check the API key provided for this service."
        return PrimError(f"{source}: authentication refused (HTTP {status}). {detail}")
    if status == 404:
        return PrimError(f"{source}: resource not found (HTTP 404). Check the parameters.")
    if status == 429:
        hint = (
            " On PRIM, you can request a quota increase."
            if "PRIM" in source or "Navitia" in source or "SIRI" in source
            else " Please retry in a moment."
        )
        return PrimError(f"{source}: too many requests (HTTP 429).{hint}")
    if status >= 500:
        return PrimError(f"{source}: the upstream service is unavailable (HTTP {status}).")
    # Other 4xx: try to extract an error message from the body.
    detail = _extract_error_detail(exc.response)
    return PrimError(f"{source}: request rejected (HTTP {status}){f' — {detail}' if detail else ''}.")


def _extract_error_detail(response: httpx.Response) -> str | None:
    try:
        data = response.json()
    except ValueError:
        return None
    if isinstance(data, dict):
        for key in ("message", "error", "description"):
            value = data.get(key)
            if isinstance(value, str) and value:
                return value
    return None


async def _request_json(
    url: str,
    *,
    params: dict[str, Any] | None,
    headers: dict[str, str] | None,
    source: str,
) -> Any:
    client = get_client()
    for attempt in range(_MAX_RETRIES + 1):
        try:
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # 429/503 are often transient (per-IP rate limit): retry.
            if exc.response.status_code in _RETRY_STATUS and attempt < _MAX_RETRIES:
                await asyncio.sleep(_RETRY_BACKOFF * (attempt + 1))
                continue
            raise _explain_status(exc, source) from exc
        except httpx.TimeoutException as exc:
            raise PrimError(f"{source}: request timed out.") from exc
        except httpx.HTTPError as exc:
            raise PrimError(f"{source}: network error ({exc}).") from exc

        try:
            return response.json()
        except ValueError as exc:
            raise PrimError(f"{source}: invalid response (expected JSON).") from exc


async def prim_get(path: str, params: dict[str, Any] | None = None, *, source: str = "PRIM") -> Any:
    """Authenticated GET against the PRIM platform (Navitia or marketplace).

    ``path`` can be an absolute URL or a path relative to the Navitia v2 base.
    The key is resolved per request (client HTTP header, then env var) and
    injected into the ``apikey`` header.
    """
    settings = get_settings()
    api_key = resolve_api_key()

    url = path if path.startswith("http") else f"{settings.prim_navitia_base}/{path.lstrip('/')}"
    return await _request_json(
        url,
        params=params,
        headers={"apikey": api_key},
        source=source,
    )


async def public_get(url: str, params: dict[str, Any] | None = None, *, source: str) -> Any:
    """Unauthenticated GET (used for the national geocoder, no key needed)."""
    return await _request_json(url, params=params, headers=None, source=source)
