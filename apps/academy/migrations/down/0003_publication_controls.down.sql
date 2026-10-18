-- Reverses 0003_publication_controls.sql. Destroys recorded review decisions; export first.
DROP TABLE IF EXISTS course_reviews;
ALTER TABLE courses DROP COLUMN video_waiver_reason;
ALTER TABLE courses DROP COLUMN video_requirement;
