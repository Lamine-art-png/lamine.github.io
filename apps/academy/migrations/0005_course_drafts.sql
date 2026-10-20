-- Published content is immutable. Editors change drafts; learners only ever
-- see the live tables, which change solely through publication of a draft
-- that passed every readiness check (including the mandatory reviews bound
-- to that exact draft). Each publication is recorded as a course revision.
-- Reverse with migrations/down/0005_course_drafts.down.sql. Additive only.


CREATE TABLE draft_courses (
  id                   TEXT PRIMARY KEY,
  slug                 TEXT NOT NULL,
  program_id           TEXT,
  title                TEXT NOT NULL,
  subtitle             TEXT NOT NULL DEFAULT '',
  description          TEXT NOT NULL DEFAULT '',
  level                TEXT NOT NULL DEFAULT 'beginner' CHECK (level IN ('beginner','intermediate','advanced')),
  duration_minutes     INTEGER NOT NULL DEFAULT 0,
  thumbnail_url        TEXT,
  source_locale        TEXT NOT NULL DEFAULT 'en',
  objectives_json      TEXT NOT NULL DEFAULT '[]',
  audience_json        TEXT NOT NULL DEFAULT '[]',
  topics_json          TEXT NOT NULL DEFAULT '[]',
  prerequisites_text   TEXT NOT NULL DEFAULT '',
  planned_release_date TEXT,
  certificate_enabled  INTEGER NOT NULL DEFAULT 1,
  passing_score        INTEGER NOT NULL DEFAULT 80 CHECK (passing_score BETWEEN 1 AND 100),
  require_all_lessons  INTEGER NOT NULL DEFAULT 1,
  require_quizzes_pass INTEGER NOT NULL DEFAULT 0,
  sort_order           INTEGER NOT NULL DEFAULT 0,
  updated_at           TEXT NOT NULL,
  updated_by           TEXT
);

CREATE TABLE draft_course_instructors (
  course_id     TEXT NOT NULL,
  instructor_id TEXT NOT NULL,
  sort_order    INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (course_id, instructor_id)
);

CREATE TABLE draft_course_prerequisites (
  course_id              TEXT NOT NULL,
  prerequisite_course_id TEXT NOT NULL,
  is_required            INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (course_id, prerequisite_course_id),
  CHECK (course_id <> prerequisite_course_id)
);

