---
name: flaneur-itinerary
description: Calculate the optimal departure time and recommended route between two addresses in Île-de-France using the Flâneur MCP, accounting for real-time network disruptions and weather conditions (for walking or cycling routes). Checks Google Calendar for appointments, maintains time buffers, and can automatically detect and plan inter-meeting journeys.
---

# Flâneur Itinerary — Weather, Calendar Integration & Smart Planning

Use this skill to calculate the optimal departure time and recommended route
between two addresses in Île-de-France, using the Flâneur MCP, accounting for
network disruptions and weather conditions (for walking or cycling routes).
Automatically checks Google Calendar for appointments, maintains smart time
buffers, and can automatically detect location changes between calendar
events to plan inter-meeting journeys with realistic, on-time arrival.

> **Corrections applied in this revision:** OpenWeatherMap condition codes
> (the `shortest` bike profile no longer exists — Flâneur's `bike_route`
> now only accepts `trekking`/`fastbike`, both traffic-light-adjusted), a
> forecast-window bug that silently dropped weather checks for any day
> other than today, redundant geocoding/weather calls, a silently-skipped
> "not enough time between meetings" case, and an uncorrected straight-line
> walking-distance estimate. See inline notes below.

## 🎯 Capabilities

- Route calculation using public transport, with automatic detection of
  disruptions (roadworks, incidents, delays).
- Bike route calculation with estimated duration and distance (already
  adjusted by Flâneur for traffic-light delays — see note below).
- Walking route calculation with estimated duration (straight-line distance
  with an urban circuity correction — see note below).
- Weather condition verification for pedestrian or cycling routes.
- Takes into account a desired departure or arrival time.
- Automatically maintains a configurable buffer (default 5 minutes) when an
  arrival time is specified, to ensure punctuality.
- Google Calendar integration: checks for appointments around the arrival
  time, and for conflicts during the journey itself, and warns the user.
- Smart timing calculation: ensures you never arrive late by calculating
  departure times based on the previous event's end time.
- Automatic inter-meeting journey detection: scans your calendar for
  location changes between consecutive events and plans the necessary
  routes, flagging any pair of events with insufficient travel time.
- User preferences integration: uses your home/work addresses and preferred
  transport modes (bike if the leg is short enough and weather permits).
- Returns the recommended departure time to arrive on time.

## 📥 Inputs

### Required parameters

- `origin` (string): departure address, stop name, or `lon;lat` coordinates.
- `destination` (string): arrival address, same formats as `origin`.

### Optional parameters

- `when` (string): date/time in ISO 8601 format (e.g. `2026-07-18T08:30:00`). Default: now.
- `arrive_by` (boolean): if true, `when` is the desired arrival time instead of
  departure. Default: false. When true, the buffer is applied automatically.
- `mode` (string): preferred transport mode.
  - `"public_transport"` (default)
  - `"bike"`
  - `"walk"`
  - `"auto"` — bike if the trip is short enough and weather permits, otherwise
    the best alternative.
- `bike_profile` (string, only if `mode` is `"bike"` or `"auto"`): `"trekking"`
  (balanced, default) or `"fastbike"` (faster). **Do not pass `"shortest"`** —
  Flâneur's `bike_route` tool rejects it (it used to route onto footways at
  walking pace and was removed).
- `max_journeys` (number): maximum number of proposed routes, 1 to 5, public
  transport only. Default: 3.
- `check_calendar` (boolean): whether to check Google Calendar. Default: true.
- `calendar_time_window` (number): time window in minutes around the arrival
  time to check for appointments. Default: 30.
- `buffer_minutes` (number): safety buffer in minutes for arrival times. Default: 5.
- `user_home` (string): home address for automatic journey planning. Uses the
  library value if not provided.
- `user_work` (string): work address for automatic journey planning. Uses the
  library value if not provided.

### Inter-meeting journey parameters (for `calculateInterMeetingItineraries`)

- `start_date` (string, required): start date, ISO 8601 (e.g. `2026-07-20`).
- `end_date` (string, required): end date, ISO 8601 (e.g. `2026-07-22`).
- `auto_create_events` (boolean): whether to automatically create calendar
  events for the journeys. Default: false.
- `min_gap_minutes` (number): minimum gap between events to consider a
  journey feasible without a warning (in minutes). Default: 10. Gaps smaller
  than this are still reported, with `isFeasible: false` and a warning —
  they are never silently skipped.

## 📤 Outputs

### For a single journey calculation

