"""Full-library backup (پشتیبان‌گیری کامل کتابخانه).

The permanence pitch needs an affordance: one ZIP a student can drop on
a flash drive at the end of the month. The backup is BOTH things at
once — a browsable درس‌پک (manifest + files + index.html via the normal
export path) AND the catalog itself (a `conn.backup()` snapshot, which
is the WAL-safe way to copy a live SQLite database, plus a short
restore guide). Restore in v1 is the documented manual steps; an
in-app restore button is a decision the user owns.

CRITICAL: the ZIP's files/ keeps the catalog's own stored names
(files/000001.pdf), NOT friendly display labels. The catalog.db
snapshot points at those names, so a restore must replace catalog.db
AND the whole files/ folder together. An earlier build filed members
as 'NNN - name'; a restore then left every copied file unreferenced,
and the next startup's orphan sweep deleted them - total data loss.
Fixed 2026-11-17 for NEW backups (stored_names=True); for backups made
BEFORE that day, Library.sweep_orphans()'s rescue pass re-homes the
friendly-labelled copies by SHA-256 on the next open, so the manual
restore below is safe for them too. See tests/test_backup.py.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
import zipfile
from pathlib import Path

import jdatetime

from .manifest import export_package

_RESTORE_GUIDE = """بازگردانی پشتیبان درس‌پک — راهنما
=================================

این فایل یک پشتیبانِ کامل کتابخانه است:
  - manifest.json + پوشه‌ی files/ + index.html : فایل‌ها و فهرست قابل مرور آن‌ها
  - catalog.db : پایگاه داده (فراداده، درس‌ها، برچسب‌ها، تاریخچه)
  - RESTORE-راهنما.txt : همین راهنما

نکته‌ی مهم: نام فایل‌های داخل پوشه‌ی files/ این پشتیبان، همان نام‌های داخلی
کاتالوگ‌اند (مثل 000001.pdf)، نه نام‌های نمایشی. catalog.db داخل پشتیبان به
همین نام‌ها اشاره می‌کند. بنابراین باید catalog.db و کل پوشه‌ی files/ را با هم
جایگزین کنید. اگر فایل‌ها را با نام دیگری کپی کنید، کاتالوگ آنها را نمی‌شناسد.
هیچ‌چیز پاک نمی‌شود: در نخستین باز شدن برنامه، هر فایلی که محتوای آن (اثر
انگشت SHA-256) با ردیفی از کاتالوگ که فایلش گم شده هم‌خوانی دارد، سر جای خود
برمی‌گردد؛ فقط محتوای بی‌صاحب پاکسازی می‌شود. بررسی سلامت نیز ردیف‌های
گم‌شده را علامت‌گذاری می‌کند.

بازگردانی (گام‌به‌گام):
  1. برنامه‌ی DarsPack را کاملاً ببندید.
  2. از پوشه‌ی کتابخانه‌ی فعلی یک کپی امن در جای دیگری بگیرید.
  3. محتوای پوشه‌ی کتابخانه را با محتوای این پشتیبان جایگزین کنید:
     catalog.db (و catalog.db-wal / catalog.db-shm اگر وجود دارند) را پاک کنید،
     catalog.db این پشتیبان را کنار پوشه‌ی files/ بگذارید؛ سپس کل پوشه‌ی
     files/ داخل پشتیبان را جای files/ فعلی کپی/جایگزین کنید.
  4. برنامه را دوباره باز کنید؛ «بررسی سلامت» در شروع، هر problem را نشان می‌دهد.

هشدار: بسته‌ی پشتیبان را روی همان دیسک نگه ندارید — فلش یا مسیر دیگری بهتر است.
"""


def backup_filename(today=None, directory=None) -> str:
    """Jalali-dated name for the backup ZIP: darspack-backup-1405-08-02.zip.

    If `directory` is given and that name is already taken there, a counter
    suffix is added (-2, -3, ...) so a second backup on the same day never
    silently overwrites the first one.
    """
    if today is None:
        import datetime as _dt
        today = _dt.date.today()
    jalali = jdatetime.date.fromgregorian(date=today)
    base = f"darspack-backup-{jalali.strftime('%Y-%m-%d')}"
    if directory is None:
        return f"{base}.zip"
    directory = Path(directory)
    name = f"{base}.zip"
    n = 2
    while (directory / name).exists():
        name = f"{base}-{n}.zip"
        n += 1
    return name


def backup_library(lib, out_path, progress=None) -> dict:
    """Write the one-click backup ZIP; returns the export info dict.

    Order matters: the snapshot is taken FIRST (a consistent point-in-time
    copy of the catalog), then the files are exported from the snapshot's
    connection — never from the live one. Both parts therefore describe
    the same moment, even if an import or a phone upload lands mid-backup.

    The ZIP is built as a temp file next to the destination and moved into
    place only on success, so a failed backup never leaves a half-written
    ZIP with a valid-looking name, and a file that already sits at
    out_path is never destroyed by a failed run. Files the catalog lists
    but whose disk copy is gone are skipped (reported as ``missing`` in
    the returned info) instead of aborting the whole backup.
    """
    out_path = Path(out_path)
    tmp_zip: Path | None = None
    try:
        with tempfile.TemporaryDirectory() as td:
            snapshot = Path(td) / "catalog.db"
            # conn.backup() copies the database INCLUDING committed WAL
            # content — never zip catalog.db directly, a live WAL file is
            # not a snapshot. The destination is closed BEFORE the temp dir
            # cleanup: an open handle would make Windows refuse to delete
            # the folder.
            dst = sqlite3.connect(snapshot)
            try:
                lib.conn.backup(dst)
            finally:
                dst.close()
            # Read the file list from the snapshot, not the live DB: the
            # manifest and the catalog inside one ZIP are one point in time.
            snap_conn = sqlite3.connect(snapshot)
            snap_conn.row_factory = sqlite3.Row
            try:
                ids = [r["id"] for r in snap_conn.execute(
                    "SELECT id FROM files ORDER BY id")]
                fd, tmp_name = tempfile.mkstemp(
                    prefix=out_path.stem + ".", suffix=".tmp.zip",
                    dir=str(out_path.parent))
                os.close(fd)
                tmp_zip = Path(tmp_name)
                info = export_package(
                    snap_conn, lib.files_dir, ids, tmp_zip,
                    progress=progress, stored_names=True, skip_missing=True)
                with zipfile.ZipFile(tmp_zip, "a",
                                     zipfile.ZIP_DEFLATED) as zf:
                    zf.write(snapshot, "catalog.db")
                    zf.writestr("RESTORE-راهنما.txt", _RESTORE_GUIDE)
            finally:
                snap_conn.close()
        os.replace(tmp_zip, out_path)
        tmp_zip = None
        info["path"] = str(out_path)
        return info
    finally:
        # Only ever remove the temp file this run created; a pre-existing
        # file at out_path is left exactly as it was.
        if tmp_zip is not None and tmp_zip.exists():
            tmp_zip.unlink(missing_ok=True)
