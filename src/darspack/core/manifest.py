"""Portable learning packages (بسته‌ی درس‌پک).

A package is a plain ZIP with three parts:

    manifest.json   machine-readable list: every file's original name,
                    subject/chapter/kind, size and SHA-256
    files/…         the files themselves
    index.html      a Persian RTL list that opens in any browser —
                    the package explains itself without DarsPack

verify_package() re-hashes every member and reports exactly what is
missing or changed. It never repairs anything — the recipient decides
what to do.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import html
import json
import os
import re
import tempfile
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path

FORMAT = "darspack-package"
VERSION = 1

# Members that belong to a full-library backup, not to a plain درس‌پک —
# verify ignores them instead of reporting them as extras (additive: a
# backup therefore verifies as a package too).
KNOWN_EXTRA_MEMBERS = {"catalog.db", "RESTORE-راهنما.txt"}

_UNSAFE_CHARS = re.compile(r'[\\/:*?"<>|\r\n]+')


def safe_name(name: str) -> str:
    """Turn a filename into a safe ZIP member name (Persian kept)."""
    return _UNSAFE_CHARS.sub("_", name).strip() or "file"


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def _fetch_entries(conn, file_ids) -> list[dict]:
    """Manifest entries for `file_ids`, in the order given (B13).

    Chunked IN queries stay well below SQLite's variable limit even when
    exporting thousands of files at once.
    """
    ids = list(file_ids)
    if not ids:
        return []
    rows = {}
    tags: dict[int, list[str]] = {}
    chunk_size = 500
    for start in range(0, len(ids), chunk_size):
        chunk = ids[start:start + chunk_size]
        marks = ",".join("?" * len(chunk))
        for row in conn.execute(
                f"""SELECT f.*, s.name AS subject_name
                    FROM files f LEFT JOIN subjects s ON s.id = f.subject_id
                    WHERE f.id IN ({marks})""", chunk):
            rows[row["id"]] = row
        for tag in conn.execute(
                f"""SELECT ft.file_id, t.name FROM tags t
                    JOIN file_tags ft ON ft.tag_id = t.id
                    WHERE ft.file_id IN ({marks})""", chunk):
            tags.setdefault(tag["file_id"], []).append(tag["name"])
    entries = []
    for file_id in ids:
        row = rows.get(file_id)
        if row is None:
            raise KeyError(f"file id {file_id} not found in catalog")
        entries.append({
            "name": row["original_name"],
            "sha256": row["sha256"],
            "size": row["size_bytes"],
            "subject": row["subject_name"],
            "chapter": row["chapter"],
            "lesson": row["lesson"],
            "school_year": row["school_year"],
            "kind": row["kind"],
            "tags": tags.get(file_id, []),
            "stored_name": row["stored_name"],   # internal; removed from manifest
        })
    return entries


def export_package(conn, files_dir, file_ids, out_path, progress=None,
                   stored_names: bool = False, skip_missing: bool = False) -> dict:
    """Write a درس‌پک ZIP for the given catalog ids. Returns package info.

    With skip_missing=True (the backup path), a catalogued file whose disk
    copy is gone is skipped instead of aborting the whole export: it is
    left out of the manifest and reported in the returned ``missing`` list
    (with ``missing_count``), so the ZIP that comes out is complete and
    verifiable. With skip_missing=False (the default, plain package
    export) a missing file still raises FileNotFoundError as before.

    The ZIP is staged into a temporary file next to ``out_path`` and moved
    into place atomically only on success, so an interrupted export never
    destroys an existing file or leaves a half-written archive behind.
    """
    # By default each member is filed under a friendly «NNN - name» label,
    # which keeps a shipped package browsable. A full-library backup passes
    # stored_names=True: it keeps the catalog's own internal names
    # (files/000001.pdf) instead. That matters because the backup ALSO carries
    # a catalog.db snapshot whose rows point at those stored names — with
    # friendly labels a restore leaves the copied files unreferenced, and the
    # next startup's orphan sweep deletes them (data loss). Fixed 2026-11-17.
    entries = _fetch_entries(conn, file_ids)
    manifest = {"format": FORMAT, "version": VERSION, "created": _now(),
                "files": []}
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    missing: list[str] = []
    kept = 0
    fd, tmp_name = tempfile.mkstemp(
        prefix=out_path.stem + ".", suffix=".tmp.zip",
        dir=str(out_path.parent))
    os.close(fd)
    tmp_path: Path | None = Path(tmp_name)
    try:
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for entry in entries:
                stored = entry.pop("stored_name")
                src = Path(files_dir) / stored
                if not stored or not src.is_file():
                    if skip_missing:
                        missing.append(entry["name"])
                        continue
                    raise FileNotFoundError(
                        f"file missing on disk: {src} "
                        f"(catalogued as {entry['name']!r})")
                kept += 1
                if stored_names:
                    arc = f"files/{stored}"
                else:
                    arc = f"files/{kept:03d} - {safe_name(entry['name'])}"
                zf.write(src, arc)
                entry["path"] = arc
                manifest["files"].append(entry)
                if progress is not None:
                    progress(kept, len(entries))
            manifest_bytes = json.dumps(
                manifest, ensure_ascii=False, indent=2).encode("utf-8")
            zf.writestr("manifest.json", manifest_bytes)
            zf.writestr("index.html", make_index_html(manifest).encode("utf-8"))
        os.replace(tmp_path, out_path)
        tmp_path = None
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
    return {
        "path": str(out_path),
        "count": len(manifest["files"]),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "missing": missing,
        "missing_count": len(missing),
    }


def make_index_html(manifest: dict) -> str:
    """Small RTL HTML table so any browser can list the package contents."""
    rows = []
    for e in manifest["files"]:
        chapter = f"فصل {e['chapter']}" if e.get("chapter") else "—"
        rows.append(
            "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
                html.escape(e.get("name") or ""),
                html.escape(e.get("subject") or "—"),
                html.escape(chapter),
                html.escape(e.get("kind") or "—")))
    return f"""<!doctype html>
