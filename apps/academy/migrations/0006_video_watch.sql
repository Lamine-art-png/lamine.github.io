-- Server-measured video watching. Each heartbeat from the lesson player is
-- timed by the server; only forward playback that is physically possible at
-- up to 2x speed since the previous heartbeat is credited, as a segment of
-- the video. A lesson completes when the merged segments cover 90% of the
-- server-known length. Reverse with migrations/down/0006_video_watch.down.sql.
CREATE TABLE video_watch (
  user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  lesson_id       TEXT NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
  last_position   REAL NOT NULL DEFAULT 0,
  last_beat_at    TEXT NOT NULL,
  playing         INTEGER NOT NULL DEFAULT 0,
  segments_json   TEXT NOT NULL DEFAULT '[]',
  watched_seconds REAL NOT NULL DEFAULT 0,
  beats           INTEGER NOT NULL DEFAULT 0,
  rejected        INTEGER NOT NULL DEFAULT 0,
  created_at      TEXT NOT NULL,
  PRIMARY KEY (user_id, lesson_id)
);
