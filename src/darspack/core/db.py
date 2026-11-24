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

# Keep in lockstep with SCHEMA's CHECK constraint on files.kind.
ALLOWED_KINDS = ("جزوه", "نمونه‌سوال", "کاربرگ", "تکلیف", "سایر")


def resolve_kind(kind: object) -> str | None:
    """Map user/import kind text to a canonical ALLOWED_KINDS value, or None.

    Accepts Arabic letters / space vs ZWNJ (e.g. «نمونه سوال» -> «نمونه‌سوال»)
    so imports and API inputs never crash SQLite's CHECK constraint.
    """
    if not isinstance(kind, str):
        return None
    text = kind.strip()
    if not text:
        return None
    if text in ALLOWED_KINDS:
        return text
    from .normalize import match_key
    key = match_key(text)
    for allowed in ALLOWED_KINDS:
        if match_key(allowed) == key:
            return allowed
    return None


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
  lesson       INTEGER,                      -- درس, nullable — separate from
                                             -- فصل: a file may have either,
                                             -- both, or neither (design
                                             -- decision 2026-10-24; INF-1
                                             -- adds it to older catalogs)
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
CREATE TABLE IF NOT EXISTS hint_rules (
  token      TEXT PRIMARY KEY,               -- one normalized token from a filename stem
  subject_id INTEGER REFERENCES subjects(id),
  hits       INTEGER NOT NULL DEFAULT 0,     -- fires only at hits >= 2
  last_used  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS import_skips (
  id            INTEGER PRIMARY KEY,
  ts            TEXT NOT NULL,
  sha256        TEXT NOT NULL,               -- content already present in the library
  size_bytes    INTEGER NOT NULL,            -- bytes the library never had to copy
  original_name TEXT NOT NULL                -- the name the user tried to import
);
"""


def connect(db_path) -> sqlite3.Connection:
    """Open the catalog with sensible, explainable pragmas.

    check_same_thread=False is deliberate: the discipline is ONE
    connection per thread (UI thread, import worker, each HTTP worker);
    the only cross-thread use is closing a thread's connection after
    that thread is gone (server stop). SQLite serializes concurrent
    writers with the busy timeout below.
    """
    conn = sqlite3.connect(db_path, timeout=5.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # readers never block the writer
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Create all tables if missing, then migrate; safe to call on every open."""
    conn.executescript(SCHEMA)
    conn.commit()
    migrate(conn)


# --- schema migrations (INF-1) ---------------------------------------------
# The catalog outlives releases: a library created by an older DarsPack must
# keep opening. Each migration is one ordered step guarded by PRAGMA
# user_version — SQLite's built-in schema-version counter. Steps run once,
# each inside a transaction, and the version is bumped only after success,
# so an interrupted migration simply re-runs on the next open.

SCHEMA_VERSION = 1


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """True if `table` already has `column` (PRAGMA table_info, col name = idx 1)."""
    names = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    return column in names


def migrate(conn: sqlite3.Connection) -> None:
    """Bring an existing catalog up to SCHEMA_VERSION, one step at a time.

    A step's ALTER statements are guarded by column checks so the step is
    safe on BOTH kinds of database: fresh installs (whose SCHEMA already
    has every column) and old v0 catalogs (which need the actual ALTER).
    """
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= SCHEMA_VERSION:
        return
    for target in range(version + 1, SCHEMA_VERSION + 1):
        with conn:                      # one transaction per migration step
            if target == 1 and not _has_column(conn, "files", "lesson"):
                conn.execute("ALTER TABLE files ADD COLUMN lesson INTEGER")
            conn.execute(f"PRAGMA user_version = {target}")
            log(conn, "migrate", f"schema v{target}")


def log(conn: sqlite3.Connection, action: str, detail: str = "") -> None:
    """Append one row to the user-activity log."""
    now = _dt.datetime.now().isoformat(timespec="seconds")
    conn.execute("INSERT INTO activity_log(ts, action, detail) VALUES (?,?,?)",
                 (now, action, detail))


def get_or_create(conn: sqlite3.Connection, table: str, name: str) -> int | None:
    """Return the id of subjects/teachers/tags row `name`, creating it if new.

    Matching uses the normalized key, so «رياضي» (Arabic ي) finds «ریاضی».
    The table name is whitelisted: callers only ever pass internal
    constants, but an assert here closes the SQL-injection question forever.
    """
    assert table in {"subjects", "teachers", "tags"}, f"unknown table {table!r}"
    from .normalize import match_key  # local import avoids a cycle at import time
    key = match_key(name)
    if not key:
        return None
    # M2: the old SELECT-then-INSERT raced — two threads both passed the
    # SELECT and the second INSERT died on the UNIQUE backstop. This is
    # one atomic upsert: the conflict branch is a deliberate no-op (it
    # rewrites the value it already has, never the stored `name`) whose
    # only job is to make RETURNING hand back the existing row's id, so
    # the whole call is a single round trip either way.
    row = conn.execute(
        f"""INSERT INTO {table}(name, normalized) VALUES (?,?)
            ON CONFLICT DO UPDATE SET normalized = {table}.normalized
            RETURNING id""", (name.strip(), key)).fetchone()
    return row["id"] if row is not None else None
