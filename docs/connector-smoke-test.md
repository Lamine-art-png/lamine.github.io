# Connector Smoke Test

After deployment, test these flows.

## Files

- Open Connectors.
- Open Files.
- Use sample file or upload a CSV.
- Expected: rows parse, evidence records are created, and the Evidence page shows records.

## Gmail

- Open Gmail.
- Connect Gmail.
- Expected in internal mode: the connection is marked connected. Real provider authorization can replace this when OAuth client IDs are configured.

## WiseConn and Talgil

- Open WiseConn or Talgil.
- Save connection details or use the sample export.
- Expected: credentials are sanitized, connection is saved, uploads create evidence.

## Weather and OpenET

- Save provider details.
- Upload sample export where available.
- Expected: connection is saved and uploaded rows create evidence.

## Data provider API

- Add provider name, provider URL, access method, and credential reference.
- Connect provider.
- Expected: connection is marked connected and an ingestion job is recorded.

## Audit endpoints

- GET /v1/connectors/data-sources
- GET /v1/connectors/jobs
- GET /v1/connectors/connections/{id}/data
