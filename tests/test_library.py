"""Tests for the Library object: subject seeding (A1) and the health check (B1)."""
import sqlite3
import pytest

from darspack.core.importer import import_file
from darspack.core.library import Library
from darspack.core.search import search
from darspack.core.suggest import DEFAULT_SUBJECTS


# --- A1: the default subject list is pre-filled on first open -------------

def test_fresh_library_seeds_default_subjects(tmp_path):
    with Library(tmp_path / "lib") as lib:
        names = [r["name"] for r in lib.conn.execute("SELECT name FROM subjects")]
        assert len(names) == len(DEFAULT_SUBJECTS)
        assert "ریاضی" in names
        # the canonical science subject (design decision 2026-10-24);
        # the bare «علوم» entry was removed
        assert "علوم تجربی" in names and "علوم" not in names
        action = lib.conn.execute(
            "SELECT detail FROM activity_log WHERE action='seed_subjects'"
        ).fetchone()
        assert action is not None


def test_reopen_does_not_duplicate_seeds(tmp_path):
    with Library(tmp_path / "lib"):
        pass
    with Library(tmp_path / "lib") as lib:
        count = lib.conn.execute("SELECT COUNT(*) c FROM subjects").fetchone()["c"]
        assert count == len(DEFAULT_SUBJECTS)
        logs = lib.conn.execute(
            "SELECT COUNT(*) c FROM activity_log WHERE action='seed_subjects'"
        ).fetchone()["c"]
        assert logs == 1


def test_existing_library_is_never_reseeded(tmp_path):
    with Library(tmp_path / "lib") as lib:
        # a user's own subjects exist → seeding must not touch anything
        lib.conn.execute("DELETE FROM subjects")
        lib.conn.execute(
            "INSERT INTO subjects(name, normalized) VALUES ('ستاره‌شناسی','ستاره شناسی')")
        lib.conn.commit()
    with Library(tmp_path / "lib") as lib:
        names = [r["name"] for r in lib.conn.execute("SELECT name FROM subjects")]
        assert names == ["ستاره‌شناسی"]


# --- B1: the startup health check makes `available` real -------------------

def test_missing_file_is_flagged_at_open(tmp_path):
    root = tmp_path / "lib"
    src = tmp_path / "جزوه ریاضی.pdf"
    src.write_bytes(b"precious")
    with Library(root) as lib:
        import_file(lib, src)
    stored = next((root / "files").iterdir())
    stored.unlink()                      # deleted behind the catalog's back
    with Library(root) as lib:
        row = lib.conn.execute("SELECT available FROM files").fetchone()
        assert row["available"] == 0


def test_size_mismatch_is_flagged_too(tmp_path):
    root = tmp_path / "lib"
    src = tmp_path / "کاربرگ.pdf"
    src.write_bytes(b"original bytes")
    with Library(root) as lib:
        import_file(lib, src)
    stored = next((root / "files").iterdir())
    stored.write_bytes(b"short")         # same name, different size
    with Library(root) as lib:
        assert lib.conn.execute(
            "SELECT available FROM files").fetchone()["available"] == 0


def test_restored_file_clears_the_flag(tmp_path):
    root = tmp_path / "lib"
    src = tmp_path / "جزوه.pdf"
    src.write_bytes(b"data")
    with Library(root) as lib:
        import_file(lib, src)
    stored = next((root / "files").iterdir())
    saved = stored.read_bytes()
    stored.unlink()
    with Library(root):
        pass                             # open #1: flags the missing file
    stored.write_bytes(saved)            # the user restores it
    with Library(root) as lib:           # open #2: heals the flag
        assert lib.conn.execute(
            "SELECT available FROM files").fetchone()["available"] == 1


def test_healthy_library_stays_available_and_search_exposes_flag(tmp_path):
    root = tmp_path / "lib"
    src = tmp_path / "سالم.pdf"
    src.write_bytes(b"ok")
    with Library(root) as lib:
        import_file(lib, src)
    with Library(root) as lib:
        assert lib.conn.execute(
            "SELECT COUNT(*) c FROM files WHERE available=0").fetchone()["c"] == 0
        rows = search(lib.conn, "سالم")
        assert rows and rows[0]["available"] == 1


def test_search_still_lists_flagged_rows(tmp_path):
    # a missing file must not vanish from the catalog: the user needs to
    # SEE the loss to re-obtain the file — the flag is a marker, not a filter
    root = tmp_path / "lib"
    src = tmp_path / "گم‌شده.pdf"
    src.write_bytes(b"x")
    with Library(root) as lib:
        import_file(lib, src)
    next((root / "files").iterdir()).unlink()
    with Library(root) as lib:
        rows = search(lib.conn, "گم")
        assert len(rows) == 1 and rows[0]["available"] == 0

def test_library_maintain_false_skips_maintenance(tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    with Library(root, maintain=False) as lib:
        assert lib.conn is not None
        with pytest.raises(sqlite3.OperationalError, match="no such table"):
            lib.conn.execute("SELECT COUNT(*) FROM subjects")