```
{
  origin: GeoLocation,
  destination: GeoLocation,

  recommended_journey: {
    mode: string,  // "public_transport" | "bike" | "walk"
    departure_time: string,  // ISO 8601
    arrival_time: string,  // ISO 8601
    duration_minutes: number,
    distance_km?: number,  // bike/walk only

    sections?: JourneySection[],  // public transport
    route_summary?: string,

    status?: string,  // e.g. "NO_SERVICE", "SIGNIFICANT_DELAYS"
    has_disruptions?: boolean,
    disruptions?: Disruption[]
  },

  alternative_journeys?: Journey[],  // public transport

  weather_alerts?: {
    departure: WeatherCheck,
    midpoint?: WeatherCheck,  // omitted for short legs, see note below
    arrival: WeatherCheck,
    overall_recommendation: string
  },

  calendar_alerts?: {
    has_appointments: boolean,
    appointments?: CalendarAppointment[],
    recommendation?: string
  },
  journey_conflicts?: {
    has_conflicts: boolean,
    conflicts?: CalendarAppointment[],
    recommendation?: string
  },

  recommendations?: string[],

  calculated_at: string,
  note?: string
}
```

### For inter-meeting journey calculation

```
{
  period: { start_date: string, end_date: string },
  total_events_analyzed: number,
  inter_meeting_journeys: {
    origin: string,
    destination: string,
    previousEvent: string,
    nextEvent: string,
    mode: string,
    distance_km: number,
    duration_minutes: number,
    departure_time: string,
    arrival_time: string,
    isFeasible: boolean,
    warning?: string,
    weather_alerts?: {
      departure: WeatherCheck,
      midpoint?: WeatherCheck,
      arrival: WeatherCheck,
      overall_recommendation: string
    }
  }[],
  journeys_created: number,
  warnings: string[]
}
```

## 🌤️ Weather Verification

For bike and walk modes, the skill checks weather conditions at the
departure point and the arrival point, plus the midpoint **only for legs
longer than 12 minutes** (for shorter legs, conditions rarely differ enough
to matter, and it halves the number of upstream OpenWeatherMap calls per
journey — see the efficiency note below).

Alert thresholds:

