"""Tests for the one-click full-library backup (پشتیبان‌گیری, B2)."""
import sqlite3
import zipfile
from datetime import date

import pytest

from darspack.core.backup import backup_filename, backup_library
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
