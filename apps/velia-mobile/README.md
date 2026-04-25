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

## Run locally

```bash
cd apps/velia-mobile
python -m http.server 4174
```

Open `http://localhost:4174`.

## Manual screenshot steps (if screenshot tools are unavailable)

1. Run local server.
2. Complete onboarding.
3. Capture Today screen (priority + recommendation + missing data + weather risk).
4. Capture quick irrigation log form.
5. Capture update condition flow.

## Tests

```bash
cd apps/velia-mobile
npm test
```

Includes v0.2 coverage for weather service output, recommendation behavior, missing data handling, field condition observation, irrigation-log effect path, offline cache behavior, and voice command mutation flows.
