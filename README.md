# 🚶 Flâneur — your Paris mobility copilot

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](#license)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![MCP](https://img.shields.io/badge/protocol-MCP-6E56CF)
![Hackathon](https://img.shields.io/badge/Mistral-Vibe%20hackathon-FF7000)

> Built for the **Mistral "Vibe" hackathon.** · 🌐 **Live:** [`idfm-mcp.onrender.com/mcp`](https://idfm-mcp.onrender.com/mcp) · [health](https://idfm-mcp.onrender.com/healthz)

Flâneur turns any AI assistant into a **mobility copilot for Île-de-France**. Give it
two addresses and it plans the best public-transit route **in real time** — folding in
roadworks and incidents — then rounds it out with cycling routes, next departures, and
the weather. So your assistant can answer the question that actually matters:

> *"What's the best way to get there, and will I actually arrive on time?"* — not just *"what's the timetable?"*

It ships as **two complementary pieces**:

| Piece | What it is | Where |
|---|---|---|
| 🔌 **MCP server** | The engine. 6 tools any MCP client can call (Mistral Vibe, Claude, …). Multi-user, deployed, HTTPS. | [`src/flaneur/`](src/flaneur/) |
| 🧠 **Agent skill** | The brain. Orchestrates those tools into a single *"get me there on time"* workflow with Google Calendar. | [`skills/itinerary/`](skills/itinerary/SKILL.MD) |

---

## ✨ What makes it interesting

- **Real-time, not just timetables.** Every leg of a journey carries the roadworks /
  incidents affecting it, and each route reports its live status (`NO_SERVICE`,
  `SIGNIFICANT_DELAYS`, …) — pulled from IDFM's PRIM API.
- **Calendar-native.** Connect the **Google Calendar connector in Mistral Vibe** and
  Flâneur plans around your *actual* day: it reads your next meeting's address and time,
  tells you exactly when to leave, and can plan every journey *between* consecutive
  meetings — flagging any two that are too close together to travel between. No
  copy-pasting addresses.
- **Weather-aware mode choice.** It won't send you cycling into the rain. Flâneur
  checks the forecast *along your route*, and in `auto` mode switches you off the bike
  when the weather (or a disruption) turns against it — *"leave at 8:10 by metro:
  it'll be pouring by 8:30, and line 8 is delayed anyway."* One recommendation from
  transit + cycling + weather + disruptions, not four tabs to reconcile yourself.
- **Bring-your-own-key, multi-user.** Each user passes their own API key per request in
  an HTTP header; nothing is stored, so one deployment safely serves everyone.
- **Proactive, not just reactive.** Wire it to a **scheduled task** for a morning
  briefing and live disruption alerts — see [Use cases](#-use-cases).

---

## 🎯 Use cases

### ⭐ Morning briefing & disruption alerts (Mistral scheduled task)

The headline use case. Connect Flâneur to **Mistral Vibe**, then create a
**Scheduled Task** so your assistant does the thinking *before you wake up*:

> *"Every weekday at 7:30, using Flâneur: compute the best departure time from
> `24 Rue Traversière, Paris` to `2 Rue des Mathurins, Paris` to arrive by 9:00.
> If my line has a disruption or it's going to rain, tell me — and suggest the bike
> or an alternate route. Otherwise just send the departure time."*

Each morning you get a single, actionable message:

> 🚇 *Leave at **8:14**. Line 8 has significant delays this morning — take the bus 87
> instead (arrive 8:56). ☔ Light rain expected, bring a jacket.*

The same pattern powers **live alerts** ("ping me if my usual line goes down before
6pm") and **evening planning** ("how do I get home after the concert, and is it warm
enough to walk?").

### Other things it unlocks

- **Bike vs metro, decided for you** — compares both and factors in the weather.
- **"Am I on time?" across a busy day** — the skill scans your calendar and plans the
  journeys *between* meetings, flagging any two that are too close to travel between.
- **Auto-scheduled commutes** — detect location changes between calendar events and
  drop the travel blocks straight into Google Calendar.
- **Arrive-by planning for any mode** — "I want to bike and arrive by 14:00" returns
  the exact departure time, buffer included.

> 🔗 **Calendar-aware answers:** enable the **Google Calendar connector in Mistral
> Vibe** to unlock everything above that reads your schedule — "when do I leave for my
> next meeting?", inter-meeting journeys, and conflict warnings. Flâneur combines the
> connector (your agenda) with its own tools (routing, disruptions, weather).

> 💡 **Tip — save your defaults in Mistral Libraries once.** Flâneur gets far more
> useful when it knows your **home address**, your **main work address**, and your
> **preferred transport mode** (e.g. "bike if it's under 30 min, otherwise metro").
> Add these to a **Library in Mistral Vibe** so it reuses them automatically —
> your morning briefing then becomes a one-liner (*"when should I leave for work?"*)
> with no addresses to retype. The `flaneur-itinerary` skill reads exactly these
> fields (`user_home`, `user_work`, preferred mode) when planning.

---

## 🔌 The MCP server

Six tools, callable from any MCP client:

| Tool | Description |
|---|---|
| `geocode_address(query)` | Address or place name → coordinates. |
| `plan_journey(origin, destination, when?, arrive_by?, max_journeys?)` | Best real-time transit journey(s), with disruptions attached to each leg. |
| `line_traffic(line?)` | Traffic info (roadworks/incidents): network-wide or per line. |
| `next_departures(stop, limit?)` | Real-time next departures at a stop. |
| `bike_route(origin, destination, profile?)` | Cycling route (duration + distance), traffic-light adjusted. |
| `weather(location, days?)` | Current weather + daily forecast for an address. |

`origin` / `destination` accept an **address** ("29 rue de Rivoli, Paris"), a
**stop name** ("Châtelet"), or **coordinates** (`longitude;latitude`).

**Data sources:** [PRIM](https://prim.iledefrance-mobilites.fr) (IDFM — Navitia journeys
+ SIRI real-time), the French national geocoder (Géoplateforme), BRouter (cycling),
and OpenWeatherMap (weather).

## 🧠 The skill: `flaneur-itinerary`

The MCP tools each answer one question; the skill
([`skills/itinerary/SKILL.MD`](skills/itinerary/SKILL.MD)) turns them into a decision:

- Picks the mode (`public_transport` / `bike` / `walk` / `auto`) — for `auto`, bike on
  short trips when weather allows, else transit.
- Computes the **recommended departure time** to hit a target arrival, with a
  configurable buffer, **for every mode** (bike/walk departure is back-computed from
  the target arrival).
- Folds in disruptions, checks weather along cycling/walking routes, and cross-
  references **Google Calendar** for nearby appointments and journey conflicts.
- Scans a date range to auto-plan **inter-meeting journeys**, flagging any pair of
  events too close together to travel between.

It consumes this server's tools plus a connected Google Calendar MCP. On **Mistral
Vibe**, the same logic is expressed directly as a scheduled-task prompt (see
[Use cases](#-use-cases)); in **Claude Code / agents**, load the skill file.

---

## 🚀 Try it

> **Live endpoint:** `https://idfm-mcp.onrender.com/mcp` — health check:
> [`/healthz`](https://idfm-mcp.onrender.com/healthz)

**Connect the hosted server to an MCP client** (Mistral Vibe, Claude, …) — point it at
the live `/mcp` endpoint and pass your keys as headers:

```json
{
  "mcpServers": {
    "flaneur": {
      "url": "https://idfm-mcp.onrender.com/mcp",
      "headers": {
        "X-PRIM-Api-Key": "YOUR_PRIM_TOKEN",
        "X-OpenWeather-Api-Key": "YOUR_OPENWEATHER_KEY"
      }
    }
  }
}
```

> ℹ️ It's a free Render instance, so the very first call after a quiet spell may take
> ~30-60 s to wake up, then it's snappy.

Then ask: *"Best way from the Eiffel Tower to Château de Vincennes right now?"* or
*"How long to bike from Bastille to La Défense, and what's the weather?"*

**Or run it locally:**

```bash
uv sync                 # install deps
cp .env.example .env    # add PRIM_API_KEY (+ optionally OPENWEATHER_API_KEY)
uv run flaneur          # HTTP transport on http://localhost:8000/mcp

curl http://localhost:8000/healthz   # {"status":"ok","service":"flaneur"}
```

Inspect the tools interactively: `uv run mcp dev src/flaneur/server.py`.

Example calls once connected:
- `plan_journey("Eiffel Tower, Paris", "Château de Vincennes")`
- `line_traffic("14")` — then `line_traffic()` for the whole network
- `next_departures("Châtelet")`
- `bike_route("Bastille, Paris", "La Défense")` → ~12 km, ~45-50 min (traffic-light adjusted)
- `weather("Eiffel Tower, Paris")`

## 🔑 Get the keys (both free)

- **PRIM** (required for transit): create an account at
  <https://prim.iledefrance-mobilites.fr> → *My account → Authentication tokens*.
- **OpenWeatherMap** (only for `weather`): <https://openweathermap.org/api>.

## 🗺️ Architecture

```
flaneur/
├── src/flaneur/          # the MCP server
│   ├── server.py         #   FastMCP app, tool registration, /healthz
│   ├── config.py         #   settings (keys, URLs, cache TTL)
│   ├── prim_client.py    #   shared httpx client: per-request keys, retries, errors
│   ├── geocoding.py      #   address → coordinates (national geocoder + Navitia)
│   ├── journeys.py       #   plan_journey + disruption-enriched summaries
│   ├── disruptions.py    #   line_traffic (disruptions_bulk / line_reports)
│   ├── departures.py     #   next_departures (SIRI stop-monitoring)
│   ├── bike.py           #   bike_route (BRouter) + traffic-light correction
│   ├── weather.py        #   weather (OpenWeatherMap) + in-memory cache
│   └── models.py         #   Pydantic output models
├── skills/itinerary/     # the agent skill (flaneur-itinerary)
├── tests/                # unit tests (parsing/logic, no live network)
├── render.yaml           # one-click Render deployment
└── pyproject.toml
```

## 🔐 Authentication — one key per user

The server is **multi-user**: each client sends **its own key** per request in an HTTP
header. The key never flows through the LLM's conversation and is never stored.

| Purpose | Header (priority order) | Env fallback |
|---|---|---|
| Transit (PRIM) | `X-PRIM-Api-Key`, `apikey`, or `Authorization: Bearer …` | `PRIM_API_KEY` |
| Weather (OpenWeatherMap) | `X-OpenWeather-Api-Key` | `OPENWEATHER_API_KEY` |

On a shared public deployment, leave the env vars empty to require every user to bring
their own key. Always deploy behind **HTTPS** (Render does by default) so keys are
encrypted in transit.

## ☁️ Deploying on Render

The repo includes a `render.yaml` blueprint:

1. **New → Blueprint**, point it at this repo.
2. Render runs a Python web service (`uv run flaneur`) on `0.0.0.0:$PORT`, health-
   checked at `/healthz`.
3. Leave `PRIM_API_KEY` / `OPENWEATHER_API_KEY` empty for a multi-user server, or set
   secrets for default fallback keys.
4. The MCP endpoint is exposed at `https://<app>.onrender.com/mcp`.

> Free plan: the service sleeps after 15 min idle; the next request pays a cold start.
> If you rename the entry point in `pyproject.toml`, update the dashboard **Start
> Command** to match — it isn't re-read from `render.yaml` on an existing service.

## 🔬 Engineering notes

A few decisions worth surfacing:

- **Traffic-light-adjusted cycling.** Raw BRouter durations imply ~20 km/h in Paris —
  optimistic for on-time planning. `bike_route` adds ~15 s per traffic-signal crossing
  actually on the route (BRouter reports each crossing), landing at realistic
  ~12-15 km/h. The broken `shortest` profile (which routed onto footways at walking
  pace) is excluded.
- **Resilient upstreams.** The shared HTTP client retries transient `429`/`503` with
  backoff, and weather responses are cached ~10 min to respect OpenWeatherMap's free-
  tier limits. Errors become clear, source-attributed messages, not raw stack traces.
- **Verbose-API taming.** Navitia's journey payloads are large; `journeys.py` flattens
  them into compact, LLM-friendly summaries and re-attaches each disruption to the
  exact leg it affects.

### Limitations & assumptions

- Cycling/walking times are estimates (PRIM only routes walking; there's no walk
  router, so walking distance uses a straight-line estimate with an urban circuity
  correction). Transit times come from real, disruption-aware schedules.
- Weather forecasts cap at 5 days (OpenWeatherMap free tier).
- Geocoding takes the top match — include a postcode/city for ambiguous names.
- The Google Calendar tool/parameter names in the skill are illustrative; confirm them
  against your connected Calendar MCP.

## ✅ Tests

```bash
uv run pytest        # unit tests: parsing, timing, caching, key resolution — no live network
```

## License

MIT.
