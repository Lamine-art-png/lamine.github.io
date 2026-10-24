# AGRO-AI DMRV Advisory API — integration contract `dmrv-uat/2`

Evidence-grounded agricultural recommendations by country, state/region,
district and crop for digital monitoring, reporting and verification (DMRV)
platforms.

| | TEST (UAT) | LIVE |
|---|---|---|
| Endpoint | `POST /v1/platform/recommendations/preview` | `POST /v1/intelligence` with `response_format: {"type":"agroai_schema","name":"dmrv_advisory"}` |
| Credential | `agro_test_` key, scope `recommendations:read`, TEST project | `agro_live_` key, scope `intelligence:run`, LIVE project |
| Engine | Deterministic AGRO-AI engine (below). No model. | Same deterministic engine output supplied as cited evidence to the AGRO-AI Intelligence model |
| Cost | Free (`billing.charged_cents: 0`) | Billed per completed run from a funded Intelligence wallet; failed or degraded runs are not charged |
| Data you may send | Location and crop labels; **synthetic** UAT measurements only | Your authorized production context |
| Availability | Per-organization allowlist | Requires a signed production agreement; disabled until then |

TEST credentials never reach the LIVE endpoint, never spend wallet balance and
never read production records. LIVE `dmrv_advisory` is disabled until a
production agreement is in place.

## How recommendations are produced

1. **Location** — `country` + `state`/`region` + `district` are resolved against
   a GeoNames gazetteer (CC BY 4.0; 763 Indian and 64 Bangladeshi districts).
   Renamed districts (for example Allahabad → Prayagraj) are matched and
   reported. The result is an administrative representative point
   (`location_precision`), never a field location.
2. **Climate** — For precomputed districts, monthly means of NASA POWER daily
   data (2004–2023) drive FAO-56 Penman–Monteith reference ET₀ and USDA-SCS
   effective rainfall, computed by AGRO-AI's registered scientific tools.
3. **Soil** — ISRIC SoilGrids 2.0 (CC BY 4.0) 0–30 cm predictions at the
   district point give texture class, pH, organic carbon, nitrogen and CEC.
   FAO-56 Table 19 gives a total/readily available water range. These values are
   labelled regional estimates.
4. **Crop** — Cited FAO-56 crop coefficients (Table 12), stage lengths
   (Table 11), rooting depth and depletion fraction (Table 22) for wheat, rice,
   maize, cotton, sugarcane, soybean, chickpea, potato and tomato. Common local
   names are accepted (paddy, gram/chana, makka, ganna, aloo, …).
5. **Calendar** — Planting date (`crop.planted_at`), or a season label
   (`kharif`, `rabi`, `zaid`; `aus`, `aman`, `boro`), or the crop's typical
   season (disclosed as an assumption). Growth stage comes from `growth_stage`,
   or from `planted_at` + `as_of`. Contradictions are reported and lower
   confidence.
6. **Your measurements** — If supplied, these override regional estimates:
   soil test (rated on India Soil Health Card classes), measured soil-water
   constants and current moisture (giving an irrigation trigger, net and gross
   refill depth and volume), irrigation efficiency, field area and stage
   lengths.

Every number is produced by a registered scientific tool and listed in
`calculations`. Every recommendation's `evidence_ids` resolve to an entry in
`evidence` or `calculations`. AGRO-AI never returns fertilizer doses, carbon
quantities or verified emissions outcomes.

## Authentication

```
Authorization: Bearer <agro_test_ key>
Content-Type: application/json
```

Create the key in the Developer Console: Projects → your TEST project →
Service accounts → API keys, with scope `recommendations:read`. The secret is
shown once. Keep it server-side, and never send it in support email.

## Request

| Field | Type | Required | Notes |
|---|---|---|---|
| `context.location.country` | string | yes | ISO 3166-1 alpha-2, uppercase (`IN`, `BD`) |
| `context.location.state` or `.region` | string | yes | State or first-level region; codes like `UP` and legacy names like `Orissa` are accepted |
| `context.location.district` | string | yes | Second-level district |
| `context.crop.name` | string | yes | Supported crop or local alias |
| `context.crop.variety` | string | no | Recorded and echoed back. It does not change FAO-56 parameters |
| `context.crop.season` | string | no | `kharif`, `rabi`, `zaid` (IN); `aus`, `aman`, `boro`, `rabi` (BD) |
| `context.crop.planted_at` | ISO datetime | no | Enables dated stage windows |
| `context.crop.growth_stage` | string | no | Free text such as `tillering`, `flowering` or `grain filling` |
| `as_of` | ISO date | no | Evaluation date for the stage calculation; never defaulted to server time |
| `areas` | array | no | Any of `irrigation`, `nutrients`, `soil`, `monitoring`, `sustainability` (default: all) |
| `measurements` | object | no | Must include `"data_classification": "synthetic"` in TEST |
| `measurements.soil_test` | object | no | `available_n_kg_ha`, `available_p_kg_ha`, `available_k_kg_ha`, `organic_carbon_pct`, `ph`, `ec_ds_m`, `sampled_at` |
| `measurements.soil_water` | object | no | `field_capacity_vwc_fraction`, `wilting_point_vwc_fraction`, `current_vwc_fraction`, `measured_at` |
| `measurements.irrigation_system` | object | no | `type`, `efficiency` (0–1] |
| `measurements.field_area_ha`, `.root_zone_depth_m` | number | no | Used for volumes and depletion |
| `measurements.stage_lengths_days` | 4 integers | no | Initial, development, mid-season and late-season lengths; required for a chickpea season schedule |

