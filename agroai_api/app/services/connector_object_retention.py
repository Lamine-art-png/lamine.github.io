from __future__ import annotations


def gc_candidate(job) -> tuple[str, str] | None:
    inputs = dict(job.input_json or {})
    outputs = dict(job.output_json or {})
    if job.status in {"failed", "cancelled"}:
        uri = str(inputs.get("object_uri") or "")
        return (uri, "terminal_job") if uri else None
    if job.status == "succeeded" and outputs.get("deduplicated") is True and outputs.get("redundant_object_deleted") is False:
        uri = str(outputs.get("object_uri") or "")
        return (uri, "duplicate_cleanup_retry") if uri else None
    return None
