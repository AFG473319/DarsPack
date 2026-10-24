"""SQLite schema and connection helpers (پایگاه داده).

One connection per thread, WAL mode, foreign keys ON. The schema is
normalized (درس‌نامه‌ی نرمال): subjects, teachers and tags live in their
own tables and files reference them, so a rename never touches file
rows. `name_norm` stores the normalized original filename — search and
name-conflict checks never depend on typing style.
"""
from __future__ import annotations

import datetime as _dt
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS subjects (
  id          INTEGER PRIMARY KEY,
  name        TEXT NOT NULL UNIQUE,          -- display name, e.g. «ریاضی»
  normalized  TEXT NOT NULL UNIQUE           -- match key
);
CREATE TABLE IF NOT EXISTS teachers (
  id          INTEGER PRIMARY KEY,
  name        TEXT NOT NULL,
  normalized  TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS files (
  id           INTEGER PRIMARY KEY,
  stored_name  TEXT NOT NULL DEFAULT '',     -- real name in files/, e.g. 000123.pdf
  original_name TEXT NOT NULL,               -- as imported, never altered
  name_norm    TEXT NOT NULL,                -- match key of original_name
  size_bytes   INTEGER NOT NULL,
  sha256       TEXT NOT NULL,                -- content hash; the dedup key
  imported_at  TEXT NOT NULL,                -- ISO datetime
  subject_id   INTEGER REFERENCES subjects(id),
  teacher_id   INTEGER REFERENCES teachers(id),
  chapter      INTEGER,                      -- فصل (1..12), nullable
  school_year  TEXT,                         -- «1405-1406»
  kind         TEXT CHECK (kind IN ('جزوه','نمونه‌سوال','کاربرگ','تکلیف','سایر')),
  note         TEXT DEFAULT '',
  available    INTEGER NOT NULL DEFAULT 1    -- 1 = present in files/
);
CREATE INDEX IF NOT EXISTS idx_files_sha       ON files(sha256);
CREATE INDEX IF NOT EXISTS idx_files_name_norm ON files(name_norm);
CREATE TABLE IF NOT EXISTS tags (
  id         INTEGER PRIMARY KEY,
  name       TEXT NOT NULL,
  normalized TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS file_tags (
  file_id INTEGER REFERENCES files(id) ON DELETE CASCADE,
  tag_id  INTEGER REFERENCES tags(id)  ON DELETE CASCADE,
  PRIMARY KEY (file_id, tag_id)
);
CREATE TABLE IF NOT EXISTS activity_log (
  id     INTEGER PRIMARY KEY,
  ts     TEXT NOT NULL,
  action TEXT NOT NULL,                      -- import / export / verify / share …
  detail TEXT DEFAULT ''
);
"""


def connect(db_path) -> sqlite3.Connection:
    """Open the catalog with sensible, explainable pragmas."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # readers never block the writer
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Create all tables if missing; safe to call on every open."""
    conn.executescript(SCHEMA)
    conn.commit()


def log(conn: sqlite3.Connection, action: str, detail: str = "") -> None:
    """Append one row to the user-activity log."""
    now = _dt.datetime.now().isoformat(timespec="seconds")
    conn.execute("INSERT INTO activity_log(ts, action, detail) VALUES (?,?,?)",
                 (now, action, detail))
