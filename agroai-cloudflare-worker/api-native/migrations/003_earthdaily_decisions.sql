CREATE TABLE IF NOT EXISTS earthdaily_decisions (
  decision_id TEXT PRIMARY KEY,
  field_id TEXT NOT NULL,
  provider TEXT NOT NULL,
  mode TEXT NOT NULL,
  input_hash TEXT NOT NULL,
  recommendation_action TEXT NOT NULL,
  priority TEXT NOT NULL,
  confidence_score REAL NOT NULL,
  rules_version TEXT NOT NULL,
  model_version TEXT NOT NULL,
  decision_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_eds_decisions_field ON earthdaily_decisions(field_id);

CREATE TABLE IF NOT EXISTS earthdaily_audit (
  audit_id TEXT PRIMARY KEY,
  decision_id TEXT NOT NULL,
  step TEXT NOT NULL,           -- 'normalize'|'decide'|'report'|'llm'|'live_fetch'|'demo_fallback'
  status TEXT NOT NULL,         -- 'ok'|'error'|'fallback'
  duration_ms INTEGER NOT NULL,
  request_id TEXT NOT NULL,
  meta_json TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (decision_id) REFERENCES earthdaily_decisions(decision_id)
);
CREATE INDEX IF NOT EXISTS idx_eds_audit_decision ON earthdaily_audit(decision_id);

