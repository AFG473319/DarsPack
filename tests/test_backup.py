"""Tests for the one-click full-library backup (پشتیبان‌گیری, B2)."""
import json
import shutil
import sqlite3
import zipfile
from datetime import date

import pytest

from darspack.core.backup import backup_filename, backup_library
from darspack.core.hashing import sha256_file
from darspack.core.importer import import_file
from darspack.core.library import Library
from darspack.core.manifest import verify_package


@pytest.fixture()
def library_with_files(tmp_path):
    root = tmp_path / "lib"
    with Library(root) as lib:
        for i, name in enumerate(("جزوه ریاضی.pdf", "کاربرگ علوم.pdf")):
            src = tmp_path / name
            src.write_bytes(f"content {i}".encode("utf-8"))
            import_file(lib, src)
    return root


def test_backup_filename_is_jalali_dated():
    # 2026-10-25 falls on 1405-08-03 (Aban) — the Persian date a student
    # expects on the flash-drive copy
    name = backup_filename(date(2026, 10, 25))
    assert name == "darspack-backup-1405-08-03.zip"


def test_backup_is_a_valid_package_and_carries_the_catalog(tmp_path,
                                                           library_with_files):
    out = tmp_path / "backup.zip"
    with Library(library_with_files) as lib:
        info = backup_library(lib, out)
    assert info["count"] == 2

    # the درس‌پک half verifies like any package (the two backup members
    # are whitelisted, not reported as extras)
    report = verify_package(out)
    assert report.ok, report.problems

    # the catalog half: a valid SQLite db whose files count matches
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        assert "catalog.db" in names
        assert any(n.startswith("RESTORE-") for n in names)
        inner = tmp_path / "inner-catalog.db"
        inner.write_bytes(zf.read("catalog.db"))
    check = sqlite3.connect(inner)
    try:
        count = check.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        subjects = check.execute(
            "SELECT COUNT(*) FROM subjects").fetchone()[0]
    finally:
        check.close()
    assert count == 2
    assert subjects > 0                      # the A1 seeds rode along


def test_backup_of_empty_library_verifies(tmp_path):
    out = tmp_path / "empty.zip"
    with Library(tmp_path / "lib") as lib:
        backup_library(lib, out)
    assert verify_package(out).ok
    with zipfile.ZipFile(out) as zf:
        inner = tmp_path / "inner.db"
        inner.write_bytes(zf.read("catalog.db"))
    check = sqlite3.connect(inner)
    try:
        assert check.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 0
    finally:
        check.close()


def test_backup_is_wal_safe(library_with_files, tmp_path):
    # the WAL pragma is on (see test_db), so the -wal file holds the last
    # commits; a direct file copy could miss them — conn.backup must not
    out = tmp_path / "wal.zip"
    with Library(library_with_files) as lib:
        # a fresh import is the newest commit, likely still only in WAL
        src = library_with_files.parent / "تازه.pdf"
        src.write_bytes(b"just imported")
        import_file(lib, src)
        backup_library(lib, out)
    with zipfile.ZipFile(out) as zf:
        inner = tmp_path / "inner2.db"
        inner.write_bytes(zf.read("catalog.db"))
    check = sqlite3.connect(inner)
    try:
        names = {r[0] for r in check.execute("SELECT original_name FROM files")}
    finally:
        check.close()
    assert "تازه.pdf" in names


def test_backup_files_keep_catalog_stored_names(tmp_path, library_with_files):
    """The backup's files/ must use the catalog's own stored names, not
    friendly «NNN - name» labels: the catalog.db in the same ZIP points at
    those names, so a restore must be able to line the two up."""
    out = tmp_path / "names.zip"
    with Library(library_with_files) as lib:
        stored = {r["stored_name"] for r in lib.conn.execute(
            "SELECT stored_name FROM files")}
        backup_library(lib, out)
    assert len(stored) == 2
    with zipfile.ZipFile(out) as zf:
        file_members = {n for n in zf.namelist() if n.startswith("files/")}
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
    assert file_members == {f"files/{s}" for s in stored}
    assert {e["path"] for e in manifest["files"]} == file_members
    assert verify_package(out).ok


def test_restore_from_backup_survives_startup_sweep(tmp_path,
                                                    library_with_files):
    """Regression for the reported data loss: following the documented
    restore (replace catalog.db AND the whole files/ folder) must survive
    the next open's orphan sweep + health check, with every lesson intact."""
    out = tmp_path / "restore.zip"
    with Library(library_with_files) as lib:
        expected = {
            r["stored_name"]: (r["size_bytes"], r["sha256"])
            for r in lib.conn.execute("SELECT * FROM files")
        }
        backup_library(lib, out)

    extracted = tmp_path / "extracted"
    with zipfile.ZipFile(out) as zf:
        zf.extractall(extracted)

    # Simulate the guide: a fresh library root gets the backup's catalog.db
    # and the whole files/ folder copied in, with the app closed.
    restored = tmp_path / "restored-lib"
    (restored / "files").mkdir(parents=True)
    shutil.copy2(extracted / "catalog.db", restored / "catalog.db")
    for member in (extracted / "files").iterdir():
        shutil.copy2(member, restored / "files" / member.name)
    assert {p.name for p in (restored / "files").iterdir()} == set(expected)

    with Library(restored) as lib:            # open runs sweep + health check
        rows = lib.conn.execute("SELECT * FROM files").fetchall()
        assert len(rows) == len(expected)
        for row in rows:
            size, digest = expected[row["stored_name"]]
            path = lib.files_dir / row["stored_name"]
            assert path.is_file(), f"restored file was deleted: {path.name}"
            assert row["available"] == 1
            assert path.stat().st_size == size
            assert sha256_file(path) == digest
