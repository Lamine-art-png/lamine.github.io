# Field Vision ground-truth annotation guidelines

Schema: `field-vision-ground-truth/1` · Scorer: `python -m evals.field_vision.validation_gate`

These guidelines turn issue #352 into a repeatable procedure. A record is
one reviewed observation. The scorer never decides agronomic correctness by
string matching; the qualified reviewer does, using the rules below.

## 1. Before any capture

- **Consent and licensing.** Every record needs `consent.basis`:
  `customer_written_consent` (signed, scoped to evaluation),
  `internal_staff_capture` (AGRO-AI staff on authorized land), or
  `licensed_dataset` (a dataset whose license allows commercial evaluation).
  Keep the consent reference (`consent.reference`) in the private evidence
  store, not in the repository.
- **No production resources.** Capture against isolated staging only. Never
  copy customer media, transcripts, or tenant identifiers into this
  repository. Records stored here must be pseudonymous.
- **Split before scoring.** Assign `split` (`train`, `calibration`, `test`)
  by `grouping.grower`, `grouping.site`, `grouping.season`, and
  `grouping.device_group` *before* anyone looks at model output. A grower,
  site, or device group may appear in only one split; the scorer reports any
  overlap as leakage and the gate fails.

## 2. Required composition (test split)

At least 50 observations: 20 `walk_video` with simultaneous speech, 15
`photo`, 10 `voice`, 5 `offline` (captured offline, uploaded after
reconnecting). Vary device, distance, lighting, motion, crop and field
context, and include healthy conditions, visible stress, equipment or
coverage issues, and deliberately ambiguous evidence. Include reviewer-
confirmed visible issues and at least one high or critical case: with none,
issue recall and the high-severity confirmation check are `NOT MEASURED` and
the gate cannot pass.

## 3. Reviewer qualification

`reviewer.qualification` is one of `agronomist`, `certified_crop_adviser`,
`pest_control_adviser`, or `trained_scout_supervised`. Record the reviewer's
pseudonymous id. The reviewer labels the reference *before* reading the
model output.

## 4. Media quality

- `clear`: subject in focus, well lit, unobstructed, close enough to see the
  claimed detail.
- `usable`: some blur, glare, distance, or occlusion, but the main subject
  can still be judged.
- `poor`: the subject cannot reliably be judged (dark, heavily blurred,
  lens obstruction, wrong subject).

Visible-fact precision is scored on `clear` and `usable` records only.

## 5. Reference labels (reviewer, blind to model output)

- `reference.visible_facts`: what can be seen, with no inferred cause
  ("yellowing on lower leaves of 3 plants", not "nitrogen deficiency").
- `reference.issues`: each visible issue with `category`, `severity`
  (`info|low|medium|high|critical`) and, after the model output is revealed,
  `detected_by_model` (true when the model's facts or hypotheses identify
  the same issue at the same location, whatever the wording).
- `reference.evidence_insufficient`: true when the media cannot support any
  conclusion about the issue.
- `reference.recommended_next_check`: the safe verification step the
  reviewer would take.

Severity rubric:

| Severity | Meaning |
|---|---|
| info | No action needed; context only. |
| low | Note and monitor at the next routine visit. |
| medium | Inspect within days; could affect yield or quality if it spreads. |
| high | Inspect within 24–48 h; likely material loss, safety, or water waste. |
| critical | Immediate action; active safety hazard, major leak, or rapid loss. |

## 6. Judging the model output (after the reference is fixed)

- Each `model.visible_facts[]` item gets `judgment`:
  `correct` (visible and accurately described), `incorrect` (contradicted
  by the media), or `unsupported` (cannot be established from the media).
- `flags.unsupported_certainty`: the model stated a diagnosis, cause, or
  outcome as confirmed when the media only supports a hypothesis.
- `flags.chemical_numeric_claim`: the model stated a concentration, residue,
  dosage, active ingredient, laboratory value, soil chemistry, or internal
  plant chemistry. The scorer also runs the runtime detector over the
  model text and counts either signal.
- `recommendation_review.useful` and `.safe` are both required booleans.
  Unsafe means it could cause harm if followed without verification
  (for example a product or dose, or skipping a safety check).
- Copy `model.severity`, `model.confidence`, `model.analysis_state`, and
  `model.human_review_required` exactly from the stored analysis.

## 7. Latency

- `latency.first_live_result_ms`: from live capture start to the first
  sampled result on screen. Set `latency.stable_connection` to true only
  when the device had a stable connection for the whole capture.
- `latency.durable_result_ms`: from upload completion to the durable
  multimodal result being visible.

## 8. What the scorer will not do

It will not report a metric from synthetic or unreviewed data, and it
reports `NOT MEASURED` or `INSUFFICIENT SAMPLE` rather than a number when
the eligible sample is empty or below the metric's minimum. Larger
independent held-out datasets and crop-specific metrics are required before
any specialized detection, ripeness, or harvest-forecast claim.
