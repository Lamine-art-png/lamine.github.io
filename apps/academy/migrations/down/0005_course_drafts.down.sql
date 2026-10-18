-- Reverses 0005_course_drafts.sql. Unpublished draft edits and revision history are lost; export first.
DROP TABLE IF EXISTS course_revisions;
DROP TABLE IF EXISTS draft_courses;
DROP TABLE IF EXISTS draft_course_instructors;
DROP TABLE IF EXISTS draft_course_prerequisites;
DROP TABLE IF EXISTS draft_modules;
DROP TABLE IF EXISTS draft_lessons;
DROP TABLE IF EXISTS draft_lesson_resources;
DROP TABLE IF EXISTS draft_assessments;
DROP TABLE IF EXISTS draft_question_banks;
DROP TABLE IF EXISTS draft_question_cases;
DROP TABLE IF EXISTS draft_questions;
DROP TABLE IF EXISTS draft_assessment_rules;
ALTER TABLE modules DROP COLUMN status;
ALTER TABLE assessments DROP COLUMN removed_at;
ALTER TABLE questions DROP COLUMN removed_at;
