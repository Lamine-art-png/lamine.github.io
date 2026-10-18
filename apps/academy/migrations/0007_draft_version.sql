-- Publication is bound to the exact draft that passed readiness. Every write
-- to a draft table bumps draft_state.version (in the same statement, through
-- triggers); readiness reads the version before fingerprinting the draft, and
-- the publication batch aborts if the version has moved in the meantime.
-- Reverse with migrations/down/0007_draft_version.down.sql.
CREATE TABLE draft_state (
  id      INTEGER PRIMARY KEY CHECK (id = 1),
  version INTEGER NOT NULL
);
INSERT INTO draft_state (id, version) VALUES (1, 0);

CREATE TRIGGER draft_courses_insert_version AFTER INSERT ON draft_courses BEGIN UPDATE draft_state SET version = version + 1 WHERE id = 1; END;
CREATE TRIGGER draft_courses_update_version AFTER UPDATE ON draft_courses BEGIN UPDATE draft_state SET version = version + 1 WHERE id = 1; END;
CREATE TRIGGER draft_courses_delete_version AFTER DELETE ON draft_courses BEGIN UPDATE draft_state SET version = version + 1 WHERE id = 1; END;
CREATE TRIGGER draft_course_instructors_insert_version AFTER INSERT ON draft_course_instructors BEGIN UPDATE draft_state SET version = version + 1 WHERE id = 1; END;
CREATE TRIGGER draft_course_instructors_update_version AFTER UPDATE ON draft_course_instructors BEGIN UPDATE draft_state SET version = version + 1 WHERE id = 1; END;
CREATE TRIGGER draft_course_instructors_delete_version AFTER DELETE ON draft_course_instructors BEGIN UPDATE draft_state SET version = version + 1 WHERE id = 1; END;
CREATE TRIGGER draft_course_prerequisites_insert_version AFTER INSERT ON draft_course_prerequisites BEGIN UPDATE draft_state SET version = version + 1 WHERE id = 1; END;
CREATE TRIGGER draft_course_prerequisites_update_version AFTER UPDATE ON draft_course_prerequisites BEGIN UPDATE draft_state SET version = version + 1 WHERE id = 1; END;
CREATE TRIGGER draft_course_prerequisites_delete_version AFTER DELETE ON draft_course_prerequisites BEGIN UPDATE draft_state SET version = version + 1 WHERE id = 1; END;
CREATE TRIGGER draft_modules_insert_version AFTER INSERT ON draft_modules BEGIN UPDATE draft_state SET version = version + 1 WHERE id = 1; END;
CREATE TRIGGER draft_modules_update_version AFTER UPDATE ON draft_modules BEGIN UPDATE draft_state SET version = version + 1 WHERE id = 1; END;
CREATE TRIGGER draft_modules_delete_version AFTER DELETE ON draft_modules BEGIN UPDATE draft_state SET version = version + 1 WHERE id = 1; END;
CREATE TRIGGER draft_lessons_insert_version AFTER INSERT ON draft_lessons BEGIN UPDATE draft_state SET version = version + 1 WHERE id = 1; END;
CREATE TRIGGER draft_lessons_update_version AFTER UPDATE ON draft_lessons BEGIN UPDATE draft_state SET version = version + 1 WHERE id = 1; END;
CREATE TRIGGER draft_lessons_delete_version AFTER DELETE ON draft_lessons BEGIN UPDATE draft_state SET version = version + 1 WHERE id = 1; END;
CREATE TRIGGER draft_lesson_resources_insert_version AFTER INSERT ON draft_lesson_resources BEGIN UPDATE draft_state SET version = version + 1 WHERE id = 1; END;
CREATE TRIGGER draft_lesson_resources_update_version AFTER UPDATE ON draft_lesson_resources BEGIN UPDATE draft_state SET version = version + 1 WHERE id = 1; END;
CREATE TRIGGER draft_lesson_resources_delete_version AFTER DELETE ON draft_lesson_resources BEGIN UPDATE draft_state SET version = version + 1 WHERE id = 1; END;
CREATE TRIGGER draft_assessments_insert_version AFTER INSERT ON draft_assessments BEGIN UPDATE draft_state SET version = version + 1 WHERE id = 1; END;
CREATE TRIGGER draft_assessments_update_version AFTER UPDATE ON draft_assessments BEGIN UPDATE draft_state SET version = version + 1 WHERE id = 1; END;
CREATE TRIGGER draft_assessments_delete_version AFTER DELETE ON draft_assessments BEGIN UPDATE draft_state SET version = version + 1 WHERE id = 1; END;
CREATE TRIGGER draft_question_banks_insert_version AFTER INSERT ON draft_question_banks BEGIN UPDATE draft_state SET version = version + 1 WHERE id = 1; END;
CREATE TRIGGER draft_question_banks_update_version AFTER UPDATE ON draft_question_banks BEGIN UPDATE draft_state SET version = version + 1 WHERE id = 1; END;
CREATE TRIGGER draft_question_banks_delete_version AFTER DELETE ON draft_question_banks BEGIN UPDATE draft_state SET version = version + 1 WHERE id = 1; END;
CREATE TRIGGER draft_question_cases_insert_version AFTER INSERT ON draft_question_cases BEGIN UPDATE draft_state SET version = version + 1 WHERE id = 1; END;
CREATE TRIGGER draft_question_cases_update_version AFTER UPDATE ON draft_question_cases BEGIN UPDATE draft_state SET version = version + 1 WHERE id = 1; END;
CREATE TRIGGER draft_question_cases_delete_version AFTER DELETE ON draft_question_cases BEGIN UPDATE draft_state SET version = version + 1 WHERE id = 1; END;
CREATE TRIGGER draft_questions_insert_version AFTER INSERT ON draft_questions BEGIN UPDATE draft_state SET version = version + 1 WHERE id = 1; END;
CREATE TRIGGER draft_questions_update_version AFTER UPDATE ON draft_questions BEGIN UPDATE draft_state SET version = version + 1 WHERE id = 1; END;
CREATE TRIGGER draft_questions_delete_version AFTER DELETE ON draft_questions BEGIN UPDATE draft_state SET version = version + 1 WHERE id = 1; END;
CREATE TRIGGER draft_assessment_rules_insert_version AFTER INSERT ON draft_assessment_rules BEGIN UPDATE draft_state SET version = version + 1 WHERE id = 1; END;
CREATE TRIGGER draft_assessment_rules_update_version AFTER UPDATE ON draft_assessment_rules BEGIN UPDATE draft_state SET version = version + 1 WHERE id = 1; END;
CREATE TRIGGER draft_assessment_rules_delete_version AFTER DELETE ON draft_assessment_rules BEGIN UPDATE draft_state SET version = version + 1 WHERE id = 1; END;
