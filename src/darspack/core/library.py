"""The DarsPack library: one folder holding catalog.db + files/ (کتابخانه).

Files are *copied* in at import time; originals are never touched. The
files/ folder is deliberately flat (files/000123.pdf): the database is
the organizer, so no folder tree can drift out of sync with the
metadata, and renaming a subject never moves a byte on disk.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from . import db
from .hashing import sha256_file
from .normalize import normalize
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

    @property
    def trash_dir(self) -> Path:
        return self.files_dir / ".trash"

    @property
    def trash_meta_dir(self) -> Path:
        return self.files_dir / ".trash_meta"

    def list_trash(self) -> list[dict]:
        """List files currently in files/.trash/ with metadata."""
        if not self.trash_dir.exists():
            return []
        items = []
        for p in self.trash_dir.iterdir():
            if not p.is_file():
                continue
            meta_path = self.trash_meta_dir / f"{p.name}.json"
            meta = {}
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except Exception:
                    pass
            stat = p.stat()
            deleted_at = meta.get("deleted_at") or datetime.fromtimestamp(stat.st_mtime).isoformat()
            items.append({
                "trash_name": p.name,
                "original_name": meta.get("original_name") or p.name,
                "stored_name": meta.get("stored_name") or p.name,
                "size": stat.st_size,
                "deleted_at": deleted_at,
                "subject_name": meta.get("subject_name") or "?",
                "kind": meta.get("kind") or "?",
                "chapter": meta.get("chapter"),
                "lesson": meta.get("lesson"),
                "school_year": meta.get("school_year"),
                "sha256": meta.get("sha256"),
                "note": meta.get("note", ""),
                "meta": meta,
            })
        items.sort(key=lambda x: x["deleted_at"], reverse=True)
        return items

    def restore_trash_file(self, trash_filename: str) -> dict:
        """Restore a single file from .trash back into files/ and catalog."""
        clean_name = Path(trash_filename).name
        src = self.trash_dir / clean_name
        if not src.exists():
            raise FileNotFoundError(f"Trash file not found: {trash_filename}")

        meta_path = self.trash_meta_dir / f"{clean_name}.json"
        meta = {}
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        original_name = meta.get("original_name") or clean_name
        # Find a non-colliding stored name in files/
        base_stored = meta.get("stored_name") or clean_name
        dest = self.files_dir / base_stored
        p_base = Path(base_stored)
        n = 0
        while dest.exists():
            n += 1
            dest = self.files_dir / f"{p_base.stem}~{n}{p_base.suffix}"

        sha = meta.get("sha256")
        size = src.stat().st_size
        if not sha:
            sha = sha256_file(src)

        subject_id = meta.get("subject_id")
        subject_name = meta.get("subject_name")
        if not subject_id and subject_name:
            sub_row = self.conn.execute(
                "SELECT id FROM subjects WHERE name=?", (subject_name,)).fetchone()
            if sub_row:
                subject_id = sub_row["id"]

        imported_at = meta.get("imported_at") or datetime.now().isoformat()
        tags = meta.get("tags") or []

        # Atomic restore: file move is performed inside the DB transaction.
        # If filesystem move fails, SQLite transaction rolls back.
        # If DB insert fails, the file has not been moved from .trash/ yet.
        with self.conn:
            cur = self.conn.execute(
                """INSERT INTO files
                   (stored_name, original_name, name_norm, sha256, size_bytes,
                    imported_at, subject_id, chapter, lesson, kind,
                    school_year, available, note)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)""",
                (dest.name, original_name, normalize(original_name), sha, size,
                 imported_at, subject_id, meta.get("chapter"),
                 meta.get("lesson"), meta.get("kind"), meta.get("school_year"),
                 meta.get("note", "")))
            new_id = cur.lastrowid

            for t in tags:
                if t and str(t).strip():
                    tag_id = db.get_or_create(self.conn, "tags", str(t).strip())
                    self.conn.execute(
                        "INSERT OR IGNORE INTO file_tags (file_id, tag_id) VALUES (?, ?)",
                        (new_id, tag_id))

            db.log(self.conn, "restore", f"{original_name} (id={new_id})")

            os.replace(src, dest)
            meta_path.unlink(missing_ok=True)

        return {"id": new_id, "original_name": original_name, "stored_name": dest.name}

    def empty_trash(self) -> int:
        """Permanently delete all files currently in files/.trash/."""
        if not self.trash_dir.exists():
            return 0
        count = 0
        for p in list(self.trash_dir.iterdir()):
            if p.is_file():
                p.unlink(missing_ok=True)
                count += 1
        if self.trash_meta_dir.exists():
            for m in list(self.trash_meta_dir.iterdir()):
                if m.is_file():
                    m.unlink(missing_ok=True)
        if self.conn:
            db.log(self.conn, "empty_trash", f"{count} files permanently deleted")
        return count
