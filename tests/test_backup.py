"""Tests for the one-click full-library backup (پشتیبان‌گیری, B2)."""
import json
import os
import shutil
import sqlite3
import time
import zipfile
from datetime import date

import pytest

from darspack.core.backup import backup_filename, backup_library
from darspack.core.hashing import sha256_file
from darspack.core.importer import import_file
from darspack.core.library import Library
from darspack.core.manifest import safe_name, verify_package


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


def test_restore_of_legacy_backup_survives_startup_sweep(tmp_path,
                                                         library_with_files):
    """Regression for backups made before 2026-11-17: members were filed
    as friendly «NNN - name» labels while catalog.db points at stored
    names, so the documented restore used to lose every file to the
    startup sweep. The rescue pass must re-home them by SHA-256 instead."""
    legacy = tmp_path / "legacy-lib"
    (legacy / "files").mkdir(parents=True)
    with Library(library_with_files) as lib:
        shutil.copy2(lib.db_path, legacy / "catalog.db")
        expected = {
            r["id"]: (r["stored_name"], r["original_name"], r["sha256"])
            for r in lib.conn.execute("SELECT * FROM files")
        }
    # reproduce the legacy export: copies under «NNN - name», in id order
    for i, fid in enumerate(sorted(expected), start=1):
        stored, original, _ = expected[fid]
        shutil.copy2(library_with_files / "files" / stored,
                     legacy / "files" / f"{i:03d} - {safe_name(original)}")
    friendly = {p.name for p in (legacy / "files").iterdir()}
    assert len(friendly) == len(expected)      # the bad state is on disk

    with Library(legacy) as lib:              # open runs rescue + sweep
        rows = {r["id"]: r for r in lib.conn.execute("SELECT * FROM files")}
        assert len(rows) == len(expected)
        for fid, (stored, _, digest) in expected.items():
            path = lib.files_dir / stored
            assert path.is_file(), f"legacy file was deleted: {stored}"
            assert sha256_file(path) == digest
            assert rows[fid]["available"] == 1
        # the friendly labels are gone (renamed into place, not duplicated)
        assert {p.name for p in lib.files_dir.iterdir() if p.is_file()} == {
            stored for stored, _, _ in expected.values()}


def test_sweep_still_removes_unknown_content(tmp_path):
    """The rescue must not hoard junk: a file matching no catalog row
    (e.g. an interrupted tmp copy) is still swept on open."""
    with Library(tmp_path / "lib") as lib:
        src = tmp_path / "جزوه.pdf"
        src.write_bytes(b"real content")
        import_file(lib, src)
    junk = tmp_path / "lib" / "files" / "tmp_partial"
    junk.write_bytes(b"interrupted copy")
    # a stale partial import: the sweep skips tmp_* copies younger than a
    # few minutes (they may be an in-flight import), so age it first
    old = time.time() - 3600
    os.utime(junk, (old, old))
    with Library(tmp_path / "lib") as lib:
        assert not junk.exists()
        assert (lib.files_dir / "000001.pdf").is_file()
