from pathlib import Path

path = Path(__file__).with_name("apply_field_intelligence_v3_patch.py")
text = path.read_text(encoding="utf-8")

old_fr = '"fieldIntel.recordingReady": "Prêt à enregistrer"'
new_fr = '"fieldIntel.recordingReady": "Enregistrement prêt"'
fr_count = text.count(old_fr)
if fr_count != 2:
    raise RuntimeError(f"Expected the guarded old/new French anchors, found {fr_count}")
# The first occurrence is the exact source anchor; the second is replacement output.
text = text.replace(old_fr, new_fr, 1)

old_root = 'ROOT = Path(__file__).resolve().parents[2]'
new_root = 'ROOT = Path(__file__).resolve().parents[1]'
root_count = text.count(old_root)
if root_count != 1:
    raise RuntimeError(f"Expected one backend contract root anchor, found {root_count}")
text = text.replace(old_root, new_root, 1)

path.write_text(text, encoding="utf-8")
print("Repaired Field Intelligence guarded patch anchors")
