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
Fixed 2026-11-17; see tests/test_backup.py.
"""
from __future__ import annotations

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
هنگام باز شدن برنامه، پاکسازی فایل‌های بی‌صاحب آنها را حذف می‌کند و بررسی
سلامت، ردیف‌های کاتالوگ را گم‌شده علامت‌گذاری می‌کند (از دست رفتن
جزوه‌ها).

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


def backup_filename(today=None) -> str:
    """Jalali-dated name for the backup ZIP: darspack-backup-1405-08-02.zip."""
    if today is None:
        import datetime as _dt
        today = _dt.date.today()
    jalali = jdatetime.date.fromgregorian(date=today)
    return f"darspack-backup-{jalali.strftime('%Y-%m-%d')}.zip"


def backup_library(lib, out_path, progress=None) -> dict:
    """Write the one-click backup ZIP; returns the export info dict.

    Order matters: the snapshot is taken FIRST (a consistent point-in-time
    copy of the catalog), then the files are exported from the same
    connection. Both parts live in one ZIP so nothing can half-arrive.
    """
    out_path = Path(out_path)
    ids = [r["id"] for r in lib.conn.execute("SELECT id FROM files ORDER BY id")]
    info = export_package(lib.conn, lib.files_dir, ids, out_path,
                          progress=progress, stored_names=True)
    with tempfile.TemporaryDirectory() as td:
        snapshot = Path(td) / "catalog.db"
        # conn.backup() copies the database INCLUDING committed WAL content —
        # never zip catalog.db directly, a live WAL file is not a snapshot.
        # The destination is closed BEFORE the temp dir cleanup: an open
        # handle would make Windows refuse to delete the folder.
        dst = sqlite3.connect(snapshot)
        try:
            lib.conn.backup(dst)
        finally:
            dst.close()
        with zipfile.ZipFile(out_path, "a", zipfile.ZIP_DEFLATED) as zf:
            zf.write(snapshot, "catalog.db")
            zf.writestr("RESTORE-راهنما.txt", _RESTORE_GUIDE)
    return info
