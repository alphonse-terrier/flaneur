"""Serveur MCP IDFM : itinéraires, perturbations et prochains passages en Île-de-France.

Expose quatre outils construits sur l'API PRIM d'Île-de-France Mobilités :
- ``geocode_address`` : adresse/lieu → coordonnées ;
- ``plan_journey`` : itinéraire complet avec perturbations temps réel ;
- ``line_traffic`` : info trafic (travaux/incidents) globale ou par ligne ;
- ``next_departures`` : prochains passages temps réel à un arrêt.
"""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

from idfm_mcp.config import get_settings
from idfm_mcp.departures import next_departures as _next_departures
from idfm_mcp.disruptions import global_disruptions, line_disruptions
from idfm_mcp.geocoding import resolve_place
from idfm_mcp.journeys import plan_journey as _plan_journey
from idfm_mcp.models import (
    DeparturesResult,
    Disruption,
    GeoLocation,
    JourneyResult,
)

mcp = FastMCP(
    "idfm-mcp",
    instructions=(
        "Serveur d'itinéraires en transports en commun pour l'Île-de-France (Paris et "
        "sa région), basé sur l'API PRIM d'Île-de-France Mobilités. Utilisez "
        "`plan_journey` pour calculer un trajet entre deux adresses avec l'impact des "
        "travaux et incidents, `line_traffic` pour l'info trafic d'une ligne, et "
        "`next_departures` pour les prochains passages à un arrêt."
    ),
)


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
