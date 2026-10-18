-- Reverses 0004_attempt_snapshots.sql. Attempts lose their snapshots; export first.
ALTER TABLE attempt_answers DROP COLUMN question_json;
ALTER TABLE attempts DROP COLUMN policy_json;
