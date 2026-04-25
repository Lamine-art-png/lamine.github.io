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

## Run locally

```bash
cd apps/velia-mobile
python -m http.server 4174
```

## Tests

```bash
cd apps/velia-mobile
npm test
```

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
