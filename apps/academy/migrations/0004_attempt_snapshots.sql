-- Attempt snapshots: an attempt keeps the exact questions, answer keys,
-- scoring settings and assessment policy it started with, so later edits to
-- an assessment never reinterpret an open or historical attempt.
-- Reverse with migrations/down/0004_attempt_snapshots.down.sql. Additive only.

-- {kind, passing_score, time_limit_seconds, feedback_policy, is_certification}
ALTER TABLE attempts ADD COLUMN policy_json TEXT;
-- {type, prompt, data_json, answer_json, explanation, rubric, grading, points,
--  lesson_id, case_title, case_body, translation} as presented to the learner.
ALTER TABLE attempt_answers ADD COLUMN question_json TEXT;
