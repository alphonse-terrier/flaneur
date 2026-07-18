"""Serveur MCP IDFM : itinéraires, perturbations et prochains passages en Île-de-France.

Expose cinq outils :
- ``geocode_address`` : adresse/lieu → coordonnées ;
- ``plan_journey`` : itinéraire complet (transports) avec perturbations temps réel ;
- ``line_traffic`` : info trafic (travaux/incidents) globale ou par ligne ;
- ``next_departures`` : prochains passages temps réel à un arrêt ;
- ``bike_route`` : itinéraire à vélo (via BRouter — PRIM ne route pas le vélo).

Les quatre premiers s'appuient sur l'API PRIM d'Île-de-France Mobilités.
"""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

from idfm_mcp.bike import bike_route as _bike_route
from idfm_mcp.config import get_settings
from idfm_mcp.departures import next_departures as _next_departures
from idfm_mcp.disruptions import global_disruptions, line_disruptions
from idfm_mcp.geocoding import resolve_place
from idfm_mcp.journeys import plan_journey as _plan_journey
from idfm_mcp.models import (
    BikeRoute,
    DeparturesResult,
    Disruption,
    GeoLocation,
    JourneyResult,
)


def _transport_security() -> TransportSecuritySettings:
    """Sécurité du transport HTTP (protection anti DNS-rebinding).

    Passée explicitement pour neutraliser la valeur par défaut du SDK, qui
    n'autorise que localhost et renvoie 421 sur un host distant (ex. Render).
    Vide = protection désactivée (serveur public derrière HTTPS) ; sinon on
    verrouille sur les hosts déclarés dans ALLOWED_HOSTS.
    """
    hosts = [h.strip() for h in get_settings().allowed_hosts.split(",") if h.strip()]
    if hosts:
        return TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=hosts + ["127.0.0.1:*", "localhost:*"],
        )
    return TransportSecuritySettings(enable_dns_rebinding_protection=False)


mcp = FastMCP(
    "idfm-mcp",
    instructions=(
        "Serveur d'itinéraires en transports en commun pour l'Île-de-France (Paris et "
        "sa région), basé sur l'API PRIM d'Île-de-France Mobilités. Utilisez "
        "`plan_journey` pour calculer un trajet en transports en commun entre deux "
        "adresses avec l'impact des travaux et incidents, `line_traffic` pour l'info "
        "trafic d'une ligne, `next_departures` pour les prochains passages à un arrêt, "
        "et `bike_route` pour un itinéraire à vélo (durée et distance)."
    ),
    transport_security=_transport_security(),
)


@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(request: Request) -> JSONResponse:
    """Point de santé public pour Render (l'endpoint MCP /mcp répond 406 à un GET nu)."""
    return JSONResponse({"status": "ok", "service": "idfm-mcp"})


@mcp.tool()
async def geocode_address(query: str) -> GeoLocation:
    """Convertit une adresse ou un nom de lieu en coordonnées géographiques.

    Args:
        query: Adresse postale, nom d'arrêt/gare, ou coordonnées `longitude;latitude`.

    Returns:
        Le lieu résolu avec ses coordonnées et son libellé normalisé.
    """
    return await resolve_place(query)


@mcp.tool()
async def plan_journey(
    origin: str,
    destination: str,
    when: str | None = None,
    arrive_by: bool = False,
    max_journeys: int = 3,
) -> JourneyResult:
    """Calcule le(s) meilleur(s) itinéraire(s) en transports en commun entre deux lieux.

    L'itinéraire est calculé en temps réel : chaque étape perturbée par des travaux ou
    un incident porte la liste des perturbations correspondantes, et chaque trajet
    indique son statut global (retards importants, interruption, etc.).

    Args:
        origin: Lieu de départ — adresse, nom d'arrêt, ou coordonnées `lon;lat`.
        destination: Lieu d'arrivée — même formats que `origin`.
        when: Date/heure au format ISO 8601 (ex. `2026-07-18T08:30:00`). Défaut : maintenant.
        arrive_by: Si vrai, `when` est l'heure d'arrivée souhaitée (au lieu du départ).
        max_journeys: Nombre maximum d'itinéraires proposés (1 à 5).

    Returns:
        Les lieux résolus et la liste des itinéraires détaillés avec perturbations.
    """
    return await _plan_journey(
        origin=origin,
        destination=destination,
        when=when,
        arrive_by=arrive_by,
        max_journeys=max_journeys,
    )


@mcp.tool()
async def line_traffic(line: str | None = None) -> list[Disruption]:
    """Retourne l'info trafic : travaux, incidents et perturbations en cours et à venir.

    Args:
        line: Nom/numéro de ligne (ex. `6`, `RER A`, `T3a`) ou id Navitia
            (`line:IDFM:...`). Si omis, retourne toutes les perturbations du réseau.

    Returns:
        La liste des perturbations (cause, effet, période, message, objets impactés).
    """
    if line:
        return await line_disruptions(line)
    return await global_disruptions()


@mcp.tool()
async def next_departures(stop: str, limit: int = 10) -> DeparturesResult:
    """Retourne les prochains passages temps réel à un arrêt.

    Args:
        stop: Nom d'arrêt/gare (ex. `Châtelet`) ou référence SIRI `STIF:StopArea:SP:...`.
        limit: Nombre maximum de passages à retourner.

    Returns:
        L'arrêt résolu et la liste des prochains passages (ligne, destination, heure).
    """
    return await _next_departures(stop, limit=limit)


@mcp.tool()
async def bike_route(
    origin: str, destination: str, profile: str = "trekking"
) -> BikeRoute:
    """Calcule un itinéraire à vélo entre deux lieux (durée et distance).

    Complète `plan_journey` : PRIM ne calcule pas d'itinéraire vélo, donc cet outil
    s'appuie sur le routeur cyclable BRouter. Utilisez-le pour toute question de type
    « combien de temps à vélo de A à B ? ».

    Args:
        origin: Lieu de départ — adresse, nom d'arrêt, ou coordonnées `lon;lat`.
        destination: Lieu d'arrivée — même formats que `origin`.
        profile: Profil vélo — `trekking` (équilibré, défaut), `fastbike` (plus rapide),
            `shortest` (plus court).

    Returns:
        Les lieux résolus, la distance (km) et la durée estimée à vélo (minutes).
    """
    return await _bike_route(origin, destination, profile=profile)


def main() -> None:
    """Point d'entrée : lance le serveur en transport HTTP (streamable-http).

    Le port est lu depuis $PORT (fourni par Render) avec repli sur la configuration.
    """
    settings = get_settings()
    mcp.settings.host = settings.host
    mcp.settings.port = int(os.environ.get("PORT", settings.port))
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
