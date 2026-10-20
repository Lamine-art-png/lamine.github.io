-- AGRO-AI Academy core schema (Cloudflare D1 / SQLite).
-- Reverse with migrations/down/0001_academy_core.down.sql.
-- Timestamps are ISO-8601 UTC strings. IDs are random URL-safe strings.


-- ───────────────────────────── Identity ─────────────────────────────

CREATE TABLE users (
  id                 TEXT PRIMARY KEY,
  email              TEXT NOT NULL COLLATE NOCASE,
  email_verified_at  TEXT,
  password_hash      TEXT,
  display_name       TEXT NOT NULL,
  credential_name    TEXT,
  locale             TEXT NOT NULL DEFAULT 'en',
  country            TEXT,
  professional_role  TEXT,
  organization       TEXT,
  bio                TEXT,
  timezone           TEXT,
  status             TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled','deleted')),
  failed_logins      INTEGER NOT NULL DEFAULT 0,
  locked_until       TEXT,
  last_login_at      TEXT,
  created_at         TEXT NOT NULL,
  updated_at         TEXT NOT NULL,
  deleted_at         TEXT
);
CREATE UNIQUE INDEX users_email_uq ON users(email);

CREATE TABLE user_roles (
  user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role       TEXT NOT NULL CHECK (role IN ('super_admin','academy_admin','instructor','content_editor','learner')),
  granted_by TEXT,
  granted_at TEXT NOT NULL,
  PRIMARY KEY (user_id, role)
);

CREATE TABLE oauth_accounts (
  provider   TEXT NOT NULL,
  subject    TEXT NOT NULL,
  user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  email      TEXT,
  created_at TEXT NOT NULL,
  PRIMARY KEY (provider, subject)
);
CREATE INDEX oauth_accounts_user ON oauth_accounts(user_id);

CREATE TABLE sessions (
  id_hash      TEXT PRIMARY KEY,
  user_id      TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at   TEXT NOT NULL,
  expires_at   TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  user_agent   TEXT,
  revoked_at   TEXT
);
CREATE INDEX sessions_user ON sessions(user_id);
CREATE INDEX sessions_expiry ON sessions(expires_at);

