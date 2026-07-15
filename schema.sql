-- robo-cortex schema v1
-- Current full schema, matching the sum of migrations/0001_init.sql.
-- See ARCHITECTURE.md §12 for the migration mechanism.

PRAGMA foreign_keys = ON;

CREATE TABLE memory (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  type              TEXT NOT NULL CHECK (type IN
                        ('fact', 'decision', 'convention', 'hypothesis',
                         'experiment', 'lesson', 'open_question')),
  scope             TEXT NOT NULL CHECK (scope IN ('repo', 'global')),
  statement         TEXT NOT NULL CHECK (length(statement) <= 500 AND length(statement) > 0),
  why_it_matters    TEXT CHECK (why_it_matters IS NULL OR length(why_it_matters) <= 300),
  assumptions       TEXT CHECK (assumptions IS NULL OR length(assumptions) <= 500),
  status            TEXT NOT NULL DEFAULT 'provisional' CHECK (status IN
                        ('active', 'provisional', 'needs_review', 'superseded',
                         'invalidated', 'abandoned', 'archived')),
  status_reason     TEXT,
  pre_review_status TEXT CHECK (pre_review_status IS NULL OR pre_review_status IN
                        ('active', 'provisional')),
  confidence        TEXT NOT NULL CHECK (confidence IN ('low', 'medium', 'high')),
  created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  last_verified_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  created_by        TEXT,
  use_count         INTEGER NOT NULL DEFAULT 0,
  last_used_at      TEXT
);

-- assumptions is only meaningful for scope = 'global'; enforced in application code
-- (a CHECK referencing another column is fine in SQLite, kept in code instead so the
-- error message can explain *why*, per ARCHITECTURE.md's "no silent nonsense" posture).

CREATE TABLE memory_path (
  memory_id  INTEGER NOT NULL REFERENCES memory(id) ON DELETE CASCADE,
  path       TEXT NOT NULL,
  blob_hash  TEXT NOT NULL,
  PRIMARY KEY (memory_id, path)
);

CREATE TABLE evidence (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  memory_id         INTEGER NOT NULL REFERENCES memory(id) ON DELETE CASCADE,
  kind              TEXT NOT NULL CHECK (kind IN
                        ('test_output', 'ci', 'commit', 'gitea_pr', 'gitea_issue',
                         'free_text', 'cold_storage_ref')),
  description       TEXT NOT NULL CHECK (length(description) <= 500 AND length(description) > 0),
  command           TEXT,
  expected_outcome  TEXT,
  ref               TEXT,
  status            TEXT NOT NULL DEFAULT 'unverified' CHECK (status IN
                        ('unverified', 'verified', 'unverifiable')),
  created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  checked_at        TEXT
);

CREATE TABLE memory_link (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  from_id     INTEGER NOT NULL REFERENCES memory(id) ON DELETE CASCADE,
  to_id       INTEGER NOT NULL REFERENCES memory(id) ON DELETE CASCADE,
  link_type   TEXT NOT NULL CHECK (link_type IN
                  ('contradicts', 'supersedes', 'duplicate_of', 'lesson_from')),
  created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  UNIQUE (from_id, to_id, link_type),
  CHECK (from_id != to_id)
);

CREATE TABLE cold_storage (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  content     TEXT NOT NULL,
  created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_memory_scope_status ON memory (scope, status);
CREATE INDEX idx_memory_path_path ON memory_path (path);
CREATE INDEX idx_evidence_memory_id ON evidence (memory_id);
CREATE INDEX idx_memory_link_from ON memory_link (from_id);
CREATE INDEX idx_memory_link_to ON memory_link (to_id);

-- FTS5 index over the text fields ranking reads from (ARCHITECTURE.md §5.1).
-- assumptions is deliberately NOT indexed here: scope-B gating (§5.4) is an absolute,
-- assumption-specific word-overlap check done in application code, not a text-match
-- search, so assumption text must never be able to satisfy a statement/why_it_matters
-- query (that was the leak in the rejected first draft of §5.4).
-- External-content table: memory owns the data, memory_fts is a search index over it,
-- kept in sync by triggers so there is exactly one place the text actually lives.
CREATE VIRTUAL TABLE memory_fts USING fts5(
  statement,
  why_it_matters,
  content = 'memory',
  content_rowid = 'id'
);

CREATE TRIGGER memory_fts_ai AFTER INSERT ON memory BEGIN
  INSERT INTO memory_fts (rowid, statement, why_it_matters)
  VALUES (new.id, new.statement, new.why_it_matters);
END;

CREATE TRIGGER memory_fts_ad AFTER DELETE ON memory BEGIN
  INSERT INTO memory_fts (memory_fts, rowid, statement, why_it_matters)
  VALUES ('delete', old.id, old.statement, old.why_it_matters);
END;

CREATE TRIGGER memory_fts_au AFTER UPDATE ON memory BEGIN
  INSERT INTO memory_fts (memory_fts, rowid, statement, why_it_matters)
  VALUES ('delete', old.id, old.statement, old.why_it_matters);
  INSERT INTO memory_fts (rowid, statement, why_it_matters)
  VALUES (new.id, new.statement, new.why_it_matters);
END;

PRAGMA user_version = 2;
