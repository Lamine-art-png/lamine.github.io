from pathlib import Path

OLD = "345bc3b89b1cbf8f6f540a29d325e9d1be8476d4"
NEW = "1034dcb47ef37ecaf7be3fef515500779c575f66"

path = Path("render.yaml")
text = path.read_text(encoding="utf-8")
if OLD not in text:
    raise SystemExit("expected previous SHA not found in render.yaml")
path.write_text(text.replace(OLD, NEW), encoding="utf-8")

print(f"Blueprint exact head updated to {NEW}")
