# AGRO-AI Intelligence Engine v1

## Purpose
AGRO-AI Intelligence Engine v1 is the first production-oriented irrigation decision layer that turns mixed farm signals into a truthful recommendation with confidence, limitations, and verification requirements.

It is designed to answer:
**What should this farm do with water today, why, with what confidence, and what must be verified afterward?**

## Endpoint Surface
- `POST /v1/intelligence/field-context/normalize`
- `POST /v1/intelligence/data-quality`
- `POST /v1/intelligence/recommend`
- `GET /v1/intelligence/schema`

## Canonical Field Context Input
The normalized field context accepts source-aware and partial-data workloads:
- `field_id`, `farm_id`, `source`, `source_entity_id`
- `crop_type`, `irrigation_method`, `soil_type`, `area`, `location`
- `weather_context`, `sensor_context`, `controller_context`
- `recent_irrigation_context`, `field_observations`
- `data_quality_score`, `missing_inputs`, `confidence_inputs`

This allows one model for:
- WiseConn-connected zones
- Talgil-connected targets/sensors
- manual/no-hardware fields
- partial telemetry fields

## Input Normalization and Alias Support
`POST /v1/intelligence/field-context/normalize` accepts messy integration-shaped inputs and returns:
- `normalized_context` (strict canonical model)
- `aliases_applied`
- `ignored_fields`
- `warnings`

### Weather aliases
- `rain_forecast_mm` → `weather_context.precipitation_forecast_mm`
- `rainfall_forecast_mm` → `weather_context.precipitation_forecast_mm`
- `forecast_rain_mm` → `weather_context.precipitation_forecast_mm`
- `evapotranspiration_mm` → `weather_context.eto_mm`
- `et_mm` → `weather_context.eto_mm`
- `et0_mm` → `weather_context.eto_mm`

### Location aliases
- `country` accepted as `location.country`
- `state` / `province` → `location.region`
- `county` accepted as `location.county`
- `latitude` / `longitude` → `location.lat` / `location.lon`

### Recent irrigation aliases
- `last_irrigation_days_ago` / `last_irrigation_hours_ago` converted to `recent_irrigation_context.last_irrigation_at`
- `last_irrigation_duration_minutes` → `recent_irrigation_context.last_duration_minutes`
- `last_irrigation_depth_mm` → `recent_irrigation_context.last_depth_mm`
- `irrigations_last_7_days` → `recent_irrigation_context.events_last_7_days`

### Sensor aliases
- `soil_moisture_percent` / `moisture_pct` → `sensor_context.moisture_percent`
- `pressure` (numeric) → `sensor_context.pressure_kpa`
- `flow_rate` (numeric) → `sensor_context.flow_m3h`

## Output Recommendation Schema
`POST /v1/intelligence/recommend` returns:
- `recommendation_id`
- `action`: `irrigate | wait | inspect | insufficient_data`
- `recommended_timing`
- `recommended_duration_minutes` (if supportable)
- `recommended_depth_mm` (if supportable)
- `priority`
- `confidence_score`, `confidence_label`
- `reasoning_summary`, `key_drivers`, `risk_flags`
- `missing_data`, `verification_required`
- `human_readable_explanation`, `language_status`
- `machine_readable_decision`, `source_trace`
- `data_quality`
- `execution_task`
- `verification_plan`

## Data Quality Logic
Data quality score (0-100) is computed from evidence availability and critical agronomic metadata.

Primary evidence tiers:
- **full_telemetry**: weather + telemetry + crop + soil
- **partial_telemetry**: some controller/sensor evidence, but incomplete
- **manual_only**: observations/manual history + weather, no live telemetry
- **weather_only**: weather data without field/telemetry support
- **insufficient**: missing critical signals

The engine always returns:
- `missing_inputs`
- `recommendation_limitations`
- `next_best_data_to_collect`

## Confidence Logic
Confidence is derived from data quality and constrained by decision risk:
- High confidence requires strong telemetry + context completeness.
- Moderate confidence is used for partially connected or mixed evidence.
- Low confidence is enforced when critical data is missing.

No fabricated precision policy:
- If data is weak, depth/duration can be omitted (`null`).
- Low confidence recommendations shift to `inspect` or `insufficient_data`.

## Recommendation Limitations
Current v1 logic is deterministic and conservative.
It does **not** claim autonomous optimization under sparse data.
When uncertainty is high, the engine explicitly asks for verification and additional data collection.

## Multilingual Behavior
Supported response language codes are structured for:
- `en`, `fr`, `es`, `pt`, `ar`

If translation infrastructure is unavailable, response falls back to English and sets:
- `language_status=fallback_to_en:<requested_language>`

## Observe → Recommend → Execute → Verify
1. **Observe**: collect field context (telemetry/manual/weather/controller).
2. **Recommend**: generate action with confidence and limitations.
3. **Execute**: output task steps and due window.
4. **Verify**: output verification plan with warning trigger.

This separation ensures truthful recommendations without pretending execution or outcomes.
