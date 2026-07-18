"""Configuration du serveur, lue depuis l'environnement (ou un fichier .env)."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Paramètres du serveur IDFM MCP.

    La seule variable obligatoire est ``PRIM_API_KEY``. Les URLs de base ont des
    valeurs par défaut correspondant à la plateforme PRIM et sont surchargeables
    (utile pour les tests ou si IDFM fait évoluer ses chemins).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Authentification PRIM -------------------------------------------------
    prim_api_key: str = ""

    # --- Serveur HTTP ----------------------------------------------------------
    host: str = "0.0.0.0"
    port: int = 8000  # Render fournit $PORT ; surchargé dans server.main()

    # Hosts autorisés (protection anti DNS-rebinding). Liste séparée par des virgules.
    # Vide = protection désactivée (adapté à un serveur public derrière HTTPS).
    # Ex. "idfm-mcp.onrender.com,mon-domaine.fr" pour verrouiller.
    allowed_hosts: str = ""

    # --- URLs de base ----------------------------------------------------------
    # Navitia v2 (journeys, places, line_reports, disruptions...) — coverage fr-idf implicite.
    prim_navitia_base: str = "https://prim.iledefrance-mobilites.fr/marketplace/v2/navitia"
    # SIRI Lite & requêtes globales (préfixe marketplace commun).
    prim_marketplace_base: str = "https://prim.iledefrance-mobilites.fr/marketplace"
    # Géocodeur national (Base Adresse Nationale via Géoplateforme), sans clé.
    geocoder_base: str = "https://data.geopf.fr/geocodage"
    geocoder_fallback_base: str = "https://api-adresse.data.gouv.fr"
    # Routeur cyclable BRouter (gratuit, sans clé) — PRIM ne route pas le vélo.
    brouter_base: str = "https://brouter.de/brouter"
    # Météo Open-Meteo. Sans clé = endpoint public (quota par IP, partagée sur Render).
    openmeteo_base: str = "https://api.open-meteo.com/v1/forecast"
    # Avec une clé (OPENMETEO_API_KEY), on bascule sur l'endpoint client dédié
    # (quota propre, plus de problème d'IP partagée).
    openmeteo_customer_base: str = "https://customer-api.open-meteo.com/v1/forecast"
    openmeteo_api_key: str = ""
    # Cache mémoire des réponses météo (secondes) pour limiter les appels.
    weather_cache_ttl: int = 600

    # --- Réseau ----------------------------------------------------------------
    http_timeout_seconds: float = 15.0

    @property
    def has_api_key(self) -> bool:
        return bool(self.prim_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    """Retourne l'instance unique de configuration (mémoïsée)."""
    return Settings()
