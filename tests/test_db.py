"""Tests for the database schema (پایگاه داده)."""
import sqlite3

import pytest

from darspack.core import db
from darspack.core.normalize import match_key


@pytest.fixture()
def conn(tmp_path):
    c = db.connect(tmp_path / "catalog.db")
    db.init_schema(c)
    yield c
    c.close()


def test_init_schema_is_idempotent(conn):
    db.init_schema(conn)   # second call must not fail
    tables = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"subjects", "teachers", "files", "tags", "file_tags",
            "activity_log"} <= tables


def test_foreign_keys_enforced(conn):
    conn.execute("INSERT INTO subjects(name, normalized) VALUES ('ریاضی','ریاضی')")
    with pytest.raises(Exception):
        conn.execute(
            """INSERT INTO files(original_name, name_norm, size_bytes, sha256,
               imported_at, subject_id) VALUES ('x','x',1,'ab','t',999)""")


def test_activity_log_appends(conn):
    db.log(conn, "import", "test")
    rows = conn.execute("SELECT action, detail FROM activity_log").fetchall()
    assert rows[-1]["action"] == "import"
    assert rows[-1]["detail"] == "test"


# --- get_or_create: the normalization workhorse behind every dialog save --

def test_get_or_create_creates_then_reuses(conn):
    first = db.get_or_create(conn, "subjects", "فیزیک")
    assert first is not None
    again = db.get_or_create(conn, "subjects", "فیزیک")
    assert again == first
    count = conn.execute("SELECT COUNT(*) c FROM subjects").fetchone()["c"]
    assert count == 1


def test_get_or_create_matches_across_spellings(conn):
    # the docstring's whole promise: «رياضي» (Arabic ي) finds «ریاضی»
    persian = db.get_or_create(conn, "subjects", "ریاضی")
    arabic = db.get_or_create(conn, "subjects", "رياضي")
    assert arabic == persian
    count = conn.execute("SELECT COUNT(*) c FROM subjects").fetchone()["c"]
    assert count == 1


def test_get_or_create_rejects_blank_names(conn):
    assert db.get_or_create(conn, "subjects", "   ") is None
    assert conn.execute("SELECT COUNT(*) c FROM subjects").fetchone()["c"] == 0


# --- schema contracts the rest of the app silently leans on --------------

def test_kind_column_only_accepts_known_kinds(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """INSERT INTO files(original_name, name_norm, size_bytes, sha256,
               imported_at, kind) VALUES ('x','x',1,'ab','t','bogus')""")


def test_wal_mode_is_on(tmp_path):
    # readers never block the writer — the LAN server's story depends on
    # this pragma; assert it once so nobody "simplifies" it away
    c = db.connect(tmp_path / "wal.db")
    try:
        assert c.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        c.close()


def test_tag_match_key_is_unique(conn):
    # get_or_create's SELECT-then-INSERT relies on the UNIQUE backstop:
    # two tags with the same match key must not both store
    key = match_key("امتحان")
    conn.execute("INSERT INTO tags(name, normalized) VALUES ('امتحان', ?)", (key,))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO tags(name, normalized) VALUES ('امتحان', ?)", (key,))


# --- schema migrations (INF-1) ----------------------------------------------

def test_fresh_install_reaches_current_schema_version(conn):
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    assert db._has_column(conn, "files", "lesson")


def test_v0_database_gains_lesson_column(tmp_path):
    # simulate an older install: schema WITHOUT the lesson column, at v0
    c = db.connect(tmp_path / "old.db")
    try:
        c.executescript(db.SCHEMA.replace(
            "lesson       INTEGER,", "-- lesson added by migration"))
        assert not db._has_column(c, "files", "lesson")
        assert c.execute("PRAGMA user_version").fetchone()[0] == 0
        db.migrate(c)
        assert db._has_column(c, "files", "lesson")
        assert c.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        # and the new column actually stores (nullable — a file may have
        # درس, فصل, both, or neither)
        c.execute("""INSERT INTO files(original_name, name_norm, size_bytes,
                     sha256, imported_at, lesson)
                     VALUES ('x','x',1,'ab','t',3)""")
        assert c.execute("SELECT lesson FROM files").fetchone()["lesson"] == 3
    finally:
        c.close()


def test_migrate_is_idempotent(conn):
    before = conn.execute(
        "SELECT COUNT(*) c FROM activity_log WHERE action='migrate'").fetchone()["c"]
    db.migrate(conn)                      # second call: version already current
    after = conn.execute(
        "SELECT COUNT(*) c FROM activity_log WHERE action='migrate'").fetchone()["c"]
    assert before == after
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION


def test_migrated_library_reopens_through_init_schema(tmp_path):
    # the real path: Library.open() runs init_schema → migrate on every
    # open; an upgraded old db must keep opening without re-migrating
    c = db.connect(tmp_path / "old.db")
    c.executescript(db.SCHEMA.replace(
        "lesson       INTEGER,", "-- lesson added by migration"))
    c.commit()
    c.close()
    from darspack.core.library import Library
    with Library(tmp_path) as lib:
        assert db._has_column(lib.conn, "files", "lesson")
        assert lib.conn.execute(
            "PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION


# --- get_or_create safety ----------------------------------------------------

def test_get_or_create_rejects_unknown_tables(conn):
    with pytest.raises(AssertionError):
        db.get_or_create(conn, "files", "bogus")


def test_cascade_delete_removes_file_tags(conn):
    # Foreign key ON DELETE CASCADE verification
    cur = conn.execute(
        """INSERT INTO files(original_name, name_norm, size_bytes, sha256, imported_at)
           VALUES ('test.pdf', 'test.pdf', 10, 'sha-test', '2026-10-25T10:00:00')""")
    file_id = cur.lastrowid
    tag_id = db.get_or_create(conn, "tags", "مهم")
    conn.execute("INSERT INTO file_tags(file_id, tag_id) VALUES (?, ?)", (file_id, tag_id))
    conn.commit()

    assert conn.execute("SELECT COUNT(*) c FROM file_tags WHERE file_id=?", (file_id,)).fetchone()["c"] == 1
    # Delete file
    conn.execute("DELETE FROM files WHERE id=?", (file_id,))
    conn.commit()
    # file_tags row must be automatically removed by CASCADE
    assert conn.execute("SELECT COUNT(*) c FROM file_tags WHERE file_id=?", (file_id,)).fetchone()["c"] == 0
    # But the tag itself is preserved
    assert conn.execute("SELECT COUNT(*) c FROM tags WHERE id=?", (tag_id,)).fetchone()["c"] == 1


def test_hint_rules_token_upsert(conn):
    sid = db.get_or_create(conn, "subjects", "فیزیک")
    conn.execute(
        """INSERT INTO hint_rules(token, subject_id, hits, last_used)
           VALUES ('فیزیک', ?, 1, '2026-10-25')
           ON CONFLICT(token) DO UPDATE SET hits = hits + 1""", (sid,))
    conn.commit()
    row = conn.execute("SELECT hits FROM hint_rules WHERE token='فیزیک'").fetchone()
    assert row["hits"] == 1

    # Second insert updates hits
    conn.execute(
        """INSERT INTO hint_rules(token, subject_id, hits, last_used)
           VALUES ('فیزیک', ?, 1, '2026-10-26')
           ON CONFLICT(token) DO UPDATE SET hits = hits + 1""", (sid,))
    conn.commit()
    row2 = conn.execute("SELECT hits FROM hint_rules WHERE token='فیزیک'").fetchone()
    assert row2["hits"] == 2
