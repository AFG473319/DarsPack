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
