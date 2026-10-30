"""The DarsPack library: one folder holding catalog.db + files/ (کتابخانه).

Files are *copied* in at import time; originals are never touched. The
files/ folder is deliberately flat (files/000123.pdf): the database is
the organizer, so no folder tree can drift out of sync with the
metadata, and renaming a subject never moves a byte on disk.
"""
from __future__ import annotations

from pathlib import Path

from . import db
from .suggest import DEFAULT_SUBJECTS


class Library:
    def __init__(self, root, maintain: bool = True):
        self.root = Path(root)
        self.maintain = maintain
        self.db_path = self.root / "catalog.db"
        self.files_dir = self.root / "files"
        self.conn = None

    def open(self) -> "Library":
        self.root.mkdir(parents=True, exist_ok=True)
        self.files_dir.mkdir(exist_ok=True)
        self.conn = db.connect(self.db_path)
        if self.maintain:
            db.init_schema(self.conn)      # creates tables + runs migrations
            self.seed_subjects()
            self.sweep_orphans()
            self.health_check()
        return self

    def seed_subjects(self) -> None:
        """Pre-fill the subjects table on a brand-new library only (A1).

        The classify dialog's subject combo reads this table — on a fresh
        install it would be empty and the user would type «ریاضی»
        letter-by-letter for a dozen imports. An existing library is never
        touched: the user's own subjects are authoritative.
        """
        count = self.conn.execute("SELECT COUNT(*) c FROM subjects").fetchone()["c"]
        if count:
            return
        with self.conn:
            for name in DEFAULT_SUBJECTS:
                db.get_or_create(self.conn, "subjects", name)
            db.log(self.conn, "seed_subjects", f"{len(DEFAULT_SUBJECTS)} درس پیش‌فرض")

    def health_check(self) -> int:
        """Verify every stored file is still on disk (B1) — return how many are not.

        DarsPack's headline promise is «یک بار ذخیره کن، برای همیشه نگه
        دار», but a file can vanish behind the catalog's back (bad USB
        sync, antivirus, an over-eager cleaner). A row whose file is
        missing or whose size no longer matches gets available=0; a row
        whose file is fine gets reset to 1 (heals the flag after the file
        is re-imported). One stat per file — milliseconds even for
        thousands; the full re-hash stays in package verify, on demand.
        """
        rows = self.conn.execute(
            "SELECT id, stored_name, size_bytes, available FROM files").fetchall()
        missing = []
        for row in rows:
            path = self.files_dir / row["stored_name"]
            try:
                ok = path.is_file() and path.stat().st_size == row["size_bytes"]
            except OSError:            # unreadable/locked counts as missing
                ok = False
            if not ok:
                missing.append(row["id"])
            elif row["available"] != 1:
                missing.append(-row["id"])   # negative id = "flag to clear"
        if not missing:
            return 0
        with self.conn:                # single transaction for the whole pass
            for value in missing:
                if value > 0:
                    self.conn.execute(
                        "UPDATE files SET available=0 WHERE id=?", (value,))
                else:
                    self.conn.execute(
                        "UPDATE files SET available=1 WHERE id=?", (-value,))
            db.log(self.conn, "healthcheck", f"missing={len(missing)}")
        return len(missing)

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def __enter__(self) -> "Library":
        return self.open()

    def __exit__(self, *exc) -> None:
        self.close()

    def sweep_orphans(self) -> None:
        """Reconcile files/ with the catalog after an interrupted import.

        Two kinds of leftovers can exist after a crash: tmp_* copies made
        before the atomic rename, and a numbered file whose row rolled
        back. Both are safe to delete — the catalog is the source of truth.
        """
        if self.conn is None:
            for p in self.files_dir.glob("tmp_*"):
                p.unlink(missing_ok=True)
            return
        known = {r["stored_name"] for r in self.conn.execute(
            "SELECT stored_name FROM files")}
        for p in self.files_dir.iterdir():
            if p.is_file() and p.name not in known:
                p.unlink(missing_ok=True)

    def stored_path(self, row) -> Path:
        """Absolute path of a catalog row's file inside the library."""
        return self.files_dir / row["stored_name"]
