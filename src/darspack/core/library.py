"""The DarsPack library: one folder holding catalog.db + files/ (کتابخانه).

Files are *copied* in at import time; originals are never touched. The
files/ folder is deliberately flat (files/000123.pdf): the database is
the organizer, so no folder tree can drift out of sync with the
metadata, and renaming a subject never moves a byte on disk.
"""
from __future__ import annotations

from pathlib import Path

from . import db


class Library:
    def __init__(self, root):
        self.root = Path(root)
        self.db_path = self.root / "catalog.db"
        self.files_dir = self.root / "files"
        self.conn = None

    def open(self) -> "Library":
        self.root.mkdir(parents=True, exist_ok=True)
        self.files_dir.mkdir(exist_ok=True)
        self.conn = db.connect(self.db_path)
        db.init_schema(self.conn)
        self.sweep_orphans()
        return self

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
