# Field Intelligence — Commercial Capability Matrix (Proposed → Implemented)

This document records the deliberate packaging decision for Field
Intelligence, replacing the incidental defaults that shipped with the
feature branch. Server-side enforcement lives in
`app/services/commercial_control.py`; the portal only mirrors it.

## Design principles

- Typed + photo capture is the free hook: every operator can record what
  they see, so the data network grows.
- Voice and AI model extraction are the paid differentiators: they carry
  real provider costs (transcription minutes, model tokens).
- Offline sync stays available on every plan — a field tool that loses
  notes when coverage drops is not a product.
- Storage/retention scale with plan; enterprise governs audit and custom
  retention.
- The rollout release-state gate (disabled/internal/canary/general) sits
  ABOVE all of this and is never granted by a plan.

## Matrix (implemented in BASE_ENTITLEMENTS)

| Capability | Free | Professional | Team | Network/Enterprise |
|---|---|---|---|---|
| Typed + photo capture | ✅ | ✅ | ✅ | ✅ |
| Offline sync | ✅ | ✅ | ✅ | ✅ |
| Field map | ✅ | ✅ | ✅ | ✅ |
| Voice capture + transcription | 25 notes/mo | ✅ unlimited* | ✅ | ✅ |
| AI model extraction | deterministic only | ✅ model-routed | ✅ | ✅ |
| Storage quota | 512 MB | 10 GB | 25 GB | 100 GB (contract) |
| Retention controls (delete media) | ✅ | ✅ | ✅ | ✅ + custom policies |
| Enterprise audit view | — | — | ✅ read | ✅ full |
| API/white-label access | — | — | — | contract_only |

*subject to fair-use transcription minute metering (future metering key
`quota.field_intelligence.voice_notes.monthly`, already enforced for Free).

## Entitlement keys

- `field_intelligence.capture` — typed/photo capture routes
- `field_intelligence.voice` — voice capture + transcription pipeline
- `field_intelligence.offline_sync` — `/sync/batch`
- `field_intelligence.map` — `/map`
- `field_intelligence.extraction` — extraction stage; `model_extraction`
  state (`enabled` vs `deterministic`) selects the model path
- `field_intelligence.model_extraction` — model-routed extraction (paid)
- `field_intelligence.retention` — deletion/retention surface
- `field_intelligence.audit` — enterprise audit surface
- `quota.field_intelligence.storage_mb` — physical-object storage quota
- `quota.field_intelligence.voice_notes.monthly` — Free-plan voice cap

## What changed from the incidental defaults

| Key | Old Free default | New Free default | Rationale |
|---|---|---|---|
| `field_intelligence.model_extraction` | (absent → model ran for all) | `locked` | model tokens are a paid cost |
| `quota.field_intelligence.voice_notes.monthly` | (absent → unlimited) | `25` | transcription minutes are a paid cost |
| `field_intelligence.audit` | (absent) | `locked` (Team: `enabled`) | governance is an enterprise feature |

Stripe/billing state, admin overrides, suspended-account enforcement and
the canary rollout gate are untouched. Existing paying organizations are
unaffected (professional and above keep full voice + model extraction).