TEST rejects coordinates, polygons, observations, weather series, production
identifiers (`cycle_id`), unknown fields and control characters.

## Response (abridged)

| Field | Meaning |
|---|---|
| `id` | Deterministic per project and request; identical requests give identical responses |
| `contract_version` | `dmrv-uat/2` |
| `status`, `environment`, `synthetic`, `model_executed`, `billing.charged_cents` | `simulated`, `test`, `true`, `false`, `0` in TEST |
| `normalized_context` | Resolved country, state, district, crop, season, `current_stage`, `location_resolved`, `location_precision` |
| `geography` | Resolution result including the GeoNames id and representative point |
| `calendar` | Planting basis, stage lengths and source, computed vs reported stage, contradiction flag, stage windows |
| `water_balance` | Per-stage ET₀, Kc, ETc, rainfall, effective rainfall and net demand; season totals; peak demand (planning estimate) |
| `soil_reference` | Regional texture, pH, organic carbon, N, CEC, TAW/RAW ranges |
| `measured_soil_water`, `soil_test` | Results from your measurements, if supplied |
| `heat_risk` | Stage-month mean Tmax against a cited crop threshold |
| `coverage` | Which evidence classes were available |
| `structured_output` | `dmrv_advisory` schema: `summary`, `recommendations[]` (`category`, `action`, `rationale`, `priority`, `timing`, `requires_human_approval`, `evidence_ids`, `required_evidence`), `confidence`, `missing_data`, `limitations` |
| `evidence` | Cited sources: id, type, source, license, precision, dataset date |
| `calculations` | Every tool run: tool id and version, inputs, outputs, status |
| `reference_dataset` | Dataset version, generation time and SHA-256 |

A complete response for the request below is in
[`dmrv-advisory-example-response.json`](dmrv-advisory-example-response.json).
It was generated by the engine from the committed dataset, not written by hand.

## Errors

All errors are JSON with `detail`. Codes are stable.

| HTTP | `detail.code` | Meaning | Action |
|---|---|---|---|
| 401 | `authentication_required`, `invalid_api_key` | Missing or invalid key | Fix the credential |
| 403 | `scope_denied` | Key lacks `recommendations:read` | Create a key with the scope |
| 403 | `test_project_required` | A LIVE key was used on the TEST endpoint | Use the `agro_test_` key |
| 404 | `dmrv_preview_not_available` / `Not found` / `platform_api_disabled` | Organization not enabled, or preview disabled | Contact AGRO-AI |
| 422 | FastAPI validation list | Schema violation (missing selector, lowercase country, coordinates, non-synthetic measurements, …) | Fix the request |
| 422 | `location_state_not_found` | State not recognized; `resolution.suggestions` given | Correct the state |
| 422 | `location_district_not_found` | District not in that state; `resolution.suggestions` given | Correct the district |
| 422 | `location_state_mismatch` | District exists in other states; `resolution.candidates` lists them | Send the right state |
| 422 | `location_ambiguous` | Several districts match; `resolution.candidates` | Disambiguate |
| 422 | `location_country_not_supported` | Country not loaded (`IN`, `BD` today) | Contact AGRO-AI |
| 422 | `crop_not_supported` | `supported_crops` lists what is available | Use a supported crop |
| 422 | `measurement_invalid` | For example, field capacity ≤ wilting point | Fix the measurement |
| 429 | rate limit | Per-key route limit; see `Retry-After` / `X-RateLimit-*` | Back off |
| 5xx | — | Transient | Retry with backoff |

**Retries.** The TEST endpoint has no side effects and is deterministic, so
retrying is always safe. No `Idempotency-Key` is needed. Retry 429 and 5xx with
exponential backoff (1 s, 2 s, 4 s, 8 s; maximum 5 attempts). Do not retry 4xx
other than 429. When you report an issue, include the `X-Request-Id` response
header, never the key.

## Examples

