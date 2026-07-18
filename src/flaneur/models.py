"""Pydantic models for tool outputs — compact, stable JSON for the LLM."""

from __future__ import annotations

from pydantic import BaseModel, Field


class GeoLocation(BaseModel):
    """Geocoding result for an address or place."""

    label: str = Field(description="Normalized label of the place.")
    longitude: float
    latitude: float
    city: str | None = None
    postcode: str | None = None
    kind: str | None = Field(
        default=None,
        description="Place type (housenumber, street, stop_area, poi...).",
    )

    @property
    def lonlat(self) -> str:
        """Coordinates in the `longitude;latitude` format expected by Navitia."""
        return f"{self.longitude};{self.latitude}"


class Disruption(BaseModel):
    """Disruption (roadworks, incident, delay) affecting a line or a stop."""

    id: str | None = None
    cause: str | None = Field(default=None, description="Cause: roadworks, incident, etc.")
    effect: str | None = Field(
        default=None,
        description="Effect: NO_SERVICE, SIGNIFICANT_DELAYS, DETOUR, MODIFIED_SERVICE...",
    )
    severity: str | None = None
    status: str | None = Field(default=None, description="active | future | past")
    begin: str | None = Field(default=None, description="Start of effect (ISO 8601).")
    end: str | None = Field(default=None, description="End of effect (ISO 8601).")
    message: str | None = Field(default=None, description="Rider-facing message (cleaned text).")
    impacted_objects: list[str] = Field(
        default_factory=list,
        description="Impacted lines / stops (labels).",
    )


class JourneySection(BaseModel):
    """One leg of a journey (walking, public transport, transfer, waiting)."""

    mode: str = Field(description="Type: walking, public_transport, transfer, waiting, crow_fly.")
    label: str = Field(description="Human-readable description of the leg.")
    line: str | None = Field(default=None, description="Line number/name (if public transport).")
    network: str | None = None
    direction: str | None = None
    from_name: str | None = None
    to_name: str | None = None
    departure: str | None = Field(default=None, description="Departure time (ISO 8601).")
    arrival: str | None = Field(default=None, description="Arrival time (ISO 8601).")
    duration_minutes: int = 0
    disruptions: list[Disruption] = Field(
        default_factory=list,
        description="Disruptions attached to this leg.",
    )


class Journey(BaseModel):
    """A complete proposed journey."""

    type: str | None = Field(default=None, description="best, fastest, comfort, less_walking...")
    status: str | None = Field(
        default=None,
        description="Overall real-time status: '' if nominal, otherwise NO_SERVICE, "
        "SIGNIFICANT_DELAYS, etc.",
    )
    departure: str | None = Field(default=None, description="Departure time (ISO 8601).")
    arrival: str | None = Field(default=None, description="Arrival time (ISO 8601).")
    duration_minutes: int = 0
    nb_transfers: int = 0
    walking_minutes: int = 0
    sections: list[JourneySection] = Field(default_factory=list)
    has_disruptions: bool = Field(
        default=False,
        description="True if at least one leg is disrupted.",
    )


class JourneyResult(BaseModel):
    """Response of the plan_journey tool."""

    origin: GeoLocation
    destination: GeoLocation
    journeys: list[Journey] = Field(default_factory=list)
    note: str | None = None


class BikeRoute(BaseModel):
    """Cycling route between two places (BRouter routing; PRIM doesn't route cycling)."""

    origin: GeoLocation
    destination: GeoLocation
    profile: str = Field(description="Cycling profile used (trekking, fastbike, shortest).")
    distance_km: float
    duration_minutes: int = Field(
        description="Estimated cycling duration (profile pace, ~18 km/h for trekking)."
    )
    note: str | None = None


class WeatherCurrent(BaseModel):
    """Current weather conditions at a place."""

    time: str | None = Field(default=None, description="Timestamp of the reading (ISO 8601).")
    condition: str | None = Field(default=None, description="Description (e.g. \"Partly cloudy\").")
    weather_code: int | None = Field(default=None, description="OpenWeatherMap condition code.")
    temperature_c: float | None = None
    apparent_temperature_c: float | None = Field(
        default=None, description="Feels-like temperature (°C)."
    )
    precipitation_mm: float | None = None
    wind_speed_kmh: float | None = None
    humidity_pct: float | None = None


class WeatherDay(BaseModel):
    """Daily weather forecast."""

    date: str | None = None
    condition: str | None = None
    weather_code: int | None = None
    temp_min_c: float | None = None
    temp_max_c: float | None = None
    precipitation_mm: float | None = Field(default=None, description="Total precipitation (mm).")
    precipitation_probability_pct: float | None = None


class WeatherResult(BaseModel):
    """Response of the weather tool: current conditions + daily forecast."""

    location: GeoLocation
    current: WeatherCurrent | None = None
    daily: list[WeatherDay] = Field(default_factory=list)


class Departure(BaseModel):
    """Next real-time departure at a stop."""

    line: str | None = None
    destination: str | None = None
    expected: str | None = Field(default=None, description="Expected time (real-time, ISO 8601).")
    aimed: str | None = Field(default=None, description="Scheduled time (ISO 8601).")
    status: str | None = Field(default=None, description="onTime, delayed, cancelled...")


class DeparturesResult(BaseModel):
    """Response of the next_departures tool."""

    stop_label: str
    stop_id: str
    departures: list[Departure] = Field(default_factory=list)
    note: str | None = None
