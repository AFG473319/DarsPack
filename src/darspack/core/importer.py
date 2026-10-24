"""Import pipeline (وارد کردن فایل): copy into the library and catalog it.

Per file: hash the source → duplicate check → copy to a tmp name →
atomic rename → single DB transaction. If anything fails before the
commit, the row rolls back and the leftover tmp file is swept the next
time the library opens. An identical hash already in the library is
*reported and skipped* — the user can override with keep_duplicate
(«با وجود این نگه دار»); nothing is ever overwritten.
"""
from __future__ import annotations

import datetime as _dt
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import db
from .hashing import sha256_file
from .normalize import match_key
from .suggest import suggest
from .schoolyear import current_school_year


@dataclass
class ImportResult:
    status: str            # "imported" | "duplicate" | "error"
    message_fa: str
    path: Path | None = None
    file_id: int | None = None
    existing_id: int | None = None


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def import_file(lib, src, meta: dict | None = None,
                keep_duplicate: bool = False, progress=None,
                display_name: str | None = None) -> ImportResult:
    """Import one file into the library. See the module docstring.

    display_name: what the file should be called in the catalog. It
    differs from src.name for web uploads, which arrive as temporary
    files with a random prefix.
    """
    src = Path(src)
    if not src.is_file():
        return ImportResult("error", f"فایل پیدا نشد: {src}")
    conn = lib.conn
    sha = sha256_file(src, progress)
    size = src.stat().st_size

    shown_name = display_name or src.name
    suggestion = suggest(Path(shown_name).stem)
    meta = meta or {}
    kind = meta.get("kind") or suggestion["kind"]
    subject_id = (db.get_or_create(conn, "subjects",
                                   meta.get("subject")
                                   or suggestion["subject"])
                  if (meta.get("subject") or suggestion["subject"]) else None)

    with conn:  # one transaction — everything commits, or nothing does
        dup = conn.execute(
            "SELECT id, original_name FROM files WHERE sha256=?", (sha,)
        ).fetchone()
        if dup and not keep_duplicate:
            return ImportResult(
                "duplicate",
                f"«{shown_name}» از قبل در کتابخانه هست",
                path=src, existing_id=dup["id"])

        cur = conn.execute(
            """INSERT INTO files(stored_name, original_name, name_norm,
               size_bytes, sha256, imported_at, subject_id, chapter,
               school_year, kind)
               VALUES ('', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (shown_name, match_key(shown_name), size, sha, _now(),
             subject_id,
             meta.get("chapter", suggestion["chapter"]),
             meta.get("school_year", current_school_year()),
             kind))
        file_id = cur.lastrowid

        tmp = lib.files_dir / f"tmp_{file_id}{src.suffix}"
        shutil.copy2(src, tmp)
        final = lib.files_dir / f"{file_id:06d}{src.suffix}"
        os.replace(tmp, final)  # atomic rename on the same volume
        conn.execute("UPDATE files SET stored_name=? WHERE id=?",
                     (final.name, file_id))
        db.log(conn, "import", f"{shown_name} → {final.name}")
    return ImportResult("imported", f"«{shown_name}» وارد شد",
                        path=src, file_id=file_id)


def iter_files(paths):
    """Expand a mix of files and folders into individual files (sorted)."""
    for p in map(Path, paths):
        if p.is_dir():
            yield from sorted(q for q in p.rglob("*") if q.is_file())
        else:
            yield p


def import_paths(lib, paths, keep_duplicates=False, progress=None) -> list[ImportResult]:
    """Import many files/folders; one ImportResult per file."""
    return [import_file(lib, p, keep_duplicate=keep_duplicates, progress=progress)
            for p in iter_files(paths)]