```bash
curl -sS https://api.agroai-pilot.com/v1/platform/recommendations/preview \
  -H "Authorization: Bearer $AGROAI_TEST_KEY" -H "Content-Type: application/json" \
  -d '{
    "context": {
      "location": {"country": "IN", "state": "Uttar Pradesh", "district": "Gautam Buddha Nagar"},
      "crop": {"name": "wheat", "variety": "HD-2967", "season": "rabi",
               "planted_at": "2025-11-10T00:00:00Z", "growth_stage": "tillering"}
    },
    "as_of": "2025-12-20",
    "measurements": {
      "data_classification": "synthetic",
      "soil_test": {"available_n_kg_ha": 230, "available_p_kg_ha": 14, "available_k_kg_ha": 260, "organic_carbon_pct": 0.45, "ph": 8.3},
      "soil_water": {"field_capacity_vwc_fraction": 0.30, "wilting_point_vwc_fraction": 0.13, "current_vwc_fraction": 0.19},
      "irrigation_system": {"type": "furrow", "efficiency": 0.6},
      "field_area_ha": 1.5
    }
  }'
```

```python
import os, time, requests

URL = "https://api.agroai-pilot.com/v1/platform/recommendations/preview"
HEADERS = {"Authorization": f"Bearer {os.environ['AGROAI_TEST_KEY']}"}

def dmrv_preview(payload: dict) -> dict:
    for attempt in range(5):
        r = requests.post(URL, json=payload, headers=HEADERS, timeout=30)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(int(r.headers.get("Retry-After", 2 ** attempt)))
            continue
        if r.status_code == 422:
            detail = r.json()["detail"]
            raise ValueError(detail)  # dict with code/resolution, or a validation list
        r.raise_for_status()
        return r.json()
    raise RuntimeError("AGRO-AI preview unavailable after retries")

result = dmrv_preview({
    "context": {"location": {"country": "IN", "state": "Punjab", "district": "Ludhiana"},
                "crop": {"name": "rice", "season": "kharif"}},
    "areas": ["irrigation", "sustainability"],
})
evidence = {e["id"]: e for e in result["evidence"]} | {c["id"]: c for c in result["calculations"]}
for rec in result["structured_output"]["recommendations"]:
    print(rec["category"], rec["priority"], rec["action"])
    print("  evidence:", [evidence[i].get("source") or evidence[i].get("tool_id") for i in rec["evidence_ids"]])
```

## Coverage (dataset v1)

Precomputed climate and soil cover 40 districts: Gautam Buddha Nagar, Meerut,
Lucknow, Varanasi, Gorakhpur (UP); Ludhiana, Bathinda, Amritsar (PB); Karnal,
Hisar (HR); Jaipur, Bikaner, Ganganagar (RJ); Indore, Ujjain, Hoshangabad (MP);
Pune, Nashik, Nagpur, Yavatmal, Aurangabad (MH); Aurangabad, Patna, Purnia (BR);
Rajkot, Banaskantha (GJ); Mandya, Dharwad, Belgaum (KA); Thanjavur, Coimbatore
(TN); Guntur (AP); Nalgonda (TS); Nadia (WB); Cuttack (OD); Nagaon (AS); Palakkad
(KL); Bogra, Dinajpur, Mymensingh (BD).

Any other gazetteer district still resolves. Without precomputed climate and
soil, the response reports `coverage.climate=false`, lists the gap in
`missing_data` and sets confidence to `low`. Coverage can be extended on request
by adding districts to the dataset build.

## UAT scenarios and acceptance criteria

| # | Scenario | Pass condition |
|---|---|---|
| 1 | Wheat, Gautam Buddha Nagar, no measurements | 200; `water_balance.season_etc_mm` > 0; every `evidence_ids` resolves; `billing.charged_cents` = 0 |
| 2 | Rice vs wheat in the same district | Different `water_balance` and recommendations; rice includes the AWD/methane monitoring practice |
| 3 | Rice in Bikaner vs Nagaon | Bikaner net irrigation demand > Nagaon |
| 4 | Aurangabad with state Uttar Pradesh | 422 `location_state_mismatch` with Bihar and Maharashtra candidates |
| 5 | Allahabad, Uttar Pradesh | Resolves to Prayagraj with `match_method: rename_alias` |
| 6 | Unsupported crop (`quinoa`) | 422 `crop_not_supported` with `supported_crops` |
| 7 | Synthetic soil water with current moisture below RAW | First irrigation recommendation reports the trigger, refill depth and gross depth from efficiency |
| 8 | Synthetic soil test with low N | Nutrient recommendation is high priority, cites the soil test, and states no dose |
| 9 | `growth_stage: harvest` with `planted_at` 25 days before `as_of` | `calendar.stage_contradiction: true`, confidence `low` |
| 10 | Identical request twice | Identical `id` and body |
| 11 | `measurements.data_classification: "production"` | 422 |
| 12 | Coordinates or observations in `context` | 422 |

## Limitations

- District values describe a regional point; they are not field evidence.
- Climate is long-term monthly means, not current weather or forecasts.
- FAO-56 tabulated parameters assume standard conditions and are not
  variety-specific.
- Paddy crop ET excludes land preparation, ponding and percolation.
- No fertilizer dose, carbon quantity or emissions outcome is calculated or
  verified. DMRV claims require an approved methodology and independent
  verification.

## Versioning

`contract_version` changes on a breaking change. New optional response fields
may be added within a version. Reference data changes are visible through
`reference_dataset.sha256`.
