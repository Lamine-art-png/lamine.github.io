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
| `FIELD_DETECTION_TIMEOUT_SECONDS` | 30 | Per-frame wall-clock budget. The HTTP exchange (DNS, connect, upload, headers, body) runs on a helper thread and the worker waits only until the deadline, then records `detector_frame_time_budget_exceeded`. httpx's timeouts apply to each socket operation, so without this a slow uplink, trickled headers, body or trailers, or a stream of informational (1xx) responses could hold a frame indefinitely. The abandoned exchange stops at its next chunk (upload and body are checked against the deadline) or socket timeout; its socket is never closed from another thread. A detector that floods 1xx responses could keep that helper thread alive, which is one more reason the detector must be self-hosted and allowlisted. Responses over 4 MB are refused. |
| `FIELD_DETECTION_MAX_FRAMES_PER_OBSERVATION` | 8 (max 8) | Frames sent per observation. |
| `FIELD_DETECTION_OBSERVATION_BUDGET_SECONDS` | 60 (5 to 300) | Hard wall-clock budget for the detection stage of one observation. No frame starts with less than 2 s left, and each frame's HTTP budget is clamped to the time remaining, so the worker gets the stage back by the deadline (plus thread scheduling). Unsent frames are recorded as `time_budget` skips. |
| `FIELD_DETECTION_DAILY_FRAME_BUDGET` | 200 per organization | Frames per organization per UTC day. Reserved atomically before any frame is sent (see below). |

### How the daily budget is enforced (`app/services/field_detection_quota.py`)

1. A transaction-scoped PostgreSQL advisory lock keyed by organization serializes reservations, so concurrent workers take turns.
2. Frames used today are counted from `detection` processing runs. A run still `reserved` counts its reserved frames; a finished run counts the frames it actually sent.
3. A `reserved` run for the granted frames is committed in its own short transaction before any frame is sent. If the worker crashes, or its pipeline rolls back or is retried, the reservation stays and keeps counting. The pipeline's own transaction is not committed early.
4. After sending, the same run records `frames_sent`, the outcome and the latency.

Tests: `test_field_intelligence_postgres.py` proves on real PostgreSQL that 4 concurrent workers requesting 3 frames each against a budget of 5 are granted exactly 5 in total, and that a reservation survives a pipeline rollback. The pipeline tests prove the reservation exists before the first frame is sent and that no frame starts after the time budget. `test_field_detection.py` runs real local servers that trickle the body, trickle the headers, trickle trailers after a fast body, or flood 100 Continue responses: each frame comes back failed at its 1 s deadline (before these fixes they took up to about 7 s, and the trailer case returned success after the deadline).

Detections never change an observation's severity or status. Results are
stored as unreviewed evidence, and the model is labelled
`unregistered_unverified` unless its id, version and crop are in the registry
**and** its registered weights digest matches both the digest the deployment
attested (`FIELD_DETECTION_ATTESTED_WEIGHTS_SHA256`, from the locked deployment
manifest) and the digest the detector reports loading. Any mismatch is recorded
as `verification_failure` (`deployment_weights_not_attested`,
`deployment_weights_digest_mismatch` or `reported_weights_digest_mismatch`).

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
   Deployed-weight attestation: the detector deployment pins the weights by
   SHA-256 in a locked manifest, the detector service refuses to start if its
   loaded weights do not match and reports that digest, and the API's
   `FIELD_DETECTION_ATTESTED_WEIGHTS_SHA256` is set from the same manifest. A
   self-reported name and version alone never counts as validated.
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
