CREATE TABLE IF NOT EXISTS terris_field_events (
  seq BIGSERIAL PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  event_id UUID NOT NULL,
  idempotency_key TEXT NOT NULL,
  event_type TEXT NOT NULL,
  field_id TEXT NOT NULL,
  crop_cycle_id TEXT,
  truth_label TEXT NOT NULL CHECK (truth_label IN ('measured','reported','calculated','estimated','ai_inferred','unknown')),
  source TEXT NOT NULL,
  observed_at TIMESTAMPTZ NOT NULL,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
  training_consent BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (tenant_id, event_id),
  UNIQUE (tenant_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_terris_field_events_tenant_field_time
  ON terris_field_events (tenant_id, field_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_terris_field_events_training
  ON terris_field_events (tenant_id, training_consent, observed_at)
  WHERE training_consent = TRUE;

REVOKE UPDATE, DELETE ON terris_field_events FROM PUBLIC;
