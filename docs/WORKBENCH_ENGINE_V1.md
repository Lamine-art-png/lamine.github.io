# Workbench Engine v1

- Real backend compute over uploaded/live context.
- Supported input: CSV, JSON, TXT, XLSX (XLSX requires `openpyxl`).
- Deterministic engine always available (`model_status: deterministic_engine`).
- Optional model-assisted summary when provider env vars are present.
- No permanent upload storage in v1 (in-memory session artifacts only).
- Live analysis uses source/entity context and preserves customer-safe errors.
