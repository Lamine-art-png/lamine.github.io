# Specialized crop detection: release controls

Status: **disabled**. No detector is registered in
`app/services/crop_model_registry.py`, so detection must not be enabled for
customers. This page lists what has to be true first, and how to stop it.

## Controls (all server-side environment settings)

| Setting | Default | Effect |
|---|---|---|
| `FIELD_DETECTION_ENABLED` | off | Global kill switch. Off means no detector call anywhere. |
| `FIELD_DETECTION_ORG_ALLOWLIST` | empty | Comma-separated organization ids allowed to run detection. Empty means none (fail closed). |
| `FIELD_DETECTION_ENDPOINT` / `FIELD_DETECTION_API_KEY` | unset | Self-hosted inference endpoint (https only, no embedded credentials). Missing values keep detection off. |
| `FIELD_DETECTION_TIMEOUT_SECONDS` | 30 | Per-frame HTTP timeout. |
| `FIELD_DETECTION_MAX_FRAMES_PER_OBSERVATION` | 8 (max 8) | Frames sent per observation. |
| `FIELD_DETECTION_OBSERVATION_BUDGET_SECONDS` | 60 (5 to 300) | Wall-clock budget per observation; later frames are recorded as skipped. |
| `FIELD_DETECTION_DAILY_FRAME_BUDGET` | 200 per organization | Frames per organization per UTC day, counted from `detection` processing runs. |

Detections never change an observation's severity or status. Results are
stored as unreviewed evidence, and the model is labelled
`unregistered_unverified` unless its id, version and crop are in the registry.

## Cost model (not measured)

Per analysed field visit: `frames × (inference cost per frame + transfer)`.
With the defaults, the most a single organization can send is 200 frames per day.
Per-frame inference cost and p50/p95 latency are **NOT MEASURED**, because no
detector has been deployed. They must be measured on the chosen hardware with
`evals/field_vision/detection_eval.py` inputs before any capacity or price
commitment.

## Enablement checklist (each item needs evidence, in order)

1. Licensed weights. Code and weights have a license that allows commercial
   use. RT-DETR/RT-DETRv2, D-FINE and YOLOX code is Apache-2.0. Check the
   pretraining datasets' terms separately. Ultralytics YOLO is AGPL-3.0 unless
   an enterprise license is held.
2. Consented, crop-specific data. A held-out test split is grouped by grower,
   site, season and device (at least 50 images from at least 3 growers).
   `detection_eval.py` reports `MEASURED` (not `INSUFFICIENT SAMPLE`) for every
   label used.
3. Registry entry. The `VerifiedEvaluation` and `VerifiedDetector` records are
   added by code review, cite the committed report, and name the reviewer.
4. Staging. `field-intelligence-staging.yml` passes in `qualify` mode and then
   `deploy` mode for the exact SHA. The staging contract still refuses
   `FIELD_STAGING_DETECTION_ENABLED` until step 3 is done.
5. Canary. One internal or consenting organization is added to the allowlist,
   with a reviewer checking stored detections on real field visits.
6. Approval. The owner explicitly approves wider rollout.

## Stopping it

Set `FIELD_DETECTION_ENABLED` to false, or remove the organization from the
allowlist. Both take effect on the next processed observation, and stored
detections stay as reviewable history.
