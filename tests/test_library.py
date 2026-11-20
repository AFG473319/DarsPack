"""Tests for the Library object: subject seeding (A1) and the health check (B1)."""
import os
import sqlite3
import time
from pathlib import Path

import pytest

from darspack.core import db
from darspack.core.hashing import sha256_file
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


def test_for_background_skips_the_startup_passes(tmp_path):
    # B9: workers open the library the window already prepared — seeding,
    # the orphan sweep and the health check must not run again per batch.
    root = tmp_path / "lib"
    with Library(root) as lib:
        before = lib.conn.execute(
            "SELECT COUNT(*) c FROM activity_log").fetchone()["c"]
    with Library.for_background(root) as lib:
        after = lib.conn.execute(
            "SELECT COUNT(*) c FROM activity_log").fetchone()["c"]
        assert after == before                     # no new startup log rows
        assert lib.conn.execute(
            "SELECT COUNT(*) c FROM subjects").fetchone()["c"] > 0
    # a folder with no catalog yet still gets a usable schema
    with Library.for_background(tmp_path / "fresh") as lib:
        assert lib.conn.execute(
            "SELECT COUNT(*) c FROM subjects").fetchone()["c"] > 0


def test_list_trash_with_corrupted_metadata_json(tmp_path):
    with Library(tmp_path / "lib") as lib:
        # Create trash and trash_meta directories
        lib.trash_dir.mkdir(parents=True, exist_ok=True)
        lib.trash_meta_dir.mkdir(parents=True, exist_ok=True)
        # Put a file in trash
        (lib.trash_dir / "sample.pdf").write_bytes(b"trash-content")
        # Write corrupted JSON in trash_meta
        (lib.trash_meta_dir / "sample.pdf.json").write_text("{corrupt-json", encoding="utf-8")
        items = lib.list_trash()
        assert len(items) == 1
        assert items[0]["original_name"] == "sample.pdf"
        assert items[0]["subject_name"] == "?"


def test_restore_nonexistent_trash_file_raises_not_found(tmp_path):
    with Library(tmp_path / "lib") as lib:
        with pytest.raises(FileNotFoundError):
            lib.restore_trash_file("ghost.pdf")


# --- H4 / M5 / M6 / M7: startup robustness -----------------------------------

def test_sweep_skips_fresh_tmp_but_removes_stale_one(tmp_path):
    """H4: a tmp_* copy younger than a few minutes may be an in-flight
    import from another process — the sweep leaves it alone; a stale
    one is still removed."""
    root = tmp_path / "lib"
    with Library(root):
        pass
    fresh = root / "files" / "tmp_fresh.pdf"
    stale = root / "files" / "tmp_stale.pdf"
    fresh.write_bytes(b"fresh")
    stale.write_bytes(b"stale")
    old = time.time() - 3600
    os.utime(stale, (old, old))
    with Library(root):
        pass
    assert fresh.exists()
    assert not stale.exists()


def test_sweep_skips_locked_files_and_app_still_opens(tmp_path, monkeypatch):
    """H4: one locked stray file (or locked tmp copy) must not stop the
    app from starting — it is skipped and logged."""
    root = tmp_path / "lib"
    with Library(root):
        pass
    stray = root / "files" / "stray.pdf"
    stray.write_bytes(b"stray")
    tmp = root / "files" / "tmp_locked.pdf"
    tmp.write_bytes(b"tmp")
    old = time.time() - 3600
    os.utime(tmp, (old, old))
    real_unlink = Path.unlink
    real_replace = os.replace

    def fake_unlink(self, missing_ok=False):
        if self in (stray, tmp):
            raise PermissionError("locked by another program")
        return real_unlink(self, missing_ok=missing_ok)

    def fake_replace(src, dst):
        if Path(src) in (stray, tmp):
            raise PermissionError("locked by another program")
        return real_replace(src, dst)

    monkeypatch.setattr(Path, "unlink", fake_unlink)
    monkeypatch.setattr(os, "replace", fake_replace)
    with Library(root) as lib:  # must not raise
        assert stray.exists()
        assert tmp.exists()
        skipped = lib.conn.execute(
            "SELECT COUNT(*) c FROM activity_log WHERE action='sweep_skip'"
        ).fetchone()["c"]
        assert skipped >= 2


def test_sweep_moves_user_file_to_trash_and_logs_it(tmp_path):
    """M5: a file dropped into files/ by hand is moved to .trash — with
    a log record (name, size, SHA) — instead of being deleted silently."""
    root = tmp_path / "lib"
    with Library(root):
        pass
    dropped = root / "files" / "handout.pdf"
    dropped.write_bytes(b"handout")
    digest = sha256_file(dropped)
    with Library(root) as lib:
        assert not dropped.exists()
        trashed = lib.trash_dir / "handout.pdf"
        assert trashed.exists()
        assert trashed.read_bytes() == b"handout"
        entry = lib.conn.execute(
            "SELECT detail FROM activity_log WHERE action='sweep'"
        ).fetchone()
        assert entry is not None
        assert "handout.pdf" in entry["detail"]
        assert digest in entry["detail"]
        assert "7 bytes" in entry["detail"]