<html lang="fa" dir="rtl"><head><meta charset="utf-8">
<title>درس‌پک — فهرست بسته</title>
<style>
 body {{ font-family: Tahoma, sans-serif; direction: rtl; margin: 2rem; }}
 table {{ border-collapse: collapse; width: 100%; }}
 td, th {{ border: 1px solid #ccc; padding: 0.4rem 0.6rem; text-align: right; }}
</style></head><body>
<h1>درس‌پک</h1>
<p>{len(rows)} فایل — ساخته‌شده در {html.escape(manifest['created'])}</p>
<table><tr><th>نام فایل</th><th>درس</th><th>فصل</th><th>نوع</th></tr>
{''.join(rows)}</table></body></html>"""


def read_manifest(zip_path) -> list[dict]:
    """Parse a package's manifest.json back into its entry list (A5).

    Pure function: it touches nothing outside the ZIP. The caller (the
    package-import dialog) matches entries to extracted files by the arc
    `path` — unique even when two files share a display name — and feeds
    each entry to the importer as `meta`, with subject/tags kept as
    pre-fill only. Raises KeyError on a ZIP without a manifest; callers
    verify the package first.
    """
    with zipfile.ZipFile(zip_path) as zf:
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        raise KeyError("not a darspack package manifest")
    files = manifest.get("files")
    if not isinstance(files, list):
        raise KeyError("invalid darspack manifest file list")
    return list(files)


@dataclass
class VerifyReport:
    ok: bool
    problems: list = field(default_factory=list)   # Persian messages


def verify_package(zip_path, progress=None) -> VerifyReport:
    """Check a package against its manifest: missing / size / SHA-256."""
    problems: list[str] = []
    try:
        zf_cm = zipfile.ZipFile(zip_path)
    except (zipfile.BadZipFile, OSError):
        return VerifyReport(False, ["فایل بسته معتبر نیست یا باز نشد"])
    with zf_cm as zf:
        names = set(zf.namelist())
        try:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        except KeyError:
            return VerifyReport(False, ["manifest.json در بسته نیست — بسته معتبر نیست"])
        except (json.JSONDecodeError, UnicodeDecodeError,
                zipfile.BadZipFile, zlib.error, EOFError, RuntimeError, OSError):
            return VerifyReport(False, ["manifest.json مخدوش است — بسته معتبر نیست"])

        if not isinstance(manifest, dict):
            return VerifyReport(False, ["ساختار manifest.json معتبر نیست"])
        if manifest.get("format") != FORMAT:
            return VerifyReport(False, ["این فایل یک بسته‌ی معتبر درس‌پک نیست"])
        files = manifest.get("files")
        if not isinstance(files, list):
            return VerifyReport(False, ["فهرست فایل‌ها در manifest.json معتبر نیست"])

        listed = set()
        for entry in files:
            if not isinstance(entry, dict):
                problems.append("رکورد نامعتبر در فهرست بسته")
                continue
            arc = entry.get("path")
            name = str(entry.get("name") or arc or "؟")
            if progress is not None:
                progress(name, arc if isinstance(arc, str) else "")
            if not isinstance(arc, str) or not arc or arc not in names:
                problems.append(f"گم‌شده: {name} ({arc})")
                continue
            listed.add(arc)
            if zf.getinfo(arc).file_size != entry.get("size"):
                problems.append(f"اندازه‌ی فایل متفاوت است: {name}")
                continue
            digest = hashlib.sha256()
            try:
                with zf.open(arc) as f:
                    for chunk in iter(lambda: f.read(1 << 20), b""):
                        digest.update(chunk)
            except (zipfile.BadZipFile, zlib.error, EOFError, RuntimeError, OSError):
                problems.append(f"خراب یا ناخوانا: {name}")
                continue
            if digest.hexdigest() != entry.get("sha256"):
                problems.append(f"خراب یا تغییرکرده: {name}")

        for extra in sorted(names - listed - {"manifest.json", "index.html"}
                            - KNOWN_EXTRA_MEMBERS):
            problems.append(f"فایل اضافه در بسته: {extra}")
    return VerifyReport(ok=not problems, problems=problems)