CREATE TABLE auth_tokens (
  id_hash    TEXT PRIMARY KEY,
  user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  purpose    TEXT NOT NULL CHECK (purpose IN ('verify_email','reset_password')),
  expires_at TEXT NOT NULL,
  used_at    TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX auth_tokens_user ON auth_tokens(user_id, purpose);

CREATE TABLE user_preferences (
  user_id                 TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  notify_course_reminders INTEGER NOT NULL DEFAULT 0,
  notify_course_updates   INTEGER NOT NULL DEFAULT 1,
  notify_product_news     INTEGER NOT NULL DEFAULT 0,
  share_country_analytics INTEGER NOT NULL DEFAULT 0,
  theme                   TEXT NOT NULL DEFAULT 'system',
  updated_at              TEXT NOT NULL
);

CREATE TABLE learning_goals (
  id             TEXT PRIMARY KEY,
  user_id        TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title          TEXT NOT NULL,
  weekly_minutes INTEGER,
  target_date    TEXT,
  status         TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','achieved','archived')),
  created_at     TEXT NOT NULL,
  updated_at     TEXT NOT NULL
);
CREATE INDEX learning_goals_user ON learning_goals(user_id);

-- ───────────────────────────── Curriculum ─────────────────────────────

CREATE TABLE programs (
  id          TEXT PRIMARY KEY,
  slug        TEXT NOT NULL UNIQUE,
  code        TEXT,
  title       TEXT NOT NULL,
  summary     TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  sort_order  INTEGER NOT NULL DEFAULT 0,
  status      TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','published','archived')),
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);

CREATE TABLE instructors (
  id           TEXT PRIMARY KEY,
  slug         TEXT NOT NULL UNIQUE,
  name         TEXT NOT NULL,
  title        TEXT NOT NULL DEFAULT '',
  bio          TEXT NOT NULL DEFAULT '',
  avatar_url   TEXT,
  is_ai_avatar INTEGER NOT NULL DEFAULT 0,
  disclosure   TEXT,
  user_id      TEXT REFERENCES users(id) ON DELETE SET NULL,
  sort_order   INTEGER NOT NULL DEFAULT 0,
  status       TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','hidden')),
  created_at   TEXT NOT NULL,
  updated_at   TEXT NOT NULL
);

CREATE TABLE courses (
  id                   TEXT PRIMARY KEY,
  slug                 TEXT NOT NULL UNIQUE,
  program_id           TEXT REFERENCES programs(id) ON DELETE SET NULL,
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
  status               TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','review','scheduled','published','archived')),
  planned_release_date TEXT,
  scheduled_at         TEXT,
  published_at         TEXT,
  certificate_enabled  INTEGER NOT NULL DEFAULT 1,
  passing_score        INTEGER NOT NULL DEFAULT 80 CHECK (passing_score BETWEEN 1 AND 100),
  require_all_lessons  INTEGER NOT NULL DEFAULT 1,
  require_quizzes_pass INTEGER NOT NULL DEFAULT 0,
  sort_order           INTEGER NOT NULL DEFAULT 0,
  content_review_note  TEXT,
  created_by           TEXT,
  created_at           TEXT NOT NULL,
  updated_at           TEXT NOT NULL
);
CREATE INDEX courses_status ON courses(status, sort_order);
CREATE INDEX courses_program ON courses(program_id);

CREATE TABLE course_instructors (
  course_id     TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
  instructor_id TEXT NOT NULL REFERENCES instructors(id) ON DELETE CASCADE,
  sort_order    INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (course_id, instructor_id)
);

CREATE TABLE course_prerequisites (
  course_id              TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
  prerequisite_course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
  is_required            INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (course_id, prerequisite_course_id),
  CHECK (course_id <> prerequisite_course_id)
);

CREATE TABLE learning_paths (
  id          TEXT PRIMARY KEY,
  slug        TEXT NOT NULL UNIQUE,
  title       TEXT NOT NULL,
  role        TEXT NOT NULL,
  summary     TEXT NOT NULL DEFAULT '',
  sort_order  INTEGER NOT NULL DEFAULT 0,
  status      TEXT NOT NULL DEFAULT 'published' CHECK (status IN ('draft','published','archived')),
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);

CREATE TABLE learning_path_courses (
  path_id    TEXT NOT NULL REFERENCES learning_paths(id) ON DELETE CASCADE,
  course_id  TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
  sort_order INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (path_id, course_id)
);

CREATE TABLE modules (
  id         TEXT PRIMARY KEY,
  course_id  TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
  title      TEXT NOT NULL,
  summary    TEXT NOT NULL DEFAULT '',
  sort_order INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX modules_course ON modules(course_id, sort_order);

CREATE TABLE video_assets (
  id               TEXT PRIMARY KEY,
  title            TEXT NOT NULL,
  provider         TEXT NOT NULL DEFAULT 'synthesia' CHECK (provider IN ('synthesia','r2','stream','external')),
  status           TEXT NOT NULL DEFAULT 'planned' CHECK (status IN ('planned','scripted','rendering','in_review','approved','retired')),
  instructor_id    TEXT REFERENCES instructors(id) ON DELETE SET NULL,
  hls_url          TEXT,
  mp4_url          TEXT,
  poster_url       TEXT,
  duration_seconds INTEGER,
  script_md        TEXT NOT NULL DEFAULT '',
  provider_ref     TEXT,
  approved_by      TEXT,
  approved_at      TEXT,
  created_at       TEXT NOT NULL,
  updated_at       TEXT NOT NULL
);

CREATE TABLE video_captions (
  id         TEXT PRIMARY KEY,
  video_id   TEXT NOT NULL REFERENCES video_assets(id) ON DELETE CASCADE,
  locale     TEXT NOT NULL,
  label      TEXT NOT NULL,
  vtt        TEXT NOT NULL,
  status     TEXT NOT NULL DEFAULT 'machine' CHECK (status IN ('machine','reviewed')),
  created_at TEXT NOT NULL,
  UNIQUE (video_id, locale)
);

CREATE TABLE lessons (
  id                TEXT PRIMARY KEY,
  course_id         TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
  module_id         TEXT NOT NULL REFERENCES modules(id) ON DELETE CASCADE,
  slug              TEXT NOT NULL,
  title             TEXT NOT NULL,
  type              TEXT NOT NULL DEFAULT 'text' CHECK (type IN ('video','text','interactive','reading','resource','exercise','quiz','case_study','assignment')),
  summary           TEXT NOT NULL DEFAULT '',
  body_md           TEXT NOT NULL DEFAULT '',
  interactive_json  TEXT,
  est_minutes       INTEGER NOT NULL DEFAULT 5,
  video_id          TEXT REFERENCES video_assets(id) ON DELETE SET NULL,
  assessment_id     TEXT,
  is_required       INTEGER NOT NULL DEFAULT 1,
  is_preview        INTEGER NOT NULL DEFAULT 0,
  sort_order        INTEGER NOT NULL DEFAULT 0,
  status            TEXT NOT NULL DEFAULT 'ready' CHECK (status IN ('draft','ready')),
  created_at        TEXT NOT NULL,
  updated_at        TEXT NOT NULL,
  UNIQUE (course_id, slug)
);
CREATE INDEX lessons_module ON lessons(module_id, sort_order);

CREATE TABLE lesson_resources (
  id         TEXT PRIMARY KEY,
  lesson_id  TEXT NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
  title      TEXT NOT NULL,
  kind       TEXT NOT NULL DEFAULT 'link' CHECK (kind IN ('link','file')),
  url        TEXT,
  file_key   TEXT,
  mime       TEXT,
  size_bytes INTEGER,
  sort_order INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE INDEX lesson_resources_lesson ON lesson_resources(lesson_id);

-- ───────────────────────────── Learning activity ─────────────────────────────

CREATE TABLE enrollments (
  id               TEXT PRIMARY KEY,
  user_id          TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  course_id        TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
  status           TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','completed','withdrawn')),
  progress_pct     INTEGER NOT NULL DEFAULT 0,
  last_lesson_id   TEXT,
  enrolled_at      TEXT NOT NULL,
  last_activity_at TEXT NOT NULL,
  completed_at     TEXT,
  UNIQUE (user_id, course_id)
);
CREATE INDEX enrollments_course ON enrollments(course_id, status);

CREATE TABLE lesson_progress (
  user_id          TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  lesson_id        TEXT NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
  course_id        TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
  status           TEXT NOT NULL DEFAULT 'started' CHECK (status IN ('started','completed')),
  position_seconds REAL NOT NULL DEFAULT 0,
  duration_seconds REAL,
  scroll_pct       INTEGER NOT NULL DEFAULT 0,
  started_at       TEXT NOT NULL,
  completed_at     TEXT,
  last_viewed_at   TEXT NOT NULL,
  client_updated_at TEXT,
  PRIMARY KEY (user_id, lesson_id)
);
CREATE INDEX lesson_progress_course ON lesson_progress(user_id, course_id);
CREATE INDEX lesson_progress_recent ON lesson_progress(user_id, last_viewed_at);

CREATE TABLE notes (
  id               TEXT PRIMARY KEY,
  user_id          TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  lesson_id        TEXT NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
  body             TEXT NOT NULL,
  position_seconds REAL,
  created_at       TEXT NOT NULL,
  updated_at       TEXT NOT NULL
);
CREATE INDEX notes_user_lesson ON notes(user_id, lesson_id);

CREATE TABLE bookmarks (
  id               TEXT PRIMARY KEY,
  user_id          TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  lesson_id        TEXT NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
  position_seconds REAL NOT NULL DEFAULT 0,
  label            TEXT NOT NULL DEFAULT '',
  created_at       TEXT NOT NULL
);
CREATE INDEX bookmarks_user_lesson ON bookmarks(user_id, lesson_id);

CREATE TABLE course_feedback (
  id         TEXT PRIMARY KEY,
  user_id    TEXT REFERENCES users(id) ON DELETE SET NULL,
  course_id  TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
  rating     INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
  comment    TEXT NOT NULL DEFAULT '',
  status     TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new','reviewed','actioned')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (user_id, course_id)
);

CREATE TABLE lesson_feedback (
  user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  lesson_id  TEXT NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
  helpful    INTEGER NOT NULL CHECK (helpful IN (0,1)),
  comment    TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  PRIMARY KEY (user_id, lesson_id)
);

CREATE TABLE achievements (
  user_id   TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  code      TEXT NOT NULL,
  detail    TEXT,
  earned_at TEXT NOT NULL,
  PRIMARY KEY (user_id, code)
);

-- ───────────────────────────── Assessments ─────────────────────────────

CREATE TABLE assessments (
  id                 TEXT PRIMARY KEY,
  course_id          TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
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
CREATE INDEX assessments_course ON assessments(course_id);

CREATE TABLE question_banks (
  id          TEXT PRIMARY KEY,
  course_id   TEXT REFERENCES courses(id) ON DELETE CASCADE,
  title       TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);

CREATE TABLE question_cases (
  id         TEXT PRIMARY KEY,
  bank_id    TEXT NOT NULL REFERENCES question_banks(id) ON DELETE CASCADE,
  title      TEXT NOT NULL,
  body_md    TEXT NOT NULL,
  created_at TEXT NOT NULL
);

-- data_json holds learner-visible structure (options, matching prompts, ordering
-- items). answer_json is the private key and is never sent to a browser.
CREATE TABLE questions (
  id           TEXT PRIMARY KEY,
  bank_id      TEXT NOT NULL REFERENCES question_banks(id) ON DELETE CASCADE,
  case_id      TEXT REFERENCES question_cases(id) ON DELETE SET NULL,
  lesson_id    TEXT REFERENCES lessons(id) ON DELETE SET NULL,
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
CREATE INDEX questions_bank ON questions(bank_id, status, difficulty);

CREATE TABLE assessment_rules (
  id            TEXT PRIMARY KEY,
  assessment_id TEXT NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
  bank_id       TEXT NOT NULL REFERENCES question_banks(id) ON DELETE CASCADE,
  difficulty    TEXT CHECK (difficulty IN ('easy','medium','hard')),
  draw_count    INTEGER NOT NULL CHECK (draw_count > 0),
  sort_order    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX assessment_rules_assessment ON assessment_rules(assessment_id);

CREATE TABLE attempts (
  id              TEXT PRIMARY KEY,
  user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  assessment_id   TEXT NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
  course_id       TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
  attempt_no      INTEGER NOT NULL,
  status          TEXT NOT NULL DEFAULT 'in_progress' CHECK (status IN ('in_progress','pending_review','graded','expired')),
  locale          TEXT NOT NULL DEFAULT 'en',
  layout_json     TEXT NOT NULL,
  started_at      TEXT NOT NULL,
  deadline_at     TEXT,
  submitted_at    TEXT,
  graded_at       TEXT,
  score_points    REAL,
  max_points      REAL,
  score_pct       REAL,
  passed          INTEGER,
  UNIQUE (user_id, assessment_id, attempt_no)
);
CREATE INDEX attempts_user ON attempts(user_id, assessment_id);
CREATE INDEX attempts_status ON attempts(status);
-- At most one open attempt per learner and assessment.
CREATE UNIQUE INDEX attempts_one_open ON attempts(user_id, assessment_id) WHERE status = 'in_progress';

CREATE TABLE attempt_answers (
  attempt_id       TEXT NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
  question_id      TEXT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
  response_json    TEXT,
  is_correct       INTEGER,
  points_awarded   REAL,
  max_points       REAL NOT NULL,
  needs_review     INTEGER NOT NULL DEFAULT 0,
  reviewer_id      TEXT,
  reviewer_comment TEXT,
  saved_at         TEXT,
  PRIMARY KEY (attempt_id, question_id)
);

-- ───────────────────────────── Credentials ─────────────────────────────

CREATE TABLE certificates (
  id              TEXT PRIMARY KEY,
  credential_id   TEXT NOT NULL UNIQUE,
  user_id         TEXT REFERENCES users(id) ON DELETE SET NULL,
  course_id       TEXT NOT NULL REFERENCES courses(id),
  attempt_id      TEXT,
  credential_name TEXT NOT NULL,
  course_title    TEXT NOT NULL,
  program_title   TEXT,
  score_pct       REAL,
  issued_at       TEXT NOT NULL,
  status          TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','revoked')),
  revoked_at      TEXT,
  revoked_reason  TEXT,
  revoked_by      TEXT,
  signature       TEXT NOT NULL,
  created_at      TEXT NOT NULL
);
-- A learner can hold only one valid credential per course.
CREATE UNIQUE INDEX certificates_one_active ON certificates(user_id, course_id) WHERE status = 'active';
CREATE INDEX certificates_user ON certificates(user_id);

CREATE TABLE certificate_events (
  id             TEXT PRIMARY KEY,
  certificate_id TEXT NOT NULL REFERENCES certificates(id) ON DELETE CASCADE,
  event          TEXT NOT NULL CHECK (event IN ('issued','revoked','reinstated','name_corrected','pdf_downloaded')),
  actor_id       TEXT,
  detail         TEXT,
  created_at     TEXT NOT NULL
);
CREATE INDEX certificate_events_cert ON certificate_events(certificate_id);

-- ───────────────────────────── Localization ─────────────────────────────

-- Database overrides layered on top of the bundled UI catalogs, so copy can be
-- corrected and reviewed without a deployment.
CREATE TABLE ui_translations (
  locale     TEXT NOT NULL,
  key        TEXT NOT NULL,
  value      TEXT NOT NULL,
  status     TEXT NOT NULL DEFAULT 'reviewed' CHECK (status IN ('machine','reviewed')),
  updated_by TEXT,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (locale, key)
);

CREATE TABLE content_translations (
  entity_type TEXT NOT NULL CHECK (entity_type IN ('course','module','lesson','question','question_case','program','learning_path','assessment')),
  entity_id   TEXT NOT NULL,
  field       TEXT NOT NULL,
  locale      TEXT NOT NULL,
  value       TEXT NOT NULL,
  status      TEXT NOT NULL DEFAULT 'machine' CHECK (status IN ('machine','draft','reviewed')),
  source_hash TEXT,
  updated_by  TEXT,
  updated_at  TEXT NOT NULL,
  PRIMARY KEY (entity_type, entity_id, field, locale)
);
CREATE INDEX content_translations_locale ON content_translations(locale, entity_type);

-- ───────────────────────────── Communication ─────────────────────────────

CREATE TABLE email_outbox (
  id         TEXT PRIMARY KEY,
  user_id    TEXT REFERENCES users(id) ON DELETE SET NULL,
  to_email   TEXT NOT NULL,
  template   TEXT NOT NULL,
  category   TEXT NOT NULL DEFAULT 'transactional' CHECK (category IN ('transactional','security','reminder')),
  locale     TEXT NOT NULL DEFAULT 'en',
  subject    TEXT NOT NULL,
  html       TEXT NOT NULL,
  text       TEXT NOT NULL,
  status     TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','sent','failed','unconfigured','suppressed')),
  attempts   INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  provider_id TEXT,
  created_at TEXT NOT NULL,
  sent_at    TEXT
);
CREATE INDEX email_outbox_status ON email_outbox(status, created_at);

CREATE TABLE notifications (
  id         TEXT PRIMARY KEY,
  user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind       TEXT NOT NULL,
  title      TEXT NOT NULL,
  body       TEXT NOT NULL DEFAULT '',
  url        TEXT,
  read_at    TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX notifications_user ON notifications(user_id, read_at);

CREATE TABLE support_requests (
  id         TEXT PRIMARY KEY,
  user_id    TEXT REFERENCES users(id) ON DELETE SET NULL,
  name       TEXT NOT NULL,
  email      TEXT NOT NULL,
  topic      TEXT NOT NULL,
  message    TEXT NOT NULL,
  status     TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','answered','closed')),
  admin_note TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- ───────────────────────────── Operations ─────────────────────────────

CREATE TABLE audit_log (
  id          TEXT PRIMARY KEY,
  actor_id    TEXT,
  action      TEXT NOT NULL,
  entity_type TEXT,
  entity_id   TEXT,
  detail      TEXT,
  created_at  TEXT NOT NULL
);
CREATE INDEX audit_log_created ON audit_log(created_at);
CREATE INDEX audit_log_entity ON audit_log(entity_type, entity_id);

-- Privacy-conscious learning events: no IP addresses, no user agents.
-- country is recorded only when the learner opted in.
CREATE TABLE learning_events (
  id         TEXT PRIMARY KEY,
  user_id    TEXT REFERENCES users(id) ON DELETE SET NULL,
  event      TEXT NOT NULL,
  course_id  TEXT,
  lesson_id  TEXT,
  locale     TEXT,
  country    TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX learning_events_event ON learning_events(event, created_at);
CREATE INDEX learning_events_user ON learning_events(user_id, created_at);

CREATE TABLE rate_limits (
  bucket       TEXT NOT NULL,
  window_start INTEGER NOT NULL,
  count        INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (bucket, window_start)
);

CREATE TABLE settings (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
