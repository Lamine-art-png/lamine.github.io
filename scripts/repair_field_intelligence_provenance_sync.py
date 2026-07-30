from pathlib import Path

path = Path(__file__).resolve().parents[1] / "agroai_api/app/services/field_intelligence_vision_extension.py"
text = path.read_text(encoding="utf-8")

old = '''        session = db.get(FieldCaptureSession, observation.capture_session_id)\n        _repair_text_inference(svc, observation)\n\n        assets = (\n'''
new = '''        session = db.get(FieldCaptureSession, observation.capture_session_id)\n        _repair_text_inference(svc, observation)\n        # The original text pipeline may already have mirrored evidence before\n        # the extension repairs provider/model provenance. Refresh immediately so\n        # text-only captures and transcript corrections remain audit-consistent.\n        svc._refresh_linked_evidence(db, observation)\n\n        assets = (\n'''
if text.count(old) != 1:
    raise RuntimeError(f"expected one post-inference evidence anchor, found {text.count(old)}")
text = text.replace(old, new, 1)

old = '''            svc._audit(\n                observation,\n                "vision_analysis_unavailable",\n                actor="system",\n                details={"asset_ids": asset_ids, "read_errors": read_errors, "frame_errors": frame_errors},\n            )\n            db.flush()\n            return\n'''
new = '''            svc._audit(\n                observation,\n                "vision_analysis_unavailable",\n                actor="system",\n                details={"asset_ids": asset_ids, "read_errors": read_errors, "frame_errors": frame_errors},\n            )\n            # The failure provenance is also part of the evidence audit trail.\n            svc._refresh_linked_evidence(db, observation)\n            db.flush()\n            return\n'''
if text.count(old) != 1:
    raise RuntimeError(f"expected one no-media evidence anchor, found {text.count(old)}")
text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")
print("Field Intelligence evidence provenance synchronization repaired")
