from pathlib import Path

path = Path(__file__).with_name("apply_field_intelligence_v3_patch.py")
text = path.read_text(encoding="utf-8")
old = '"fieldIntel.recordingReady": "Prêt à enregistrer"'
new = '"fieldIntel.recordingReady": "Enregistrement prêt"'
count = text.count(old)
if count != 2:
    raise RuntimeError(f"Expected the guarded old/new French anchors, found {count}")
# The first occurrence is the exact source anchor; the second is replacement output.
path.write_text(text.replace(old, new, 1), encoding="utf-8")
print("Repaired French Field Intelligence catalog source anchor")