CREATE TABLE draft_modules (
  id         TEXT PRIMARY KEY,
  course_id  TEXT NOT NULL,
  title      TEXT NOT NULL,
  summary    TEXT NOT NULL DEFAULT '',
  sort_order INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE draft_lessons (
  id                TEXT PRIMARY KEY,
  course_id         TEXT NOT NULL,
  module_id         TEXT NOT NULL,
  slug              TEXT NOT NULL,
  title             TEXT NOT NULL,
  type              TEXT NOT NULL DEFAULT 'text' CHECK (type IN ('video','text','interactive','reading','resource','exercise','quiz','case_study','assignment')),
  summary           TEXT NOT NULL DEFAULT '',
  body_md           TEXT NOT NULL DEFAULT '',
  interactive_json  TEXT,
  est_minutes       INTEGER NOT NULL DEFAULT 5,
  video_id          TEXT,
  assessment_id     TEXT,
  is_required       INTEGER NOT NULL DEFAULT 1,
  is_preview        INTEGER NOT NULL DEFAULT 0,
  sort_order        INTEGER NOT NULL DEFAULT 0,
  status            TEXT NOT NULL DEFAULT 'ready' CHECK (status IN ('draft','ready')),
  created_at        TEXT NOT NULL,
  updated_at        TEXT NOT NULL,
  UNIQUE (course_id, slug)
);

CREATE TABLE draft_lesson_resources (
  id         TEXT PRIMARY KEY,
  lesson_id  TEXT NOT NULL,
  title      TEXT NOT NULL,
  kind       TEXT NOT NULL DEFAULT 'link' CHECK (kind IN ('link','file')),
  url        TEXT,
  file_key   TEXT,
  mime       TEXT,
  size_bytes INTEGER,
  sort_order INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE TABLE draft_assessments (
  id                 TEXT PRIMARY KEY,
  course_id          TEXT NOT NULL,
  kind               TEXT NOT NULL CHECK (kind IN ('quiz','exam')),
  title              TEXT NOT NULL,
  instructions       TEXT NOT NULL DEFAULT '',
  time_limit_seconds INTEGER,
  passing_score      INTEGER NOT NULL DEFAULT 80 CHECK (passing_score BETWEEN 1 AND 100),
  max_attempts       INTEGER,
  cooldown_minutes   INTEGER NOT NULL DEFAULT 0,
  shuffle_questions  INTEGER NOT NULL DEFAULT 1,
  shuffle_options    INTEGER NOT NULL DEFAULT 1,
  feedback_policy    TEXT NOT NULL DEFAULT 'full' CHECK (feedback_policy IN ('score','correctness','full')),
  is_certification   INTEGER NOT NULL DEFAULT 0,
  is_required        INTEGER NOT NULL DEFAULT 1,
  status             TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('draft','active','retired')),
  created_at         TEXT NOT NULL,
  updated_at         TEXT NOT NULL
);

CREATE TABLE draft_question_banks (
  id          TEXT PRIMARY KEY,
  course_id   TEXT,
  title       TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);

CREATE TABLE draft_question_cases (
  id         TEXT PRIMARY KEY,
  bank_id    TEXT NOT NULL,
  title      TEXT NOT NULL,
  body_md    TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE draft_questions (
  id           TEXT PRIMARY KEY,
  bank_id      TEXT NOT NULL,
  case_id      TEXT,
  lesson_id    TEXT,
  type         TEXT NOT NULL CHECK (type IN ('single','multiple','true_false','matching','ordering','short_answer')),
  difficulty   TEXT NOT NULL DEFAULT 'medium' CHECK (difficulty IN ('easy','medium','hard')),
  prompt       TEXT NOT NULL,
  data_json    TEXT NOT NULL DEFAULT '{}',
  answer_json  TEXT NOT NULL,
  explanation  TEXT NOT NULL DEFAULT '',
  rubric       TEXT,
  grading      TEXT NOT NULL DEFAULT 'auto' CHECK (grading IN ('auto','manual')),
  points       INTEGER NOT NULL DEFAULT 1 CHECK (points > 0),
  status       TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('draft','active','retired')),
  created_at   TEXT NOT NULL,
  updated_at   TEXT NOT NULL
);

CREATE TABLE draft_assessment_rules (
  id            TEXT PRIMARY KEY,
  assessment_id TEXT NOT NULL,
  bank_id       TEXT NOT NULL,
  difficulty    TEXT CHECK (difficulty IN ('easy','medium','hard')),
  draw_count    INTEGER NOT NULL CHECK (draw_count > 0),
  sort_order    INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX draft_modules_course ON draft_modules(course_id, sort_order);
CREATE INDEX draft_lessons_course ON draft_lessons(course_id, sort_order);
CREATE INDEX draft_lesson_resources_lesson ON draft_lesson_resources(lesson_id);
CREATE INDEX draft_assessments_course ON draft_assessments(course_id);
CREATE INDEX draft_questions_bank ON draft_questions(bank_id, status, difficulty);
CREATE INDEX draft_assessment_rules_assessment ON draft_assessment_rules(assessment_id);

-- Live modules removed by a publication are retired (lessons inside keep learners' progress).
ALTER TABLE modules ADD COLUMN status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','retired'));
-- Set when a publication retires an assessment or question because the draft
-- removed it (as opposed to an editor choosing status 'retired').
ALTER TABLE assessments ADD COLUMN removed_at TEXT;
ALTER TABLE questions ADD COLUMN removed_at TEXT;

-- One row per publication: what went live, when, by whom, and the reviewed fingerprint.
CREATE TABLE course_revisions (
  id           TEXT PRIMARY KEY,
  course_id    TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
  number       INTEGER NOT NULL,
  content_hash TEXT NOT NULL,
  published_by TEXT,
  published_at TEXT NOT NULL,
  summary_json TEXT NOT NULL DEFAULT '{}',
  UNIQUE (course_id, number)
);

-- Start every draft as a copy of the current content.

INSERT INTO draft_courses (id,slug,program_id,title,subtitle,description,level,duration_minutes,thumbnail_url,source_locale,objectives_json,audience_json,topics_json,prerequisites_text,planned_release_date,certificate_enabled,passing_score,require_all_lessons,require_quizzes_pass,sort_order, updated_at) SELECT id,slug,program_id,title,subtitle,description,level,duration_minutes,thumbnail_url,source_locale,objectives_json,audience_json,topics_json,prerequisites_text,planned_release_date,certificate_enabled,passing_score,require_all_lessons,require_quizzes_pass,sort_order, updated_at FROM courses;

INSERT INTO draft_course_instructors (course_id,instructor_id,sort_order) SELECT course_id,instructor_id,sort_order FROM course_instructors;

INSERT INTO draft_course_prerequisites (course_id,prerequisite_course_id,is_required) SELECT course_id,prerequisite_course_id,is_required FROM course_prerequisites;

INSERT INTO draft_modules (id,course_id,title,summary,sort_order,created_at,updated_at) SELECT id,course_id,title,summary,sort_order,created_at,updated_at FROM modules;

INSERT INTO draft_lessons (id,course_id,module_id,slug,title,type,summary,body_md,interactive_json,est_minutes,video_id,assessment_id,is_required,is_preview,sort_order,status,created_at,updated_at) SELECT id,course_id,module_id,slug,title,type,summary,body_md,interactive_json,est_minutes,video_id,assessment_id,is_required,is_preview,sort_order,status,created_at,updated_at FROM lessons;

INSERT INTO draft_lesson_resources (id,lesson_id,title,kind,url,file_key,mime,size_bytes,sort_order,created_at) SELECT id,lesson_id,title,kind,url,file_key,mime,size_bytes,sort_order,created_at FROM lesson_resources;

INSERT INTO draft_assessments (id,course_id,kind,title,instructions,time_limit_seconds,passing_score,max_attempts,cooldown_minutes,shuffle_questions,shuffle_options,feedback_policy,is_certification,is_required,status,created_at,updated_at) SELECT id,course_id,kind,title,instructions,time_limit_seconds,passing_score,max_attempts,cooldown_minutes,shuffle_questions,shuffle_options,feedback_policy,is_certification,is_required,status,created_at,updated_at FROM assessments;

INSERT INTO draft_question_banks (id,course_id,title,description,created_at,updated_at) SELECT id,course_id,title,description,created_at,updated_at FROM question_banks;

INSERT INTO draft_question_cases (id,bank_id,title,body_md,created_at) SELECT id,bank_id,title,body_md,created_at FROM question_cases;

INSERT INTO draft_questions (id,bank_id,case_id,lesson_id,type,difficulty,prompt,data_json,answer_json,explanation,rubric,grading,points,status,created_at,updated_at) SELECT id,bank_id,case_id,lesson_id,type,difficulty,prompt,data_json,answer_json,explanation,rubric,grading,points,status,created_at,updated_at FROM questions;

INSERT INTO draft_assessment_rules (id,assessment_id,bank_id,difficulty,draw_count,sort_order) SELECT id,assessment_id,bank_id,difficulty,draw_count,sort_order FROM assessment_rules;
