-- Reverts 0012_caption_source.sql: an unreviewed draft that is still the
-- reflow output (reflowed_at set) goes back to the text Stream produced. A
-- draft a person has edited since (saving clears reflowed_at) and reviewed
-- captions are left as they are.
UPDATE video_captions SET vtt = source_vtt WHERE status = 'machine' AND source_vtt IS NOT NULL AND reflowed_at IS NOT NULL;
ALTER TABLE video_captions DROP COLUMN reflowed_at;
ALTER TABLE video_captions DROP COLUMN source_vtt;
