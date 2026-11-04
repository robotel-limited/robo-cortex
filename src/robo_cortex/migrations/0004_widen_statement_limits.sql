-- Migration 0004: widen statement/assumptions/description caps 500 -> 750.
-- SQLite has no ALTER TABLE for a CHECK constraint, so this is the
-- create-copy-drop-rename rebuild documented in db.py's migrate() -- the
-- runner already disables foreign_keys for the duration and verifies with
-- PRAGMA foreign_key_check afterward, so this script only has to recreate
-- everything the old `memory`/`evidence` tables carried: all columns
-- (including `use_count`/`last_used_at`, added after 0001 by
-- 0002_add_usage_tracking.sql -- a rebuild must restate every column ever
-- added since init, not just 0001_init.sql's original set), indexes, the
-- AUTOINCREMENT sequence (sqlite_sequence is keyed by table name and does
-- NOT follow a RENAME+DROP, so it must be reseeded explicitly or a future
-- insert on either table could reuse an id still referenced by memory_path/
-- evidence/memory_link), and memory's FTS5 triggers (trigger objects are
-- dropped along with the table they're defined ON, same as indexes).

CREATE TABLE memory_new (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  type              TEXT NOT NULL CHECK (type IN
                        ('fact', 'decision', 'convention', 'hypothesis',
                         'experiment', 'lesson', 'open_question')),
  scope             TEXT NOT NULL CHECK (scope IN ('repo', 'global')),
  statement         TEXT NOT NULL CHECK (length(statement) <= 750 AND length(statement) > 0),
  why_it_matters    TEXT CHECK (why_it_matters IS NULL OR length(why_it_matters) <= 300),
  assumptions       TEXT CHECK (assumptions IS NULL OR length(assumptions) <= 750),
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

INSERT INTO memory_new SELECT * FROM memory;

CREATE TABLE evidence_new (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  memory_id         INTEGER NOT NULL REFERENCES memory_new(id) ON DELETE CASCADE,
  kind              TEXT NOT NULL CHECK (kind IN
                        ('test_output', 'ci', 'commit', 'gitea_pr', 'gitea_issue',
                         'free_text', 'cold_storage_ref')),
  description       TEXT NOT NULL CHECK (length(description) <= 750 AND length(description) > 0),
  command           TEXT,
  expected_outcome  TEXT,
  ref               TEXT,
  status            TEXT NOT NULL DEFAULT 'unverified' CHECK (status IN
                        ('unverified', 'verified', 'unverifiable')),
  created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  checked_at        TEXT
);

INSERT INTO evidence_new SELECT * FROM evidence;

DROP TABLE evidence;
DROP TABLE memory;
ALTER TABLE memory_new RENAME TO memory;
ALTER TABLE evidence_new RENAME TO evidence;

-- memory_path and memory_link's own FK references (declared `REFERENCES
-- memory(id)`) are resolved by name at use time, not bound to the old
-- table object, so they automatically target the rebuilt `memory` table --
-- nothing to redo for those two tables.

CREATE INDEX idx_memory_scope_status ON memory (scope, status);
CREATE INDEX idx_evidence_memory_id ON evidence (memory_id);

-- Reseed sqlite_sequence: a bare INSERT INTO ... SELECT * (explicit ids)
-- does not update it, and the rebuilt tables start with no row of their
-- own, so the next AUTOINCREMENT insert would start from 1 and could
-- collide with an id still referenced by memory_path/evidence/memory_link.
DELETE FROM sqlite_sequence WHERE name IN ('memory', 'evidence', 'memory_new', 'evidence_new');
INSERT INTO sqlite_sequence (name, seq)
  SELECT 'memory', COALESCE((SELECT MAX(id) FROM memory), 0);
INSERT INTO sqlite_sequence (name, seq)
  SELECT 'evidence', COALESCE((SELECT MAX(id) FROM evidence), 0);

DROP TRIGGER IF EXISTS memory_fts_ai;
DROP TRIGGER IF EXISTS memory_fts_ad;
DROP TRIGGER IF EXISTS memory_fts_au;

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

-- memory_fts is an external-content FTS5 table (content='memory',
-- content_rowid='id'); since the rebuild preserved every row's `id`
-- unchanged, the existing FTS index entries still point at valid rowids --
-- no 'rebuild' command needed, only the triggers above for future writes.
