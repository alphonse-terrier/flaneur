"""Client HTTP partagé pour les appels à l'API PRIM et au géocodeur BAN.

Un unique ``httpx.AsyncClient`` est réutilisé pour toute la durée de vie du
serveur. Les erreurs réseau et HTTP sont converties en ``PrimError`` avec un
message clair, afin que les outils MCP renvoient une explication exploitable
au lieu d'une exception brute.
"""

from __future__ import annotations

from typing import Any

import httpx

from idfm_mcp.config import Settings, get_settings


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


def _explain_status(exc: httpx.HTTPStatusError, source: str) -> PrimError:
    status = exc.response.status_code
    if status in (401, 403):
        return PrimError(
            f"{source} : authentification refusée (HTTP {status}). "
            "Vérifiez que PRIM_API_KEY est défini et valide."
        )
    if status == 404:
        return PrimError(f"{source} : ressource introuvable (HTTP 404). Vérifiez les paramètres.")
    if status == 429:
        return PrimError(
            f"{source} : quota dépassé (HTTP 429). Réessayez plus tard ou demandez une "
            "augmentation de quota sur PRIM."
        )
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
    try:
        response = await client.get(url, params=params, headers=headers)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
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
    Le header ``apikey`` est injecté automatiquement.
    """
    settings = get_settings()
    if not settings.has_api_key:
        raise PrimError(
            "PRIM_API_KEY n'est pas défini. Créez un jeton sur "
            "https://prim.iledefrance-mobilites.fr et exportez-le dans l'environnement."
        )

    url = path if path.startswith("http") else f"{settings.prim_navitia_base}/{path.lstrip('/')}"
    return await _request_json(
        url,
        params=params,
        headers={"apikey": settings.prim_api_key},
        source=source,
    )


async def public_get(url: str, params: dict[str, Any] | None = None, *, source: str) -> Any:
    """GET non authentifié (utilisé pour le géocodeur BAN, sans clé)."""
    return await _request_json(url, params=params, headers=None, source=source)
