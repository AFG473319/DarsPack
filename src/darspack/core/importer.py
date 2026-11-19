"""Import pipeline (وارد کردن فایل): copy into the library and catalog it.

Per file: hash the source → duplicate check (one short transaction) →
copy to a tmp name (outside any transaction) → one short transaction
that re-checks the duplicate, inserts the row, renames atomically and
updates stored_name. The slow work — hashing and copying — never holds
SQLite's write lock, so a big import can no longer starve a concurrent
phone upload (H1). If anything fails before the commit, the row rolls
back and the leftover tmp file is swept the next time the library
opens. An identical hash already in the library is *reported and
skipped* — the user can override with keep_duplicate
(«با وجود این نگه دار»); nothing is ever overwritten.
"""
from __future__ import annotations

import datetime as _dt
import os
import shutil
import uuid
from contextlib import contextmanager
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
    # Contract for the classify dialog: imports may carry pre-fill metadata,
    # {"subject": str, "tags": [str]} carried back from a package manifest.
    # The importer NEVER stores them itself — pre-fill only.
    prefill: dict | None = None


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


@contextmanager
def _write_tx(conn):
    """One short write transaction that takes the lock up front.

    BEGIN IMMEDIATE (not the default deferred BEGIN) so the duplicate
    re-check and the INSERT that follows it are atomic against other
    writers — a second importer can no longer slip between the check
    and the insert (M2). If the caller already holds a transaction the
    lock is already held, so the block just runs inside it — a nested
    BEGIN would raise.
    """
    if conn.in_transaction:
        yield
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def _duplicate_result(conn, sha, size, shown_name, prefill, src):
    """The duplicate path, run inside the caller's short transaction:
    record the skip (E5 stats) and report the twin by name (C4)."""
    dup = conn.execute(
        "SELECT id, original_name FROM files WHERE sha256=?", (sha,)
    ).fetchone()
    if not dup:
        return None
    conn.execute(
        """INSERT INTO import_skips(ts, sha256, size_bytes, original_name)
           VALUES (?,?,?,?)""", (_now(), sha, size, shown_name))
    return ImportResult(
        "duplicate",
        f"«{shown_name}» تکرارِ «{dup['original_name']}» است",
        path=src, existing_id=dup["id"], prefill=prefill)


def import_file(lib, src, meta: dict | None = None,
                keep_duplicate: bool = False, progress=None,
                display_name: str | None = None) -> ImportResult:
    """Import one file into the library. See the module docstring.

    display_name: what the file should be called in the catalog. It
    differs from src.name for web uploads, which arrive as temporary
    files with a random prefix.

    meta (A5): may carry "kind", "chapter", "lesson", "school_year" —
    applied like the filename suggestions — plus "subject" and "tags"
    from a درس‌پک manifest. Those two are NEVER stored (the subject is
    never auto-applied); they travel back on the result as `prefill`
    so the classify dialog can offer them for review.
    """
    src = Path(src)
    if not src.is_file():
        return ImportResult("error", f"فایل پیدا نشد: {src}")
    conn = lib.conn
    size = src.stat().st_size          # the ONLY stat: hashing reuses it
    sha = sha256_file(src, progress, size=size)

    shown_name = display_name or src.name
    suggestion = suggest(Path(shown_name).stem)
    meta = meta or {}
    kind = meta.get("kind") or suggestion["kind"]
    # The SUBJECT is deliberately NOT auto-applied: categorizing is the
    # app's main job and belongs to the user. Suggestions only pre-fill
    # the classification dialog; until then the file counts as
    # unclassified («بدون درس») so the app keeps asking.
    subject_id = None
    prefill = None
    if meta.get("subject") or meta.get("tags"):
        prefill = {"subject": meta.get("subject"),
                   "tags": list(meta.get("tags") or [])}

    # H1: the copy used to run INSIDE the write transaction, so a big
    # file held the lock for the whole copy and a concurrent phone
    # upload failed with "database is locked". The slow work is now
    # split around two short transactions; only the second one —
    # insert + rename + stored_name update — runs next to the copy.
    if not keep_duplicate:
        # Fast pre-check: skip copying a file we already have. The
        # check inside the transaction below is the authoritative one
        # — this only avoids wasted copies.
        with _write_tx(conn):
            dup_result = _duplicate_result(
                conn, sha, size, shown_name, prefill, src)
            if dup_result is not None:
                return dup_result

    # Copy outside any transaction. The name is random — the file id
    # only exists after the INSERT — and a crash leaves a tmp_* file
    # the next library open sweeps, exactly as before.
    tmp = lib.files_dir / f"tmp_{uuid.uuid4().hex}{src.suffix}"
    shutil.copy2(src, tmp)
    try:
        with _write_tx(conn):
            # Authoritative re-check (M2): another importer may have
            # landed the same content while we were copying.
            if not keep_duplicate:
                dup_result = _duplicate_result(
                    conn, sha, size, shown_name, prefill, src)
                if dup_result is not None:
                    return dup_result

            cur = conn.execute(
                """INSERT INTO files(stored_name, original_name, name_norm,
                   size_bytes, sha256, imported_at, subject_id, chapter,
                   lesson, school_year, kind)
                   VALUES ('', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (shown_name, match_key(shown_name), size, sha, _now(),
                 subject_id,
                 meta.get("chapter", suggestion["chapter"]),
                 meta.get("lesson", suggestion["lesson"]),
                 meta.get("school_year", current_school_year()),
                 kind))
            file_id = cur.lastrowid

            final = lib.files_dir / f"{file_id:06d}{src.suffix}"
            os.replace(tmp, final)  # atomic rename on the same volume
            conn.execute("UPDATE files SET stored_name=? WHERE id=?",
                         (final.name, file_id))
            db.log(conn, "import", f"{shown_name} → {final.name}")
    finally:
        tmp.unlink(missing_ok=True)
    return ImportResult("imported", f"«{shown_name}» وارد شد",
                        path=src, file_id=file_id, prefill=prefill)


def iter_files(paths):
    """Expand a mix of files and folders into individual files (sorted)."""
    for p in map(Path, paths):
        if p.is_dir():
            yield from sorted(q for q in p.rglob("*") if q.is_file())
        else:
            yield p


def import_paths(lib, paths, keep_duplicates=False, progress=None) -> list[ImportResult]:
    """Import many files/folders; one ImportResult per file.

    A file that raises (locked by another program, unreadable) becomes
    an 'error' result — one bad file must not abort the whole batch.
    """
    results: list[ImportResult] = []
    for p in iter_files(paths):
        try:
            results.append(import_file(lib, p, keep_duplicate=keep_duplicates,
                                       progress=progress))
        except Exception as exc:   # report and keep going — never crash the batch
            results.append(ImportResult(
                "error", f"{p.name}: {exc.__class__.__name__}", path=p))
    return results
