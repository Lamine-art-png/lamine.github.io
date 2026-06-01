# Agronomic Decision Kernel v0.2

The v0.2 kernel is a deterministic, no-fabrication decision layer for Water
Command Center V2. It is designed for preview evaluation and technical diligence:
it computes conservative irrigation decisions when enough evidence exists and
withholds precision when evidence is missing.

## Inputs

The kernel accepts ETo, crop type, growth stage, crop coefficient, precipitation
forecast, effective rainfall, soil type, root-zone depth, soil-moisture deficit,
management allowable depletion, recent irrigation, irrigation method, irrigation
efficiency, field area, controller capacity, flow rate, pressure state, operating
window, field observations, confidence state, and missing-data state.

## Formulas

- crop demand = ETo * crop coefficient
- net irrigation need = crop demand - effective rainfall + validated root-zone
  replenishment need - recent verified irrigation credit
- gross irrigation need = net irrigation need / irrigation efficiency
- required volume = gross irrigation need * field area
- duration = required volume / validated system flow

Duration is only emitted when validated flow or controller-capacity evidence is
present. Otherwise the response includes the duration limitation and returns an
inspect or insufficient-data action.

## Actions

- `irrigate`
- `wait`
- `inspect`
- `insufficient_data`

When evidence is insufficient, user-facing recommendations are:

- `Inspect and collect required evidence`
- `Decision pending source review`

## Calibration Pack

Calibration defaults are versioned as `agroai_calibration_pack_v0.2`.

Crops: wine grapes, almonds, citrus, vegetables, generic specialty crop.

Soils: sand, loam, clay loam, clay, unknown.

Irrigation methods: drip, micro-sprinkler, sprinkler, flood, unknown.

The response returns:

- `calibration_pack_version`
- `calibration_status`
- `assumptions`
- `missing_inputs`

Calibration status values are:

- `calibrated_context`
- `partial_calibration`
- `assumptions_required`
- `insufficient_context`

Defaults are never presented as farm-specific calibration.

## Outputs

The kernel returns action, net irrigation depth, gross irrigation depth,
estimated volume, duration only when justified, timing window, confidence,
evidence completeness, key drivers, assumptions, limitations, missing inputs,
verification requirements, calculation trace, calibration status,
calibration-pack version, and recommendation origin.

## Orchestration

`IrrigationDecisionOrchestrator` maps uploaded artifacts and live provider
context into the kernel. It first normalizes context through
`IntelligenceEngineV1`, merges safe explicit manual overrides, evaluates data
quality, then calls the kernel.

Uploaded analysis uses parsed controller, weather, soil, flow, crop, field-note,
earth-observation, and water-cost records. Live analysis uses provider reads from
`LiveFieldContextAssembler` and stays degraded when provider credentials, target
selection, crop profile, soil profile, field area, or flow evidence are missing.

## Known Limitations

- v0.2 defaults are conservative preview defaults, not farm-specific calibration.
- Flow-rate validation is required for precise duration.
- Durable tenant evidence persistence is future work.
- Live provider telemetry depends on server-side credential provisioning and
  target selection.
