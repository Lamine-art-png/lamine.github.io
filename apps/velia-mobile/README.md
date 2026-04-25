codex/build-foundation-for-velia-voice-agent-bvfyqx
# Velia Mobile Foundation v0.3 (AGRO-AI)

Velia helps farms make better water decisions, act faster, and understand what happened across their fields.

## What changed in v0.3

- **Today UX polish retained** with card-based decision cockpit.
- **Field location/map foundation** added to field model and field detail (map placeholder + coordinates-ready fields).
- **Weather provider adapter structure** added (`weatherProviders/`) so real providers can be swapped in later.
- **Recommendation history storage** improved with deduping logic to reduce noisy repeated entries.
- **Demo scenario switching** added (Baseline, Hot and dry, Cool and wet).
- **Action confirmations** added (toasts for logs/notes/conditions).
- **Offline polish** improved with explicit offline banner and queue language.
- **Voice timeline** added to Today view to show recent voice actions.

## Architecture highlights

```text
js/services/weatherProviders/
  baseAdapter.js
  mockAdapter.js
  registry.js
```

`weatherService` now resolves a provider adapter from the registry and still supports offline caching.

## Field location/map foundation

- Field model includes:
  - `location` (text)
  - `coordinates` (lat/lon)
- Field detail renders a map-ready placeholder card so real map providers can be integrated without changing the core flow.

## Demo scenarios

Demo mode now supports scenario switching:
- `baseline`
- `hotDry`
- `coolWet`

Scenarios update weather/stress context so recommendation behavior can be demonstrated quickly.

## Recommendation history behavior

History is now stored with simple dedupe logic:
- skips repeated same-urgency records within a short interval
- keeps recent meaningful history entries

## Offline behavior

When offline:
- cached weather is used
- actions still save
- queue status remains visible
- banner and confirmations clarify that sync will resume on reconnect
=======
# Velia Mobile Foundation v0.2 (AGRO-AI)

Velia v0.2 delivers the first real **daily irrigation decision loop**.

**Product framing:** Velia helps farms make better water decisions, act faster, and understand what happened across their fields.

## v0.2 daily decision loop

A farmer can now:
1. Onboard quickly with farm + first field context.
2. Add optional GPS or manual location.
3. Receive a clear daily recommendation using field profile + weather + last irrigation + observation context.
4. Log irrigation quickly.
5. Update field condition quickly.
6. Ask Velia by voice and trigger structured actions.

## Weather service abstraction

`js/services/weatherService.js` provides a replaceable weather layer.

Current behavior:
- mock weather output (default)
- cached local weather fallback
- returns:
  - temperature
  - rain chance
  - rainfall forecast
  - wind
  - humidity
  - evapotranspiration placeholder
  - heat risk
  - frost risk
  - forecast summary
  - last updated timestamp

Future production integration points:
- OpenWeather / Meteomatics / NOAA adapter
- ET model calibration
- per-field geospatial weather blending

## Recommendation engine v0.2

`js/services/recommendationEngine.js` uses:
- crop
- acreage
- soil type
- irrigation method
- last irrigation
- weather and rainfall forecast
- heat/frost risk
- water stress status + latest observation
- data source availability
- missing data

Returns:
- main recommendation
- timing
- urgency
- confidence
- reason summary
- missing data
- risk flags
- next best action

## Offline cached weather behavior

When offline:
- Today screen still loads with cached weather + local field data
- logs and observations still save immediately
- actions are queued for later sync
- UI clearly states: using last available weather data

## Mode separation

- Demo mode: pre-seeded example farm/field
- Real mode: onboarding-created local profile + field data
 main

## Run locally

```bash
cd apps/velia-mobile
python -m http.server 4174
```

codex/build-foundation-for-velia-voice-agent-bvfyqx

Open `http://localhost:4174`.

## Manual screenshot steps (if screenshot tools are unavailable)

1. Run local server.
2. Complete onboarding.
3. Capture Today screen (priority + recommendation + missing data + weather risk).
4. Capture quick irrigation log form.
5. Capture update condition flow.

 main
## Tests

```bash
cd apps/velia-mobile
npm test
```

 codex/build-foundation-for-velia-voice-agent-bvfyqx
Includes coverage for:
- onboarding + field location capture
- weather adapter/provider structure
- recommendation behavior + missing data
- recommendation history dedupe
- demo scenario switching
- offline queue behavior
- voice parsing + voice timeline entry creation

## Planned production integration points

1. Real weather providers (OpenWeather, Meteomatics, NOAA).
2. Field map rendering adapter (Mapbox/Leaflet/Google Maps).
3. Persisted recommendation timeline analytics and comparison views.
4. Richer scenario packs for training/demo and onboarding education.

Includes v0.2 coverage for weather service output, recommendation behavior, missing data handling, field condition observation, irrigation-log effect path, offline cache behavior, and voice command mutation flows.
 main
