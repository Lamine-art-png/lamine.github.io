-- The deploy reflows unreviewed machine caption drafts for readability (line
-- length, cue duration, reading time; the words are never changed). The
-- draft as Stream produced it is kept in source_vtt, and reflowed_at records
-- when the reflow ran. A draft is reflowed at most once, so a reviewer's
-- edits are never overwritten; reviewed captions are never touched.
ALTER TABLE video_captions ADD COLUMN source_vtt TEXT;
ALTER TABLE video_captions ADD COLUMN reflowed_at TEXT;
