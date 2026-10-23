# Geographic and crop-specific advisory integration (DMRV)

## Purpose

AGRO-AI supports agricultural reasoning and validated JSON output in its existing
Intelligence API. This integration guide adds **a non-billable, synthetic UAT
contract preview** for partners building digital monitoring, reporting and
verification (DMRV) applications.

**Two separate execution paths:**

- TEST: `POST /v1/platform/recommendations/preview` with a TEST project's
  `agro_test_` API key carrying `recommendations:read`. This returns
  **deterministic simulation data**, not model inference. No billing, live
  datasets, equipment commands, provider writes, or actual carbon estimates.
- LIVE: `POST /v1/intelligence` with a separately authorized
  `agro_live_` Intelligence key. This uses the existing agricultural
  intelligence pipeline, context handling, provenance and schema validation;
  paid execution requires explicit production authorization. TEST credentials
  do **not** work on the LIVE path.

The UAT preview is private beta and should not be advertised as live or
production-ready until released and smoke-tested.

## TEST request

```http
POST /v1/platform/recommendations/preview
Authorization: Bearer $AGROAI_TEST_KEY
Content-Type: application/json
```

```json
{
  "context": {
    "location": {
      "country": "IN",
      "state": "Uttar Pradesh",
      "district": "Gautam Buddha Nagar"
    },
    "crop": {"name": "wheat", "growth_stage": "vegetative"}
  },
  "areas": ["irrigation", "nutrients", "soil", "monitoring", "sustainability"]
}
```

Response shape:

```json
{
  "id": "uat_<project-scoped-deterministic-fingerprint>",
  "status": "simulated",
  "environment": "test",
  "synthetic": true,
  "model_executed": false,
  "physical_execution": false,
  "billing": {"charged_cents": 0},
  "normalized_context": {
    "country": "IN",
    "state_or_region": "Uttar Pradesh",
    "district": "Gautam Buddha Nagar",
    "crop": "wheat",
    "growth_stage": "vegetative",
    "location_verified": false
  },
  "structured_output_status": "valid",
  "structured_output": {
    "summary": "Synthetic DMRV advisory preview...",
    "recommendations": [
      {
        "category": "irrigation",
        "action": "Review soil moisture, recent rainfall, ET0 and irrigation-system capacity before scheduling water.",
        "rationale": "Water timing and depth require local measurements...",
        "priority": "medium",
        "timing": "review before field implementation",
        "requires_human_approval": true,
        "evidence_ids": [],
        "required_evidence": ["soil moisture observations", "dated rainfall and ET0", "irrigation efficiency and water rights"]
      }
    ],
    "confidence": "low",
    "missing_data": ["..."],
    "limitations": ["..."]
  },
  "provenance": {
    "source": "static_synthetic_template",
    "evidence_ids": [],
    "customer_field_data_used": false
  }
}
```

The response's `recommendations` array contains one entry per requested area.
The example above abbreviates the remaining array items. Schema
`dmrv_advisory` is shared with the LIVE Intelligence API.

**Input safety:** The UAT preview accepts country, state/region, district,
crop and optional growth stage. Precise coordinates, polygons, customer
observations, uploaded evidence, provider credentials or production data are
not accepted. Geographic labels are not geocoded or independently verified,
and neither local regulations nor weather data are retrieved.

## LIVE API — separate explicit production agreement

The existing LIVE endpoint supports typed `context.location` (country, state,
district or region, and optional coordinates), `context.crop`, observations,
soil, weather, and verifiable sources. An authorized production client may
request the same validated `dmrv_advisory` response schema:

```json
{
  "task": "decision",
  "question": "Provide evidence-supported irrigation, nutrient, soil management and sustainability monitoring recommendations for this crop and location. Do not prescribe quantities without supporting field measurements. State missing data and avoid unverified carbon claims.",
  "context": {
    "location": {"country": "IN", "state": "Uttar Pradesh", "district": "Gautam Buddha Nagar"},
    "crop": {"name": "wheat", "growth_stage": "vegetative"}
  },
  "response_format": {"type": "agroai_schema", "name": "dmrv_advisory"}
}
```

Use `Idempotency-Key` and a restricted server-side credential. Model output
can be degraded if evidence is insufficient or schema validation fails. Never
treat `location_verified=false` or an uncited recommendation as evidence
of district-specific agronomic accuracy. Actual DMRV outcomes require an
approved methodology and independent verification.

## Release gates

1. Code review and all targeted unit and integration tests pass.
2. Confirm TEST-only entitlement, key scope, tenant isolation, no charge,
   no inference, and no provider/physical writes.
3. Demonstrate deterministic UAT response for wheat and a second crop,
   missing data and adversarial geographic inputs.
4. Only then deploy via the normal protected release process.
5. Obtain the customer's acceptance of the UAT schema, followed by
   a separately scoped and priced production agreement.
