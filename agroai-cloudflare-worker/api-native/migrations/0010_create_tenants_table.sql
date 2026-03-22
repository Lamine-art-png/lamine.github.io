-- Create tenants table (was previously created by WiseConn migrations 0001-0005
-- which are not part of this project).
-- This table is the FK target for integrations_talgil.tenant_id.

CREATE TABLE IF NOT EXISTS tenants (
  id   TEXT PRIMARY KEY,
  name TEXT
);
