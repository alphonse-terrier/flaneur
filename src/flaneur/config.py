"""Server configuration, read from the environment (or a .env file)."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Flâneur server settings.

    There is no strictly required variable at import time: PRIM_API_KEY and
    OPENWEATHER_API_KEY are optional server-side fallbacks, since each client
    is expected to send its own key via an HTTP header (multi-user model).
    Base URLs default to the real providers and are overridable (useful for
    tests, or if a provider changes its paths).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- PRIM authentication -----------------------------------------------------
    prim_api_key: str = ""

    # --- HTTP server ---------------------------------------------------------------
    host: str = "0.0.0.0"
    port: int = 8000  # Render provides $PORT; overridden in server.main()

    # Allowed hosts (anti DNS-rebinding protection). Comma-separated list.
    # Empty = protection disabled (fine for a public server behind HTTPS).
    # E.g. "flaneur.onrender.com,my-domain.com" to lock it down.
    allowed_hosts: str = ""

    # --- Base URLs -----------------------------------------------------------------
    # Navitia v2 (journeys, places, line_reports, disruptions...) — fr-idf coverage implicit.
    prim_navitia_base: str = "https://prim.iledefrance-mobilites.fr/marketplace/v2/navitia"
    # SIRI Lite & global queries (shared marketplace prefix).
    prim_marketplace_base: str = "https://prim.iledefrance-mobilites.fr/marketplace"
    # National geocoder (French national address database via Géoplateforme), no key.
    geocoder_base: str = "https://data.geopf.fr/geocodage"
    geocoder_fallback_base: str = "https://api-adresse.data.gouv.fr"
    # BRouter cycling router (free, no key) — PRIM doesn't route cycling.
    brouter_base: str = "https://brouter.de/brouter"
    # OpenWeatherMap weather (key required). Each client can send its own key via
    # the 'X-OpenWeather-Api-Key' header; otherwise falls back to OPENWEATHER_API_KEY.
    openweather_base: str = "https://api.openweathermap.org/data/2.5"
    openweather_api_key: str = ""
    # In-memory weather response cache (seconds), to limit upstream calls.
    weather_cache_ttl: int = 600
    # Vélib' Métropole real-time availability (GBFS, free, no key).
    velib_base: str = "https://velib-metropole-opendata.smovengo.cloud/opendata/Velib_Metropole"

    # --- Network ---------------------------------------------------------------
    http_timeout_seconds: float = 15.0

    @property
    def has_api_key(self) -> bool:
        return bool(self.prim_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    """Returns the single, memoized configuration instance."""
    return Settings()
