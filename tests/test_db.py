"""Tests for the database schema (پایگاه داده)."""
import pytest

from darspack.core import db


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