- ⚠️ Rain: precipitation > 1 mm/h, or forecast probability > 60%.
- ❄️ Cold: temperature < 5°C.
- 🌡️ Heat: temperature > 30°C.
- 💨 Wind: speed > 30 km/h.
- ⛈️ Dangerous conditions, by **OpenWeatherMap condition code** (`weather_code`
  in Flâneur's `weather` output — these are OWM codes, not WMO codes):
  - `200`–`232`: thunderstorm
  - `602`, `611`–`622`: snow, sleet, freezing rain
  - `741`: fog
  - `771`: squalls
  - `781`: tornado

If unfavorable conditions are detected, the skill issues an alert, may
recommend an alternative transport mode, and provides advice (equipment,
postponement, etc.).

**Forecast window:** when the target time is not "now", request enough
forecast days to cover it — `days = min(5, max(1, days_between(today, target_date) + 1))`
— and look up the matching entry in the `daily` array by date. Flâneur's
`weather` tool caps forecasts at 5 days (OpenWeatherMap free-tier limit); if
the target date falls beyond that horizon, skip the weather check and note
it in `overall_recommendation` rather than silently returning nothing.

## 📅 Calendar Integration

When `check_calendar` is true (default), the skill:

1. Checks for appointments within `calendar_time_window` minutes of the
   estimated arrival time (`calendar_alerts`).
2. Checks whether the journey itself (departure → arrival, ± the time
   window) overlaps any other calendar event — e.g. a meeting scheduled
   during your commute (`journey_conflicts`).

Both checks respect the configured buffer for arrival-time calculations.

> **Integration note:** the exact tool name and parameter shape for listing
> and creating calendar events (`list_events`/`create_event` below, with
> `startTime`/`endTime`) are illustrative. Confirm them against whatever
> Google Calendar MCP tool is actually connected in your environment before
> relying on this verbatim — some integrations expect `timeMin`/`timeMax`
> or a different event shape.

## ⏱️ Configurable Buffer for Arrival Times

When `arrive_by: true` is specified, the skill applies a configurable buffer
(default 5 minutes) before all calculations (route, weather, calendar
checks), so the recommended departure time targets arriving *before* the
requested time, not exactly at it.

Example: `when: "2026-07-18T14:00:00"`, `arrive_by: true`,
`buffer_minutes: 5` → the skill targets an arrival of `13:55:00`.

## 🔄 Automatic Inter-Meeting Journey Detection

The skill can scan your Google Calendar for a date range, identify
consecutive events with different locations, and plan the journey between
them:

- Departure time = end of the previous event.
- Arrival time = start of the next event, minus the buffer.
- Best transport mode selected automatically from your preferences.
- Optionally creates calendar events for the journeys.

**Every location change is reported**, even when the gap is smaller than
`min_gap_minutes` — those are returned with `isFeasible: false` and a
warning, never silently dropped, since "there's no time to get there" is
exactly the kind of thing this skill exists to catch.

### Example scenario

```
Event 1: Meeting at Work (2 Rue des Mathurins) ends at 10:15
Event 2: Meeting at Champs-Élysées starts at 10:25
Journey: 2 Rue des Mathurins → 1 Av. des Champs-Élysées (10 min by bike)

Result:
- Departure: 10:15 (end of Event 1)
- Arrival: 10:25 (start of Event 2)
- Mode: Bike (10 min, perfect timing!)
```

If the journey instead took 15 minutes:

```
Warning: "Insufficient time! Need 20 min (15 min journey + 5 min buffer)
but only 10 min available. Consider a faster transport mode or leaving
Event 1 earlier."
```

## 🚇 Internal Operation

### 1. Geocode once, reuse everywhere

```ts
const [originGeo, destinationGeo] = await Promise.all([
  tools.flaneur.geocode_address({ query: origin }),
  tools.flaneur.geocode_address({ query: destination })
]);

// Reuse the resolved coordinates for every subsequent call — do not pass
// the raw address strings again, which would silently re-geocode (an extra
// network round trip, and a theoretical risk of a different match for an
// ambiguous address).
const originCoord = `${originGeo.longitude};${originGeo.latitude}`;
const destinationCoord = `${destinationGeo.longitude};${destinationGeo.latitude}`;
```

### 2. Apply the arrival buffer

```ts
let targetTime = when || (await step(() => new Date().toISOString()));
if (arrive_by) {
  const bufferDate = new Date(targetTime);
  bufferDate.setMinutes(bufferDate.getMinutes() - (buffer_minutes ?? 5));
  targetTime = bufferDate.toISOString();
}
```

### 3. Route calculation based on mode

Public transport:

```ts
const result = await tools.flaneur.plan_journey({
  origin: originCoord,
  destination: destinationCoord,
  when: departTime,
  arrive_by,
  max_journeys
});
```

Bike (profile is `"trekking"` or `"fastbike"` only):

```ts
const bikeResult = await tools.flaneur.bike_route({
  origin: originCoord,
  destination: destinationCoord,
  profile: bike_profile === "shortest" ? "trekking" : (bike_profile || "trekking")
});
```

Walking — Flâneur has no walking router, so this is a documented
approximation, not a real routed distance:

```ts
// Haversine gives straight-line ("as the crow flies") distance, which
// systematically understates real street-network walking distance in a
// dense city grid. Apply a circuity correction (~1.3x is a commonly cited
// factor for dense urban grids) so the estimate errs toward realistic
// rather than optimistic — consistent with why bike_route corrects for
// traffic lights instead of trusting the raw router output.
const straightLineKm = haversineKm(originGeo, destinationGeo);
const distanceKm = straightLineKm * 1.3;
const durationMinutes = Math.round((distanceKm / 5) * 60); // 5 km/h walking pace
```

### 4. Weather check (bike/walk only, midpoint skipped for short legs)

```ts
async function checkWeatherForRoute(originGeo, destinationGeo, departureTime, durationMinutes) {
  const departDate = new Date(departureTime);
  const arrivalDate = new Date(departDate.getTime() + durationMinutes * 60000);

  const forecastDays = computeForecastDays(departDate); // see helper below

  const points = [
    { name: "departure", lon: originGeo.longitude, lat: originGeo.latitude, at: departDate },
    { name: "arrival", lon: destinationGeo.longitude, lat: destinationGeo.latitude, at: arrivalDate }
  ];
  if (durationMinutes > 12) {
    points.splice(1, 0, {
      name: "midpoint",
      lon: (originGeo.longitude + destinationGeo.longitude) / 2,
      lat: (originGeo.latitude + destinationGeo.latitude) / 2,
      at: new Date(departDate.getTime() + (durationMinutes * 60000) / 2)
    });
  }

  const checks = await Promise.all(
    points.map(async p => ({
      name: p.name,
      check: analyzeWeather(
        await tools.flaneur.weather({ location: `${p.lon};${p.lat}`, days: forecastDays }),
        p.at
      )
    }))
  );

  return Object.fromEntries(checks.map(c => [c.name, c.check]));
}

function computeForecastDays(targetDate: Date): number {
  const today = new Date();
  const daysAhead = Math.floor(
    (Date.UTC(targetDate.getFullYear(), targetDate.getMonth(), targetDate.getDate()) -
     Date.UTC(today.getFullYear(), today.getMonth(), today.getDate())) / 86400000
  );
  return Math.min(5, Math.max(1, daysAhead + 1));
}
```

### 5. Calendar checks

```ts
const calendarAlerts = await checkCalendarForAppointments(arrivalTime, calendar_time_window ?? 30);
const journeyConflicts = await checkJourneyAgainstCalendar(departureTime, arrivalTime, calendar_time_window ?? 30);
```

## 📝 Usage Examples

**Example 1 — public transport with a departure time**

```
Skill: flaneur-itinerary
origin: "10 rue de Rivoli, Paris"
destination: "La Défense, Puteaux"
when: "2026-07-18T09:00:00"
```

**Example 2 — bike route with weather check**

```
Skill: flaneur-itinerary
origin: "Gare de Lyon, Paris"
destination: "Bois de Boulogne, Paris"
mode: "bike"
bike_profile: "trekking"
```

**Example 3 — walking to arrive at a specific time (5-minute buffer)**

```
Skill: flaneur-itinerary
origin: "Hôtel de Ville, Paris"
destination: "Eiffel Tower, Paris"
mode: "walk"
arrive_by: true
when: "2026-07-18T14:00:00"  // targets 13:55:00
```

**Example 4 — with all options**

```
Skill: flaneur-itinerary
origin: "Châtelet, Paris"
destination: "Orly Airport"
mode: "public_transport"
when: "2026-07-18T08:00:00"
arrive_by: false
max_journeys: 2
check_calendar: true
calendar_time_window: 60
```

**Example 5 — automatic inter-meeting journey planning**

```
Skill: flaneur-itinerary
start_date: "2026-07-20"
end_date: "2026-07-22"
auto_create_events: true
buffer_minutes: 5
user_home: "24bis Rue Traversière, Paris"
user_work: "2 Rue des Mathurins, Paris"
```

This scans the calendar from July 20–22, 2026; detects every location
change between consecutive events; calculates optimal journeys with
realistic timing (including weather forecasts scoped to each event's actual
date, not just today); creates calendar events for the feasible ones; and
reports a warning — rather than silence — for any pair of events too close
together to travel between.

**Example 6 — check feasibility without creating events**

```
Skill: flaneur-itinerary
start_date: "2026-07-21"
end_date: "2026-07-21"
auto_create_events: false
```

Returns every necessary inter-meeting journey, whether each is feasible
within the buffer, and a warning for any meeting you'd arrive late to.

## 🎨 User Output Format

```
## 📍 Route: [Departure] → [Arrival]

**Mode:** [public_transport/bike/walk]
**Recommended departure time:** [HH:MM]
**Estimated arrival time:** [HH:MM]
**Duration:** [X] minutes
**Distance:** [Y] km (bike/walk)

---

### 🚆 Route Details
[Detailed description of each step]

### ⚠️ Disruptions
[List of detected disruptions, if any]

### 🌤️ Weather Conditions (bike/walk)
- **Departure:** [Condition] – [Temperature]°C
- **Mid-journey:** [Condition] – [Temperature]°C (only for legs > 12 min)
- **Arrival:** [Condition] – [Temperature]°C

**Recommendation:** [Recommendation message]

### 📅 Calendar
[Nearby appointments, and any conflicts with the journey itself]

### 💡 Advice
- [Advice 1]
- [Advice 2]
```

## ⚠️ Error Handling

- Geocoding fails → return a clear error naming the problematic address(es).
- No route found → suggest alternative transport modes.
- Flâneur MCP unavailable → return an error with a suggestion to retry; if
  it's an authentication error, check that a PRIM (and, for `weather`, an
  OpenWeatherMap) key is configured — see the MCP's own README.
