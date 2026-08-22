# Agronomic Decision Kernel v0.3 (v0.2 compatibility name)

`AgronomicDecisionKernelV02` remains the import-compatible class name, but the
production implementation is the fail-closed `agronomic_decision_kernel_v0.3`.
The legacy v0.2 heuristic defaults are isolated and cannot authorize an
operational recommendation.

## Safety contract

The kernel never infers crop coefficient, effective rainfall, root-zone
replenishment, irrigation efficiency, flow validity, operating window, or
recent applied-water credit from crop/soil/method labels. Missing or invalid
inputs produce `insufficient_data` or `inspect`; unsupported values remain
`null` and are never clamped into plausible-looking numbers.

An operational irrigation proposal requires either:

- an explicit net irrigation requirement; or
- matching ETo, supplied Kc, effective rainfall, root-zone replenishment, and a
  verified recent-applied-water status.

It also requires crop and method identity, supplied irrigation efficiency,
field area, source-validated flow, and a customer-approved operating window.
The resulting status is `ready_for_human_approval`, never autonomous execution.

## Versioned calculations

All calculations run through `ScientificToolRegistry` and return their tool
version, normalized inputs, missing requirements, assumptions, limitations,
and output:

- `fao56.etc.single_kc.v1`: `ETc = Kc × ETo`
- `irrigation.gross_requirement.v1`: `gross = net ÷ efficiency`
- `irrigation.volume_from_depth.v1`: `volume = depth × area × 10`
- `irrigation.duration_from_validated_flow.v1`: `duration = volume ÷ flow`

Unit conversion, measured volume/depth, evidence freshness, and sensor
plausibility are also registered as deterministic tools. Freshness and
plausibility thresholds must be supplied by source calibration or policy; the
tools contain no hidden domain thresholds.

## Evidence validation

Flow evidence must identify the matching block, trusted controller/flow-meter
provenance, timestamp, explicit validity period or caller-supplied maximum age,
stable pressure, and current calibration status. Observed variance is accepted
only against an explicit source-specific limit.

Recent irrigation credit requires matching block, controller/flow-meter
confirmation, timestamp, and explicit validity/freshness. It is applied exactly
as verified, with no silent percentage or depth cap.

## Output and verification

The response contains action/status, justified values or `null`, exact missing
inputs, validation warnings, tool traces, and limitations. A proposed action
requires approval preservation, controller/meter/operator execution evidence,
as-applied reconciliation, and a post-action field or sensor observation before
the outcome can be marked verified.

## Legacy isolation

`calibration_packs.py` is retained only for backward-compatible preview and
research display. It declares `OPERATIONAL_USE_ALLOWED = False`; the production
kernel does not import it. Its historical crop, soil, and method constants must
not be presented as customer calibration.
