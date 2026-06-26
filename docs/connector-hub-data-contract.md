# AGRO-AI Connector Hub Data Contract

This document defines the working contract for connector data in AGRO-AI.

## Core objects

### ConnectorConnection
One row per provider connection per tenant/workspace. Stores provider, mode, status, sanitized configuration, credential reference hash, test/sync timestamps, and last error.

### DataSource
One row per uploaded or imported source. Stores filename, content type, storage path, raw text preview, parse metadata, mapping suggestions, and status.

### IngestionJob
One row per connector action. Stores connection tests, OAuth starts, API/custom connection saves, file parse jobs, sync attempts, warnings, and output metadata.

### EvidenceRecord
Normalized operational facts that AGRO-AI can cite. Evidence records are produced from uploads and later live sync jobs. They include type, field/block, timestamp, summary, values, quality status, confidence, source excerpt, and citation label.

## Current working patterns

1. Controllers: WiseConn and Talgil support API credential setup plus export upload.
2. Files: CSV/JSON/TXT/PDF uploads are stored, parsed, and normalized into evidence.
3. Accounts: Gmail, Outlook, and Google Drive are connectable in internal mode now. Production OAuth can replace the internal connector once provider client IDs are configured.
4. Data providers: Weather, OpenET, and custom APIs store provider URL/access metadata and credential references for future live sync jobs.

## Storage

Uploads are stored under `CONNECTOR_UPLOAD_DIR`, defaulting to `/tmp/agroai_uploads`. This is enough for internal testing and Render preview. Production should move to persistent object storage such as S3/R2/Render Disk with the same `DataSource.storage_path` abstraction.

## Security

Raw secrets are not stored in `config_json`; secret-like fields are sanitized. `credentials_ref` stores only a hashed reference with last-four metadata. Production should replace this with a real vault/KMS-backed credential reference.