- Weather unavailable → continue without weather alerts, with a warning.
  If the target date is beyond the 5-day forecast horizon, say so explicitly
  rather than silently omitting the check.
- Calendar unavailable → continue without calendar alerts, with a warning.
- Insufficient time between events → return a warning with a concrete
  suggestion (earlier departure from the prior event, or a faster mode) —
  never drop the leg silently.
- Location missing from a calendar event → fall back to the user's home/work
  address.
- `bike_profile: "shortest"` requested → silently substitute `"trekking"`
  (or reject with a clear message) rather than forwarding it to the MCP,
  which will error.

## 💡 Design Notes

- **Timing is critical**: always calculate departure time from the previous
  event's *end* time, not just the next event's start time.
- **Buffers are configurable and always respected.**
- **Calendar events often lack a location** — fall back to the user's
  home/work address.
- **Mode selection**: prefer bike for short trips when weather permits,
  otherwise fall back to public transport.
- **Don't trust raw travel-time estimates at face value.** Both of
  Flâneur's non-scheduled modes need a correction to be realistic for
  "arrive on time" planning: `bike_route` already applies a traffic-light
  delay server-side; this skill applies an urban circuity factor to the
  walking-distance approximation for the same reason. Public-transit times
  from `plan_journey` come from real, disruption-aware schedules and don't
  need a correction.
