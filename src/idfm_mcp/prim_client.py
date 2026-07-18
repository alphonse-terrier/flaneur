"""Client HTTP partagé pour les appels à l'API PRIM et au géocodeur BAN.

Un unique ``httpx.AsyncClient`` est réutilisé pour toute la durée de vie du
serveur. La clé PRIM est résolue **par requête** : chaque client envoie la sienne
dans un en-tête HTTP (``X-PRIM-Api-Key``), avec repli sur la variable d'env
``PRIM_API_KEY``. Les erreurs réseau et HTTP sont converties en ``PrimError`` avec
un message clair, afin que les outils MCP renvoient une explication exploitable au
lieu d'une exception brute.
"""

from __future__ import annotations

import asyncio
from typing import Any, Mapping

import httpx

from idfm_mcp.config import Settings, get_settings

# En-têtes HTTP acceptés pour transmettre la clé PRIM par requête (insensibles à la casse).
API_KEY_HEADERS = ("x-prim-api-key", "apikey", "prim-api-key")

# Réessai sur codes transitoires (limite de débit / indisponibilité momentanée).
_RETRY_STATUS = {429, 503}
_MAX_RETRIES = 2
_RETRY_BACKOFF = 0.6  # secondes, multiplié par le numéro de tentative


class PrimError(RuntimeError):
    """Erreur exploitable renvoyée aux outils MCP (message lisible pour l'utilisateur)."""


_client: httpx.AsyncClient | None = None


def _build_client(settings: Settings) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=settings.http_timeout_seconds,
        headers={"Accept": "application/json"},
        follow_redirects=True,
    )


def get_client() -> httpx.AsyncClient:
    """Retourne le client HTTP partagé, en le créant au premier appel."""
    global _client
    if _client is None or _client.is_closed:
        _client = _build_client(get_settings())
    return _client


async def close_client() -> None:
    """Ferme le client partagé (à appeler à l'arrêt du serveur)."""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


def _current_request_headers() -> Mapping[str, str] | None:
    """Retourne les en-têtes HTTP de la requête MCP en cours, si disponible.

    En transport HTTP, le SDK MCP place la requête Starlette dans une ``ContextVar``.
    En transport stdio (ou hors requête), il n'y a pas de requête : on renvoie None.
    """
    try:
        from mcp.server.lowlevel.server import request_ctx
    except Exception:  # pragma: no cover - SDK sans ce module
        return None
    try:
        ctx = request_ctx.get()
    except LookupError:
        return None
    request = getattr(ctx, "request", None)
    return getattr(request, "headers", None)


def _api_key_from_request() -> str | None:
    """Extrait la clé PRIM d'un en-tête HTTP de la requête courante (Bearer inclus)."""
    headers = _current_request_headers()
    if not headers:
        return None
    for name in API_KEY_HEADERS:
        value = headers.get(name)
        if value and value.strip():
            return value.strip()
    auth = headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        token = auth[len("bearer ") :].strip()
        if token:
            return token
    return None


def resolve_api_key() -> str:
    """Clé PRIM à utiliser : en-tête de la requête en priorité, sinon variable d'env.

    Lève ``PrimError`` avec un message d'aide si aucune clé n'est disponible.
    """
    key = _api_key_from_request()
    if not key:
        env_key = get_settings().prim_api_key.strip()
        key = env_key or None
    if not key:
        raise PrimError(
            "Aucune clé PRIM fournie. Envoyez votre jeton dans l'en-tête HTTP "
            "'X-PRIM-Api-Key' (ou 'apikey', ou 'Authorization: Bearer <jeton>'). "
            "Créez un jeton gratuit sur https://prim.iledefrance-mobilites.fr."
        )
    return key


def _explain_status(exc: httpx.HTTPStatusError, source: str) -> PrimError:
    status = exc.response.status_code
    if status in (401, 403):
        return PrimError(
            f"{source} : authentification refusée (HTTP {status}). "
            "Vérifiez la clé PRIM envoyée dans l'en-tête 'X-PRIM-Api-Key' "
            "(ou la variable d'environnement PRIM_API_KEY)."
        )
    if status == 404:
        return PrimError(f"{source} : ressource introuvable (HTTP 404). Vérifiez les paramètres.")
    if status == 429:
        hint = (
            " Sur PRIM, vous pouvez demander une augmentation de quota."
            if "PRIM" in source or "Navitia" in source or "SIRI" in source
            else " Réessayez dans quelques instants."
        )
        return PrimError(f"{source} : trop de requêtes (HTTP 429).{hint}")
    if status >= 500:
        return PrimError(f"{source} : le service distant est indisponible (HTTP {status}).")
    # Autres 4xx : on tente d'extraire un message d'erreur du corps.
    detail = _extract_error_detail(exc.response)
    return PrimError(f"{source} : requête refusée (HTTP {status}){f' — {detail}' if detail else ''}.")


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
            # 429/503 sont souvent transitoires (limite par IP) : on réessaie.
            if exc.response.status_code in _RETRY_STATUS and attempt < _MAX_RETRIES:
                await asyncio.sleep(_RETRY_BACKOFF * (attempt + 1))
                continue
            raise _explain_status(exc, source) from exc
        except httpx.TimeoutException as exc:
            raise PrimError(f"{source} : délai d'attente dépassé.") from exc
        except httpx.HTTPError as exc:
            raise PrimError(f"{source} : erreur réseau ({exc}).") from exc

        try:
            return response.json()
        except ValueError as exc:
            raise PrimError(f"{source} : réponse invalide (JSON attendu).") from exc


async def prim_get(path: str, params: dict[str, Any] | None = None, *, source: str = "PRIM") -> Any:
    """GET authentifié sur la plateforme PRIM (Navitia ou marketplace).

    ``path`` peut être une URL absolue ou un chemin relatif à la base Navitia v2.
    La clé est résolue par requête (en-tête HTTP du client, sinon variable d'env)
    et injectée dans le header ``apikey``.
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
    """GET non authentifié (utilisé pour le géocodeur BAN, sans clé)."""
    return await _request_json(url, params=params, headers=None, source=source)
