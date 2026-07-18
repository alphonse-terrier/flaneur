"""Modèles Pydantic des sorties d'outils — JSON compact et stable pour le LLM."""

from __future__ import annotations

from pydantic import BaseModel, Field


class GeoLocation(BaseModel):
    """Résultat de géocodage d'une adresse ou d'un lieu."""

    label: str = Field(description="Libellé normalisé du lieu.")
    longitude: float
    latitude: float
    city: str | None = None
    postcode: str | None = None
    kind: str | None = Field(
        default=None,
        description="Type de lieu (housenumber, street, stop_area, poi...).",
    )

    @property
    def lonlat(self) -> str:
        """Coordonnées au format `longitude;latitude` attendu par Navitia."""
        return f"{self.longitude};{self.latitude}"


class Disruption(BaseModel):
    """Perturbation (travaux, incident, retard) affectant une ligne ou un arrêt."""

    id: str | None = None
    cause: str | None = Field(default=None, description="Cause : travaux, incident, etc.")
    effect: str | None = Field(
        default=None,
        description="Effet : NO_SERVICE, SIGNIFICANT_DELAYS, DETOUR, MODIFIED_SERVICE...",
    )
    severity: str | None = None
    status: str | None = Field(default=None, description="active | future | past")
    begin: str | None = Field(default=None, description="Début d'application (ISO 8601).")
    end: str | None = Field(default=None, description="Fin d'application (ISO 8601).")
    message: str | None = Field(default=None, description="Message voyageur (texte nettoyé).")
    impacted_objects: list[str] = Field(
        default_factory=list,
        description="Lignes / arrêts impactés (libellés).",
    )


class JourneySection(BaseModel):
    """Une étape d'un itinéraire (marche, transport en commun, correspondance, attente)."""

    mode: str = Field(description="Type : walking, public_transport, transfer, waiting, crow_fly.")
    label: str = Field(description="Description lisible de l'étape.")
    line: str | None = Field(default=None, description="Numéro/nom de ligne (si transport).")
    network: str | None = None
    direction: str | None = None
    from_name: str | None = None
    to_name: str | None = None
    departure: str | None = Field(default=None, description="Heure de départ (ISO 8601).")
    arrival: str | None = Field(default=None, description="Heure d'arrivée (ISO 8601).")
    duration_minutes: int = 0
    disruptions: list[Disruption] = Field(
        default_factory=list,
        description="Perturbations rattachées à cette étape.",
    )


class Journey(BaseModel):
    """Un itinéraire complet proposé."""

    type: str | None = Field(default=None, description="best, fastest, comfort, less_walking...")
    status: str | None = Field(
        default=None,
        description="Statut temps réel global : '' si nominal, sinon NO_SERVICE, "
        "SIGNIFICANT_DELAYS, etc.",
    )
    departure: str | None = Field(default=None, description="Heure de départ (ISO 8601).")
    arrival: str | None = Field(default=None, description="Heure d'arrivée (ISO 8601).")
    duration_minutes: int = 0
    nb_transfers: int = 0
    walking_minutes: int = 0
    sections: list[JourneySection] = Field(default_factory=list)
    has_disruptions: bool = Field(
        default=False,
        description="True si au moins une étape est perturbée.",
    )


class JourneyResult(BaseModel):
    """Réponse de l'outil plan_journey."""

    origin: GeoLocation
    destination: GeoLocation
    journeys: list[Journey] = Field(default_factory=list)
    note: str | None = None


class BikeRoute(BaseModel):
    """Itinéraire à vélo entre deux lieux (routage BRouter, PRIM ne route pas le vélo)."""

    origin: GeoLocation
    destination: GeoLocation
    profile: str = Field(description="Profil vélo utilisé (trekking, fastbike, shortest).")
    distance_km: float
    duration_minutes: int = Field(
        description="Durée estimée à vélo (allure du profil, ~18 km/h en trekking)."
    )
    note: str | None = None


class Departure(BaseModel):
    """Prochain passage à un arrêt (temps réel)."""

    line: str | None = None
    destination: str | None = None
    expected: str | None = Field(default=None, description="Heure attendue (temps réel, ISO 8601).")
    aimed: str | None = Field(default=None, description="Heure théorique (ISO 8601).")
    status: str | None = Field(default=None, description="onTime, delayed, cancelled...")


class DeparturesResult(BaseModel):
    """Réponse de l'outil next_departures."""

    stop_label: str
    stop_id: str
    departures: list[Departure] = Field(default_factory=list)
    note: str | None = None
