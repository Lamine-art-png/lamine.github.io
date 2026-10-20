-- Early-access registrants from agroai-pilot.com/academy/early-access (stored by
-- the Platform API before the Academy existed). Imported by a super
-- administrator; importing never creates an account, a password or a verified
-- address. A registrant is linked to an account only after that person
-- registers and proves the mailbox, and is invited at most once.
CREATE TABLE early_access_registrants (
  id                TEXT PRIMARY KEY,
  source            TEXT NOT NULL DEFAULT 'agroai-pilot.com/academy/early-access',
  source_id         TEXT,
  email             TEXT NOT NULL,
  name              TEXT,
  locale            TEXT,
  professional_role TEXT,
  email_opt_in      INTEGER NOT NULL DEFAULT 0,
  registered_at     TEXT NOT NULL,
  imported_at       TEXT NOT NULL,
  imported_by       TEXT,
  status            TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'invited', 'activated')),
  invited_at        TEXT,
  activated_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  activated_at      TEXT
);
CREATE UNIQUE INDEX early_access_email ON early_access_registrants(email);
CREATE UNIQUE INDEX early_access_source ON early_access_registrants(source, source_id) WHERE source_id IS NOT NULL;
CREATE INDEX early_access_status ON early_access_registrants(status);
