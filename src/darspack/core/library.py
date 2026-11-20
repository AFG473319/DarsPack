"""The DarsPack library: one folder holding catalog.db + files/ (کتابخانه).

Files are *copied* in at import time; originals are never touched. The
files/ folder is deliberately flat (files/000123.pdf): the database is
the organizer, so no folder tree can drift out of sync with the
metadata, and renaming a subject never moves a byte on disk.
"""
from __future__ import annotations

import json
import os
import time
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

    @classmethod
    def for_background(cls, root) -> "Library":
        """Open a library for a worker thread without the startup passes.

        The desktop window opens the library — seeding, orphan sweep,
        health check — before any worker starts, so re-running those on
        every import/export/stats batch is pure repeated work (the health
        check alone stats every file in the library). A folder with no
        catalog yet (a test, a script, a first run) still gets the full
        one-time setup, so a worker never lands on a missing schema.

        Returns an ALREADY OPENED library: call it instead of
        `Library(root).open()`, not in addition to it (a second open()
        would make a second connection and leak the first).
        """
        fresh = not (Path(root) / "catalog.db").exists()
        return cls(root, maintain=fresh).open()

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

    # A tmp_* copy younger than this may be an in-flight import from
    # another process (desktop import, phone upload, MCP): the sweep
    # must leave it alone (H4).
    TMP_FRESH_SECONDS = 300

    def _is_fresh_tmp(self, p: Path) -> bool:
        """True if `p` is a tmp_* copy younger than TMP_FRESH_SECONDS."""
        if not p.name.startswith("tmp_"):
            return False
        try:
            age = time.time() - p.stat().st_mtime
        except OSError:
            return False
        return age < self.TMP_FRESH_SECONDS

    def _log_sweep(self, action: str, detail: str) -> None:
        """Best-effort activity-log entry; a logging failure must never
        break the sweep itself."""
        if self.conn is None:
            return
        try:
            with self.conn:
                db.log(self.conn, action, detail)
        except Exception:
            pass

    def _trash_dest_for(self, name: str) -> Path:
        """A non-colliding path inside .trash for `name`."""
        self.trash_dir.mkdir(exist_ok=True)
        dest = self.trash_dir / name
        stem, suffix = Path(name).stem, Path(name).suffix
        n = 0
        while dest.exists():
            n += 1
            dest = self.trash_dir / f"{stem}~{n}{suffix}"
        return dest

    def _sweep_one(self, p: Path) -> None:
        """Deal with one leftover file from the sweep.

        A tmp_* partial import is deleted (and logged). Anything else
        is a file the user dropped into files/ by hand — it is moved
        to .trash, logged with name, size and SHA, and never deleted
        silently (M5). A file that cannot be removed or moved — locked
        by another program, antivirus holding a just-copied file — is
        skipped and logged instead of stopping the app from starting
        (H4).
        """
        name = p.name
        if name.startswith("tmp_"):
            try:
                size = p.stat().st_size
                p.unlink(missing_ok=True)
            except OSError:
                self._log_sweep("sweep_skip", f"{name} (locked, left in place)")
                return
            self._log_sweep("sweep", f"{name} ({size} bytes, partial import)")
            return
        try:
            size = p.stat().st_size
            digest = sha256_file(p)
        except OSError:
            self._log_sweep("sweep_skip", f"{name} (unreadable, left in place)")
            return
        dest = self._trash_dest_for(name)
        try:
            os.replace(p, dest)
        except OSError:
            self._log_sweep("sweep_skip", f"{name} (locked, left in place)")
            return
        self._log_sweep(
            "sweep", f"{name} → .trash ({size} bytes, sha256={digest})")

    def sweep_orphans(self) -> None:
        """Reconcile files/ with the catalog after an interrupted import.

        Two kinds of leftovers can exist after a crash: tmp_* copies made
        before the atomic rename, and a numbered file whose row rolled
        back. Both are safe to delete — the catalog is the source of truth.

        Nothing is deleted before a rescue pass (see _rescue_unknowns):
        an unknown file whose SHA-256 matches a catalog row that lost its
        own file is renamed into place instead of swept. This is what
        makes a backup made before 2026-11-17 (members filed under
        friendly «NNN - name» labels) safe to restore with the guide's
        manual steps.

        Robustness (H4, M5): a file that cannot be removed, renamed or
        moved is skipped and logged instead of raising out of open();
        a tmp_* copy younger than a few minutes is left alone because
        it may be an in-flight import from another process; and files
        the user dropped into files/ by hand are moved to .trash (with
        a log record) instead of being deleted silently.
        """
        if self.conn is None:
            for p in self.files_dir.glob("tmp_*"):
                if self._is_fresh_tmp(p):
                    continue
                try:
                    p.unlink(missing_ok=True)
                except OSError:
                    continue  # locked: leave it for the next open
            return
        known = {r["stored_name"] for r in self.conn.execute(
            "SELECT stored_name FROM files")}
        unknown = [p for p in self.files_dir.iterdir()
                   if p.is_file() and p.name not in known]
        if unknown:
            self._rescue_unknowns(unknown)
            unknown = [p for p in unknown if p.is_file()]
        for p in unknown:
            if self._is_fresh_tmp(p):
                continue
            self._sweep_one(p)

    def _rescue_unknowns(self, paths) -> int:
        """Rename files the catalog doesn't know into rows that lost their file.

        A full-library backup made before 2026-11-17 filed its members
        under friendly display labels («001 - جزوه.pdf»), while the
        catalog.db snapshot inside the same ZIP still points at the
        internal stored names (files/000001.pdf). Restoring such a backup
        per its own guide copies files no row knows by name — and this
        sweep then erased every one of them on the next open (data loss).
        The fix for NEW backups (stored_names=True in export_package)
        shipped the same day; this pass makes the OLD backups safe too.

        Match by SHA-256 — the content's fingerprint, not the name. An
        unknown file whose hash equals a catalog row whose own file is
        missing is renamed to that row's stored name; anything with no
        such row is left for the sweep. One hash rescues at most one row,
        so duplicate rows (identical content) each need their own copy.
        """
        missing: dict[str, list[str]] = {}
        for row in self.conn.execute(
                "SELECT stored_name, sha256 FROM files"):
            if (self.files_dir / row["stored_name"]).exists():
                continue
            missing.setdefault(row["sha256"], []).append(row["stored_name"])
        if not missing:
            return 0                        # nothing is lost → nothing to rescue
        rescued = 0
        for p in paths:
            try:
                digest = sha256_file(p)
            except OSError:                 # unreadable: not rescuable today
                continue
            stored_names = missing.get(digest)
            if not stored_names:
                continue                    # nobody is waiting for this content
            stored_name = stored_names[0]
            try:
                p.rename(self.files_dir / stored_name)   # same folder: atomic
            except OSError:
                continue  # locked: the sweep leaves it in place, logged
            stored_names.pop(0)
            if not stored_names:
                del missing[digest]
            rescued += 1
            with self.conn:
                db.log(self.conn, "rescue", f"{p.name} → {stored_name}")
        return rescued

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
                "kind": meta.get("kind") or "",
                "chapter": meta.get("chapter"),
                "lesson": meta.get("lesson"),
                "school_year": meta.get("school_year"),
                "sha256": meta.get("sha256"),
                "note": meta.get("note", ""),
                "meta": meta,
            })
        items.sort(key=lambda x: x["deleted_at"], reverse=True)
        return items

    def move_to_trash(self, file_id: int) -> dict:
        """Safely move a file from files/ to files/.trash/ and remove its catalog row."""
        row = self.conn.execute(
            """SELECT f.*, s.name AS subject_name FROM files f
               LEFT JOIN subjects s ON s.id=f.subject_id WHERE f.id=?""",
            (file_id,)).fetchone()
        if row is None:
            raise KeyError(f"File id {file_id} not found in catalog")

        self.trash_dir.mkdir(exist_ok=True)
        self.trash_meta_dir.mkdir(exist_ok=True)

        stored_p = Path(row["stored_name"])
        dest = self.trash_dir / row["stored_name"]
        n = 0
        while dest.exists():
            n += 1
            dest = self.trash_dir / f"{stored_p.stem}~{n}{stored_p.suffix}"

        src_file = self.stored_path(row)
        try:
            os.replace(src_file, dest)
            tag_rows = self.conn.execute(
                "SELECT t.name FROM tags t JOIN file_tags ft ON ft.tag_id=t.id WHERE ft.file_id=?",
                (file_id,)
            ).fetchall()
            file_tags = [r[0] for r in tag_rows]
            meta = {
                "original_name": row["original_name"],
                "stored_name": row["stored_name"],
                "subject_id": row["subject_id"],
                "subject_name": row["subject_name"],
                "chapter": row["chapter"],
                "lesson": row["lesson"] if "lesson" in row.keys() else None,
                "kind": row["kind"],
                "school_year": row["school_year"],
                "sha256": row["sha256"],
                "size": row["size_bytes"],
                "imported_at": row["imported_at"] if "imported_at" in row.keys() else None,
                "deleted_at": datetime.now().isoformat(),
                "note": row["note"] if "note" in row.keys() else "",
                "tags": file_tags,
            }
            meta_dest = self.trash_meta_dir / f"{dest.name}.json"
            meta_dest.write_text(
                json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        except FileNotFoundError:
            pass

        with self.conn:
            self.conn.execute("DELETE FROM files WHERE id=?", (file_id,))
            db.log(self.conn, "delete", row["original_name"])

        return {
            "id": file_id,
            "original_name": row["original_name"],
            "trash_name": dest.name,
        }

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

        # Always re-hash the actual file (M7): a trashed file may have
        # been altered while in trash, and the saved hash would then lie
        # about its content. A file that cannot be read fails loudly
        # here instead of being restored with a wrong hash.
        size = src.stat().st_size
        sha = sha256_file(src)

        imported_at = meta.get("imported_at") or datetime.now().isoformat()
        tags = meta.get("tags") or []

        # Atomic restore: file move is performed inside the DB transaction.
        # If filesystem move fails, SQLite transaction rolls back.
        # If DB insert fails, the file has not been moved from .trash/ yet.
        with self.conn:
            # Resolve the subject now, inside the transaction (M7): the
            # saved subject_id may point at a subject deleted since the
            # file was trashed, and the saved name may differ in spelling
            # from the current one. Matching by normalized name finds it;
            # a missing subject is recreated instead of silently leaving
            # the file as «بدون درس» or failing on the foreign key.
            subject_id = meta.get("subject_id")
            if subject_id is not None:
                row = self.conn.execute(
                    "SELECT id FROM subjects WHERE id=?",
                    (subject_id,)).fetchone()
                if row is None:
                    subject_id = None
            subject_name = meta.get("subject_name")
            if subject_id is None and subject_name:
                subject_id = db.get_or_create(
                    self.conn, "subjects", subject_name)

            # A file with this exact content may already be back in the
            # library (re-imported while it sat in trash): restoring it
            # again would create a duplicate row, so flag it instead.
            existing = self.conn.execute(
                "SELECT id FROM files WHERE sha256=?", (sha,)).fetchone()
            if existing is not None:
                raise ValueError(
                    "already in the library "
                    f"(same content as file id {existing['id']})")

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

    def empty_trash(self) -> dict:
        """Permanently delete all files currently in files/.trash/.

        Returns {"deleted": n, "failed": m, "failed_names": [...]}. A
        file that is open in another program (Windows locks it) is
        skipped instead of aborting the whole clear halfway — the user
        gets the honest count of what went and what stayed (M6). A
        file that could not be deleted keeps its metadata, so it stays
        listed in the trash instead of vanishing from the record.
        """
        deleted = 0
        failed_names: list[str] = []
        if self.trash_dir.exists():
            for p in list(self.trash_dir.iterdir()):
                if not p.is_file():
                    continue
                try:
                    p.unlink()
                except OSError:
                    failed_names.append(p.name)
                    continue
                deleted += 1
        if self.trash_meta_dir.exists():
            for m in list(self.trash_meta_dir.iterdir()):
                if not m.is_file():
                    continue
                # keep the metadata of any file that survived (failed
                # delete): it must stay listed in the trash. Drop the
                # metadata of files that are gone — just deleted, or
                # removed behind the app's back earlier.
                if (self.trash_dir / m.name[:-5]).exists():
                    continue
                try:
                    m.unlink()
                except OSError:
                    continue  # a stale meta file is harmless; leave it
        if self.conn:
            detail = f"{deleted} files permanently deleted"
            if failed_names:
                detail += f", {len(failed_names)} could not be deleted"
            db.log(self.conn, "empty_trash", detail)
        return {"deleted": deleted, "failed": len(failed_names),
                "failed_names": failed_names}
