# Flâneur

An **MCP** (Model Context Protocol) server for **Île-de-France mobility**: it plans
public-transit **journeys** with real-time **roadworks & incident** impact, and rounds
it out with real-time next departures, **cycling routes**, and **weather** — built on
Île-de-France Mobilités' **PRIM API**.

Given a start and end address, the server geocodes the places, computes the best
real-time journeys, and surfaces the disruptions affecting each leg of the trip.

## Features (MCP tools)

| Tool | Description |
|---|---|
| `geocode_address(query)` | Converts an address or place name into coordinates. |
| `plan_journey(origin, destination, when?, arrive_by?, max_journeys?)` | Full real-time journey(s), with disruptions attached to each leg. |
| `line_traffic(line?)` | Traffic info (roadworks/incidents): network-wide or for a given line. |
| `next_departures(stop, limit?)` | Real-time next departures at a stop. |
| `bike_route(origin, destination, profile?)` | Cycling route (duration + distance) via BRouter. |
| `weather(location, days?)` | Current weather + daily forecast for an address (OpenWeatherMap). |

`origin` / `destination` accept an **address** ("29 rue de Rivoli, Paris"), a
**stop name** ("Châtelet"), or **coordinates** in `longitude;latitude` format.

## Architecture

```
src/flaneur/
├── config.py        # Configuration (PRIM_API_KEY, URLs, timeouts)
├── prim_client.py   # Shared httpx client (apikey header, error handling)
├── geocoding.py      # Address → coordinates (national geocoder + Navitia /places)
├── journeys.py       # /journeys + disruption-enriched summary
├── disruptions.py    # Traffic info (disruptions_bulk / line_reports)
├── departures.py     # Next departures (SIRI stop-monitoring)
├── bike.py           # Cycling route (BRouter)
├── weather.py        # Weather (OpenWeatherMap)
├── models.py         # Pydantic models for tool outputs
└── server.py         # FastMCP server + tool registration
```

Data sources:
- **Navitia** via PRIM (`/journeys`, `/places`, `/line_reports`, `disruptions_bulk`) —
  `apikey` header.
- **SIRI Lite** via PRIM (`stop-monitoring`) — `apikey` header.
- **National geocoder** (French national address database via Géoplateforme) — no key.
- **BRouter** (open-source cycling router) for cycling — no key. PRIM can't compute
  cycling routes (its Navitia coverage only routes walking).
- **OpenWeatherMap** for weather (responses cached ~10 min). Key required: per-request
  `X-OpenWeather-Api-Key` header, or `OPENWEATHER_API_KEY` fallback.

## Requirements

- Python ≥ 3.10.
- A free **PRIM API key**: create an account at
  <https://prim.iledefrance-mobilites.fr>, then generate a token under
  *My account → Authentication tokens*.

## Authentication — one key per user

The server is **multi-user**: each client supplies **its own PRIM key**, sent per
request in an **HTTP header**. The key never flows through the LLM's conversation and
is never stored by the server.

Accepted headers (in priority order):

| Header | Example |
|---|---|
| `X-PRIM-Api-Key` | `X-PRIM-Api-Key: <your_token>` |
| `apikey` | `apikey: <your_token>` |
| `Authorization` (Bearer) | `Authorization: Bearer <your_token>` |

Fallback: if no header is provided, the server uses the `PRIM_API_KEY` environment
variable if set (handy locally, or as a default key). On a shared public deployment,
leave `PRIM_API_KEY` empty to require every user to bring their own key.

The `weather` tool follows the same model with an `X-OpenWeather-Api-Key` header
(fallback: `OPENWEATHER_API_KEY`).

> ⚠️ Always deploy behind **HTTPS** (Render does by default) so the key is encrypted
> in transit.

## Local setup & run

```bash
# 1. Dependencies (with uv, recommended)
uv sync
# ... or with pip
pip install -e ".[dev]"

# 2. Configuration
cp .env.example .env
# edit .env and fill in PRIM_API_KEY (and optionally OPENWEATHER_API_KEY)

# 3. Run (HTTP transport, listens on http://localhost:8000/mcp)
python -m flaneur.server
```

### Testing with the MCP inspector

```bash
# Web UI to call tools manually
uv run mcp dev src/flaneur/server.py
# or
npx @modelcontextprotocol/inspector
```

Example calls:
- `geocode_address("29 rue de Rivoli, Paris")`
- `plan_journey("Eiffel Tower, Paris", "Château de Vincennes")`
- `line_traffic("14")` then `line_traffic()`
- `next_departures("Châtelet")`
- `bike_route("Bastille, Paris", "La Défense")` → ~12 km, ~37 min by bike
- `weather("Eiffel Tower, Paris")` → current conditions + forecast

## Deploying on Render

The repo includes a `render.yaml` blueprint. On Render:

1. **New → Blueprint**, point it at this repo.
2. Render creates a Python web service that runs `uv run flaneur`
   (listens on `0.0.0.0:$PORT`).
3. Leave `PRIM_API_KEY` (and `OPENWEATHER_API_KEY`) empty for a multi-user server
   (each client brings its own key), or set a secret for a default fallback key.
4. Once deployed, the MCP endpoint is exposed at `https://<app>.onrender.com/mcp`.

### Connecting an MCP client

Each user configures the remote server with **their own PRIM key** (and, if using
`weather`, their own OpenWeatherMap key) in the headers:

```json
{
  "mcpServers": {
    "flaneur": {
      "url": "https://<app>.onrender.com/mcp",
      "headers": {
        "X-PRIM-Api-Key": "YOUR_PRIM_TOKEN",
        "X-OpenWeather-Api-Key": "YOUR_OPENWEATHER_KEY"
      }
    }
  }
}
```

## Tests

```bash
uv run pytest        # unit tests (parsing, no real network calls)
```

## License

MIT.
