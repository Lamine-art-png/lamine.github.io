-- Reverts 0012_caption_source.sql: unreviewed drafts go back to the text
-- Stream produced; reviewed captions (a person's work) are left as they are.
UPDATE video_captions SET vtt = source_vtt WHERE status = 'machine' AND source_vtt IS NOT NULL;
ALTER TABLE video_captions DROP COLUMN reflowed_at;
ALTER TABLE video_captions DROP COLUMN source_vtt;