def test_empty_trash_reports_locked_file(tmp_path, monkeypatch):
    """M6: emptying the trash skips a file that is open elsewhere and
    reports how many went and how many stayed, instead of dying."""
    root = tmp_path / "lib"
    with Library(root) as lib:
        src1 = tmp_path / "a.pdf"
        src2 = tmp_path / "b.pdf"
        src1.write_bytes(b"a")
        src2.write_bytes(b"b")
        import_file(lib, src1)
        import_file(lib, src2)
        names = [r["stored_name"] for r in lib.conn.execute(
            "SELECT stored_name FROM files ORDER BY id")]
        ids = [r["id"] for r in lib.conn.execute("SELECT id FROM files")]
        for fid in ids:
            lib.move_to_trash(fid)
        assert len(lib.list_trash()) == 2
        locked = lib.trash_dir / names[1]
        real_unlink = Path.unlink

        def fake_unlink(self, missing_ok=False):
            if self == locked:
                raise PermissionError("open in another program")
            return real_unlink(self, missing_ok=missing_ok)

        monkeypatch.setattr(Path, "unlink", fake_unlink)
        result = lib.empty_trash()
        assert result["deleted"] == 1
        assert result["failed"] == 1
        assert result["failed_names"] == [locked.name]
        assert locked.exists()                    # still there
        assert not (lib.trash_dir / names[0]).exists()
        # the failed file keeps its metadata, so it stays listed
        assert [i["trash_name"] for i in lib.list_trash()] == [locked.name]


def test_restore_rehashes_tampered_file(tmp_path):
    """M7: restoring always re-hashes the actual file — a trashed file
    altered while in trash is restored with its real hash, not the
    saved one."""
    root = tmp_path / "lib"
    with Library(root) as lib:
        src = tmp_path / "doc.pdf"
        src.write_bytes(b"original")
        import_file(lib, src)
        fid = lib.conn.execute("SELECT id FROM files").fetchone()["id"]
        lib.move_to_trash(fid)
        trashed = lib.trash_dir / "000001.pdf"
        trashed.write_bytes(b"tampered while in trash")
        expected = sha256_file(trashed)
        res = lib.restore_trash_file("000001.pdf")
        row = lib.conn.execute(
            "SELECT * FROM files WHERE id=?", (res["id"],)).fetchone()
        assert row["sha256"] == expected
        assert row["size_bytes"] == len(b"tampered while in trash")


def test_restore_recreates_missing_subject(tmp_path):
    """M7: the subject a trashed file belonged to may have been deleted
    since — restore looks it up by normalized name and recreates it
    instead of leaving the file as «بدون درس»."""
    root = tmp_path / "lib"
    with Library(root) as lib:
        src = tmp_path / "doc.pdf"
        src.write_bytes(b"doc")
        import_file(lib, src)
        fid = lib.conn.execute("SELECT id FROM files").fetchone()["id"]
        subject_id = db.get_or_create(lib.conn, "subjects", "ریاضی")
        lib.conn.execute(
            "UPDATE files SET subject_id=? WHERE id=?", (subject_id, fid))
        lib.conn.commit()
        lib.move_to_trash(fid)
        lib.conn.execute("DELETE FROM subjects WHERE id=?", (subject_id,))
        lib.conn.commit()
        res = lib.restore_trash_file("000001.pdf")
        row = lib.conn.execute(
            "SELECT * FROM files WHERE id=?", (res["id"],)).fetchone()
        sub = lib.conn.execute(
            "SELECT name FROM subjects WHERE id=?",
            (row["subject_id"],)).fetchone()
        assert sub is not None and sub["name"] == "ریاضی"


def test_restore_duplicate_sha_is_flagged(tmp_path):
    """M7: a file whose content is already back in the library
    (re-imported while it sat in trash) is not restored as a duplicate
    row — the restore is refused and the file stays in trash."""
    root = tmp_path / "lib"
    with Library(root) as lib:
        src = tmp_path / "doc.pdf"
        src.write_bytes(b"doc")
        import_file(lib, src)
        fid = lib.conn.execute("SELECT id FROM files").fetchone()["id"]
        lib.move_to_trash(fid)
        lib.conn.execute(
            "INSERT INTO files (original_name, stored_name, name_norm,"
            " size_bytes, sha256, imported_at) VALUES (?,?,?,?,?,?)",
            ("doc.pdf", "000002.pdf", "doc", 3,
             sha256_file(src), "2026-11-19T00:00:00"))
        lib.conn.commit()
        with pytest.raises(ValueError, match="already in the library"):
            lib.restore_trash_file("000001.pdf")
        assert (lib.trash_dir / "000001.pdf").exists()  # still in trash
