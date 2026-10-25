-- Evidence that each Cloudflare Stream upload is private, written by the
-- deploy pipeline after it re-reads the video's settings from Stream and
-- probes anonymous playback. Publication readiness requires a recent, passing
-- record for every Stream video a course uses. Kept apart from video_assets so
-- a protection check never changes reviewed course content.
CREATE TABLE stream_protection (
  uid               TEXT PRIMARY KEY,
  title             TEXT NOT NULL DEFAULT '',
  duration_seconds  INTEGER,
  signed_required   INTEGER NOT NULL DEFAULT 0,
  allowed_origins   TEXT NOT NULL DEFAULT '',
  downloads         TEXT NOT NULL DEFAULT 'unknown',
  anonymous_status  INTEGER,
  checked_at        TEXT NOT NULL
);
