"""Server-side registry of verified crop detectors and their evaluations.

Verification is never self-attested. A detector's own ``model.id`` or
``license`` string, or a ``detector_validation_id`` supplied by an API
client, proves nothing by itself. Only the entries in this module, which are
versioned with the application and change through code review, count as
verified. Everything else is labelled user-supplied or upstream-reported and
unverified.

An evaluation may be added only with a held-out dataset whose splits are
grouped by grower, site, season and device, metrics computed by
``evals/field_vision``, a committed report, and a named qualified reviewer.

Both registries are deliberately empty: no detector has such an evaluation.
"""
from __future__ import annotations

from dataclasses import dataclass, field

REGISTRY_VERSION = "crop-model-registry/1"


@dataclass(frozen=True)
class VerifiedEvaluation:
    evaluation_id: str
    model_id: str
    model_version: str
    crop_id: str
    dataset: str           # held-out dataset identity and version
    split_policy: str      # how leakage was prevented
    report_ref: str        # repository path of the committed evaluation report
    reviewed_by: str       # qualified reviewer
    metrics: dict = field(default_factory=dict)


@dataclass(frozen=True)
class VerifiedDetector:
    model_id: str
    version: str
    license: str           # verified license of weights and code
    weights_sha256: str
    crop_ids: tuple[str, ...]
    evaluation_id: str


VERIFIED_EVALUATIONS: tuple[VerifiedEvaluation, ...] = ()
VERIFIED_DETECTORS: tuple[VerifiedDetector, ...] = ()


def verified_evaluation(evaluation_id: str | None) -> VerifiedEvaluation | None:
    if not evaluation_id:
        return None
    return next((item for item in VERIFIED_EVALUATIONS if item.evaluation_id == evaluation_id), None)


def verified_detector(model_id: str | None, version: str | None) -> VerifiedDetector | None:
    if not model_id or not version:
        return None
    return next((item for item in VERIFIED_DETECTORS if item.model_id == model_id and item.version == version), None)
