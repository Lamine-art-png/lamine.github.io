-- Publication controls: mandatory course reviews and the instructor-video policy.
-- Reverse with migrations/down/0003_publication_controls.down.sql.
-- Additive only: no existing rows are changed or removed.

-- 'required': every planned lesson video must be approved, playable and captioned
-- before publication. 'optional' needs a recorded reason (shown in readiness checks).
ALTER TABLE courses ADD COLUMN video_requirement TEXT NOT NULL DEFAULT 'required' CHECK (video_requirement IN ('required','optional'));
ALTER TABLE courses ADD COLUMN video_waiver_reason TEXT;

-- Append-only review decisions. The latest decision per (course, type) is the
-- current one; an approval applies only while content_hash matches the course.
CREATE TABLE course_reviews (
  id            TEXT PRIMARY KEY,
  course_id     TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
  review_type   TEXT NOT NULL CHECK (review_type IN ('academic','assessment','accessibility')),
  decision      TEXT NOT NULL CHECK (decision IN ('approved','changes_requested')),
  reviewer_id   TEXT REFERENCES users(id) ON DELETE SET NULL,
  reviewer_name TEXT,
  notes         TEXT NOT NULL DEFAULT '',
  content_hash  TEXT NOT NULL,
  created_at    TEXT NOT NULL
);
CREATE INDEX course_reviews_course ON course_reviews(course_id, review_type, created_at);