- **Minimize upstream API calls**: reuse geocoding results, skip the
  midpoint weather check on short legs, and scope forecast requests to the
  actual target date — OpenWeatherMap's free tier has real rate limits, and
  a busy multi-meeting day can otherwise multiply into dozens of calls.

## 📚 References

- Flâneur MCP: Île-de-France transport routing based on the PRIM API,
  cycling routes via BRouter, weather via OpenWeatherMap.
- OpenWeatherMap condition codes: <https://openweathermap.org/weather-conditions>
- Google Calendar API: for appointment checking and event creation (verify
  the exact tool/parameter names against your connected MCP).

## 🔧 Reference Implementation

```ts
// Ensure on-time arrival with a buffer; never silently drops a leg.
function ensureOnTimeArrival(
  previousEventEnd: string,
  nextEventStart: string,
  journeyDuration: number,
  bufferMinutes: number = 5
): { departureTime: string; arrivalTime: string; isFeasible: boolean; warning?: string } {
  const endDate = new Date(previousEventEnd);
  const startDate = new Date(nextEventStart);
  const availableMinutes = (startDate.getTime() - endDate.getTime()) / 60000;
  const requiredMinutes = journeyDuration + bufferMinutes;

  if (availableMinutes < requiredMinutes) {
    const earliestDeparture = new Date(startDate.getTime() - requiredMinutes * 60000);
    return {
      departureTime: earliestDeparture.toISOString(),
      arrivalTime: new Date(earliestDeparture.getTime() + journeyDuration * 60000).toISOString(),
      isFeasible: false,
      warning: `Insufficient time! Need ${requiredMinutes} min but only ${Math.round(availableMinutes)} min available. Leave ${Math.round(requiredMinutes - availableMinutes)} min earlier from the previous event.`
    };
  }

  const departureDate = new Date(startDate.getTime() - requiredMinutes * 60000);
  return {
    departureTime: departureDate.toISOString(),
    arrivalTime: new Date(departureDate.getTime() + journeyDuration * 60000).toISOString(),
    isFeasible: true
  };
}

async function calculateInterMeetingItineraries(params: {
  start_date: string;
  end_date: string;
  buffer_minutes?: number;
  user_home?: string;
  user_work?: string;
  auto_create_events?: boolean;
  check_weather?: boolean;
  min_gap_minutes?: number;
}) {
  const {
    start_date,
    end_date,
    buffer_minutes = 5,
    user_home = null,
    user_work = null,
    auto_create_events = false,
    check_weather = true,
    min_gap_minutes = 10
  } = params;

  const calendarEvents = await tools.google_calendar.list_events({
    startTime: `${start_date}T00:00:00+02:00`,
    endTime: `${end_date}T23:59:59+02:00`,
    orderBy: "startTime"
  });

  const userEvents = (calendarEvents.events || [])
    .filter(e => !e.summary?.includes("Trajet") && !e.summary?.includes("Journey"))
    .sort((a, b) =>
      new Date(a.start?.dateTime || a.start?.date || "").getTime() -
      new Date(b.start?.dateTime || b.start?.date || "").getTime()
    );

  const homeAddress = user_home || "24bis Rue Traversière, Paris";
  const workAddress = user_work || "2 Rue des Mathurins, Paris";

  const interMeetingJourneys: InterMeetingJourney[] = [];

  for (let i = 0; i < userEvents.length - 1; i++) {
    const currentEvent = userEvents[i];
    const nextEvent = userEvents[i + 1];

    const currentEnd = currentEvent.end?.dateTime || currentEvent.end?.date;
    const nextStart = nextEvent.start?.dateTime || nextEvent.start?.date;
    if (!currentEnd || !nextStart) continue;

    const currentLocation = currentEvent.location || workAddress;
    const nextLocation = nextEvent.location || workAddress;
    if (currentLocation === nextLocation) continue;

    // Compute the journey regardless of the raw gap size — a tight gap is
    // exactly the case we need to surface, not skip.
    const journey = await calculateOptimalJourney({
      origin: currentLocation,
      destination: nextLocation,
      when: currentEnd,
      arrive_by: false,
      mode: "auto",
      buffer_minutes: 0 // buffer handled separately below
    });
    if (!journey.recommended_journey) continue;

    const timing = ensureOnTimeArrival(
      currentEnd,
      nextStart,
      journey.recommended_journey.duration_minutes,
      buffer_minutes
    );

    const gapMinutes = (new Date(nextStart).getTime() - new Date(currentEnd).getTime()) / 60000;
    const tooTight = gapMinutes < min_gap_minutes;

    const journeyInfo: InterMeetingJourney = {
      origin: currentLocation,
      destination: nextLocation,
      previousEvent: currentEvent.summary,
      nextEvent: nextEvent.summary,
      mode: journey.recommended_journey.mode,
      distance_km: journey.recommended_journey.distance_km,
      duration_minutes: journey.recommended_journey.duration_minutes,
      departure_time: timing.departureTime,
      arrival_time: timing.arrivalTime,
      isFeasible: timing.isFeasible && !tooTight,
      warning: timing.warning ??
        (tooTight
          ? `Only ${Math.round(gapMinutes)} min between "${currentEvent.summary}" and "${nextEvent.summary}" — below the ${min_gap_minutes}-min minimum you configured.`
          : undefined),
      weather_alerts: check_weather
        ? await checkWeatherForRoute(
            await tools.flaneur.geocode_address({ query: currentLocation }),
            await tools.flaneur.geocode_address({ query: nextLocation }),
            timing.departureTime,
            journey.recommended_journey.duration_minutes
          )
        : undefined
    };

    interMeetingJourneys.push(journeyInfo);

    if (auto_create_events && journeyInfo.isFeasible) {
      await tools.google_calendar.create_event({
        summary: `Trajet ${journeyInfo.mode}: ${currentLocation} → ${nextLocation}`,
        startTime: timing.departureTime,
        endTime: timing.arrivalTime,
        description:
          `Trajet entre réunions\n` +
          `De: ${currentEvent.summary}\n` +
          `À: ${nextEvent.summary}\n` +
          `Distance: ${journeyInfo.distance_km} km\n` +
          `Durée: ${journeyInfo.duration_minutes} min\n` +
          `Mode: ${journeyInfo.mode}`,
        location: `${currentLocation} → ${nextLocation}`,
        timeZone: "Europe/Paris"
      });
    }
  }

  return {
    period: { start_date, end_date },
    total_events_analyzed: userEvents.length,
    inter_meeting_journeys: interMeetingJourneys,
    journeys_created: auto_create_events ? interMeetingJourneys.filter(j => j.isFeasible).length : 0,
    warnings: interMeetingJourneys.filter(j => j.warning).map(j => j.warning!)
  };
}

async function checkCalendarForAppointments(arrivalTime: string, timeWindow: number) {
  try {
    const arrivalDate = new Date(arrivalTime);
    const startTime = new Date(arrivalDate.getTime() - timeWindow * 60000);
    const endTime = new Date(arrivalDate.getTime() + timeWindow * 60000);

    const calendarResult = await tools.google_calendar.list_events({
      startTime: startTime.toISOString(),
      endTime: endTime.toISOString(),
      orderBy: "startTime"
    });

    const appointments = (calendarResult.events || [])
      .filter(e => e.start && e.summary)
      .map(e => ({
        title: e.summary!,
        start_time: e.start?.dateTime || e.start?.date || "Unknown",
        end_time: e.end?.dateTime || e.end?.date || "Unknown",
        location: e.location || "Not specified"
      }));

    if (appointments.length === 0) {
      return { has_appointments: false, appointments: [], recommendation: "✅ No appointments found around your arrival time." };
    }

    const recommendation = appointments.length === 1
      ? `⚠️ You have an appointment at ${appointments[0].start_time}. Consider adjusting your departure time.`
      : "⚠️ You have appointments around your arrival time.";

    return { has_appointments: true, appointments, recommendation };
  } catch (error) {
    console.warn("Calendar check failed:", error);
    return { has_appointments: false, appointments: [], recommendation: "⚠️ Could not check calendar. Please verify your calendar access." };
  }
}

// Checks whether the journey itself (not just arrival time) overlaps another event.
async function checkJourneyAgainstCalendar(
  departureTime: string,
  arrivalTime: string,
  timeWindow: number = 30
): Promise<{ has_conflicts: boolean; conflicts?: CalendarAppointment[]; recommendation?: string }> {
  try {
    const depDate = new Date(departureTime);
    const arrDate = new Date(arrivalTime);
    const journeyStart = new Date(depDate.getTime() - timeWindow * 60000);
    const journeyEnd = new Date(arrDate.getTime() + timeWindow * 60000);

    const calendarResult = await tools.google_calendar.list_events({
      startTime: journeyStart.toISOString(),
      endTime: journeyEnd.toISOString(),
      orderBy: "startTime"
    });

    const conflicts = (calendarResult.events || [])
      .filter(e => e.summary && !e.summary.includes("Trajet") && !e.summary.includes("Journey"))
      .filter(e => {
        const eventStart = new Date(e.start?.dateTime || e.start?.date || "");
        const eventEnd = new Date(e.end?.dateTime || e.end?.date || "");
        return depDate < eventEnd && arrDate > eventStart;
      })
      .map(e => ({
        title: e.summary!,
        start_time: e.start?.dateTime || e.start?.date || "",
        end_time: e.end?.dateTime || e.end?.date || "",
        location: e.location || "Not specified"
      }));

    if (conflicts.length === 0) {
      return { has_conflicts: false, conflicts: [], recommendation: "✅ No conflicts with your journey." };
    }
    return {
      has_conflicts: true,
      conflicts,
      recommendation: `⚠️ Your journey conflicts with ${conflicts.length} event(s). Consider rescheduling.`
    };
  } catch (error) {
    console.warn("Journey conflict check failed:", error);
    return { has_conflicts: false, conflicts: [], recommendation: "⚠️ Could not check for journey conflicts." };
  }
}

function computeForecastDays(targetDate: Date): number {
  const today = new Date();
  const daysAhead = Math.floor(
    (Date.UTC(targetDate.getFullYear(), targetDate.getMonth(), targetDate.getDate()) -
     Date.UTC(today.getFullYear(), today.getMonth(), today.getDate())) / 86400000
  );
  return Math.min(5, Math.max(1, daysAhead + 1));
}

async function checkWeatherForRoute(originGeo: any, destinationGeo: any, departureTime: string, durationMinutes: number) {
  const departDate = new Date(departureTime);
  const arrivalDate = new Date(departDate.getTime() + durationMinutes * 60000);
  const forecastDays = computeForecastDays(departDate);

  if (forecastDays > 5) {
    return {
      departure: null, midpoint: null, arrival: null,
      overall_recommendation: "ℹ️ Target date is beyond the 5-day forecast horizon — weather could not be checked."
    };
  }

  const points: { name: string; lon: number; lat: number; at: Date }[] = [
    { name: "departure", lon: originGeo.longitude, lat: originGeo.latitude, at: departDate },
    { name: "arrival", lon: destinationGeo.longitude, lat: destinationGeo.latitude, at: arrivalDate }
  ];
  if (durationMinutes > 12) {
    points.splice(1, 0, {
      name: "midpoint",
      lon: (originGeo.longitude + destinationGeo.longitude) / 2,
      lat: (originGeo.latitude + destinationGeo.latitude) / 2,
      at: new Date(departDate.getTime() + (durationMinutes * 60000) / 2)
    });
  }

  const results = await Promise.all(
    points.map(async p => [
      p.name,
      analyzeWeather(
        await tools.flaneur.weather({ location: `${p.lon};${p.lat}`, days: forecastDays }),
        p.at
      )
    ] as const)
  );
  const checks = Object.fromEntries(results);

  const allAlerts = Object.values(checks).flatMap((c: any) => c.alerts);
  let overall_recommendation = "✅ Favorable weather conditions for this route.";
  if (allAlerts.length > 0) {
    const hasSevere = allAlerts.some((a: any) => a.severity === "high");
    overall_recommendation = `⚠️ Caution: ${allAlerts.length} weather alert(s) detected. ` +
      (hasSevere ? "Consider an alternative transport mode or postpone your trip." : "Bring appropriate equipment.");
  }

  return { ...checks, overall_recommendation };
}

// OpenWeatherMap condition-code ranges for dangerous conditions (NOT WMO codes).
const DANGEROUS_OWM_CODE_RANGES: [number, number, string][] = [
  [200, 232, "Thunderstorm"],
  [602, 602, "Heavy snow"],
  [611, 622, "Sleet / freezing rain / snow showers"],
  [741, 741, "Fog"],
  [771, 771, "Squalls"],
  [781, 781, "Tornado"]
];

function describeDangerousCode(code: number): string | null {
  for (const [lo, hi, label] of DANGEROUS_OWM_CODE_RANGES) {
    if (code >= lo && code <= hi) return label;
  }
  return null;
}

function analyzeWeather(weatherResult: any, targetTime: Date) {
  const alerts: WeatherAlert[] = [];
  const current = weatherResult.current;

  if (current) {
    if (current.precipitation_mm && current.precipitation_mm > 1) {
      alerts.push({ type: "rain", message: `Rain: ${current.precipitation_mm} mm/h`, severity: "medium", value: current.precipitation_mm });
    }
    if (current.temperature_c != null) {
      if (current.temperature_c < 5) {
        alerts.push({ type: "cold", message: `Cold: ${current.temperature_c}°C`, severity: "medium", value: current.temperature_c });
      } else if (current.temperature_c > 30) {
        alerts.push({ type: "heat", message: `Heat: ${current.temperature_c}°C`, severity: "high", value: current.temperature_c });
      }
    }
    if (current.wind_speed_kmh && current.wind_speed_kmh > 30) {
      alerts.push({ type: "wind", message: `Strong wind: ${current.wind_speed_kmh} km/h`, severity: "medium", value: current.wind_speed_kmh });
    }
    if (current.weather_code != null) {
      const label = describeDangerousCode(current.weather_code);
      if (label) {
        alerts.push({ type: "dangerous_condition", message: `${label} (OWM code ${current.weather_code})`, severity: "high", value: current.weather_code });
      }
    }
  }

  if (weatherResult.daily?.length) {
    const targetDate = targetTime.toISOString().split("T")[0];
    const forecast = weatherResult.daily.find((d: any) => d.date === targetDate);
    if (forecast?.precipitation_probability_pct > 60) {
      alerts.push({ type: "rain_probability", message: `Rain probability: ${forecast.precipitation_probability_pct}%`, severity: "medium", value: forecast.precipitation_probability_pct });
    }
  }

  return {
    time: targetTime.toISOString(),
    condition: current?.condition || "Unknown",
    temperature: current?.temperature_c,
    alerts
  };
}

function generateRecommendations(journeyResult: any) {
  const recommendations: string[] = [];

  if (journeyResult.mode === "walk" && journeyResult.distance_km > 5) {
    recommendations.push("Consider a bike or public transport for this distance.");
  }
  if (journeyResult.mode === "walk") {
    recommendations.push("Walking distance/time is an estimate (no real walking router available).");
  }

  if (journeyResult.mode === "bike" && journeyResult.weather_alerts) {
    const allAlerts = Object.values(journeyResult.weather_alerts)
      .filter((v: any) => v?.alerts)
      .flatMap((v: any) => v.alerts);
    if (allAlerts.some((a: any) => a.severity === "high")) {
      recommendations.push("Weather conditions are dangerous for cycling. Consider public transport.");
    } else if (allAlerts.length > 0) {
      recommendations.push("Weather conditions may affect your ride. Bring appropriate gear.");
    }
  }

  if (journeyResult.has_disruptions) {
    recommendations.push("There are disruptions on your route. Check for alternative journeys.");
  }
  if (journeyResult.calendar_alerts?.has_appointments) {
    recommendations.push(journeyResult.calendar_alerts.recommendation);
  }
  if (journeyResult.journey_conflicts?.has_conflicts) {
    recommendations.push(journeyResult.journey_conflicts.recommendation);
  }
  if (journeyResult.note?.includes("buffer applied")) {
    recommendations.push("A safety buffer has been applied to ensure you arrive on time.");
  }

  return recommendations.length > 0 ? recommendations : ["Have a safe journey!"];
}

// Utility types
interface WeatherAlert { type: string; message: string; severity: "low" | "medium" | "high"; value: number; }
interface WeatherCheck { time: string; condition: string; temperature?: number; alerts: WeatherAlert[]; }
interface CalendarAppointment { title: string; start_time: string; end_time: string; location: string; }
interface InterMeetingJourney {
  origin: string; destination: string; previousEvent: string; nextEvent: string; mode: string;
  distance_km: number; duration_minutes: number; departure_time: string; arrival_time: string;
  isFeasible: boolean; warning?: string;
  weather_alerts?: { departure: WeatherCheck; midpoint?: WeatherCheck; arrival: WeatherCheck; overall_recommendation: string };
}

function haversineKm(a: { latitude: number; longitude: number }, b: { latitude: number; longitude: number }): number {
  const R = 6371;
  const dLat = (b.latitude - a.latitude) * Math.PI / 180;
  const dLon = (b.longitude - a.longitude) * Math.PI / 180;
  const h = Math.sin(dLat / 2) ** 2 +
    Math.cos(a.latitude * Math.PI / 180) * Math.cos(b.latitude * Math.PI / 180) * Math.sin(dLon / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h));
}
```

Base directory for this skill: `/home/user/skills/flaneur-itinerary`. Relative
paths in this skill are relative to this base directory.
