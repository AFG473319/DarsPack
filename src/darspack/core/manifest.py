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
import re
import zipfile
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


def _fetch_entry(conn, file_id: int) -> dict:
    row = conn.execute(
        """SELECT f.*, s.name AS subject_name
           FROM files f LEFT JOIN subjects s ON s.id = f.subject_id
           WHERE f.id = ?""", (file_id,)).fetchone()
    if row is None:
        raise KeyError(f"file id {file_id} not found in catalog")
    tags = [t["name"] for t in conn.execute(
        """SELECT t.name FROM tags t
           JOIN file_tags ft ON ft.tag_id = t.id
           WHERE ft.file_id = ?""", (file_id,))]
    return {
        "name": row["original_name"],
        "sha256": row["sha256"],
        "size": row["size_bytes"],
        "subject": row["subject_name"],
        "chapter": row["chapter"],
        "lesson": row["lesson"],
        "school_year": row["school_year"],
        "kind": row["kind"],
        "tags": tags,
        "stored_name": row["stored_name"],   # internal; removed from manifest
    }


def export_package(conn, files_dir, file_ids, out_path, progress=None,
                   stored_names: bool = False) -> dict:
    """Write a درس‌پک ZIP for the given catalog ids. Returns package info."""
    # By default each member is filed under a friendly «NNN - name» label,
    # which keeps a shipped package browsable. A full-library backup passes
    # stored_names=True: it keeps the catalog's own internal names
    # (files/000001.pdf) instead. That matters because the backup ALSO carries
    # a catalog.db snapshot whose rows point at those stored names — with
    # friendly labels a restore leaves the copied files unreferenced, and the
    # next startup's orphan sweep deletes them (data loss). Fixed 2026-11-17.
    entries = [_fetch_entry(conn, fid) for fid in file_ids]
    manifest = {"format": FORMAT, "version": VERSION, "created": _now(),
                "files": entries}
    out_path = Path(out_path)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, entry in enumerate(manifest["files"], start=1):
            stored = entry.pop("stored_name")
            if stored_names:
                arc = f"files/{stored}"
            else:
                arc = f"files/{i:03d} - {safe_name(entry['name'])}"
            zf.write(Path(files_dir) / stored, arc)
            entry["path"] = arc
            if progress is not None:
                progress(i, len(entries))
        manifest_bytes = json.dumps(
            manifest, ensure_ascii=False, indent=2).encode("utf-8")
        zf.writestr("manifest.json", manifest_bytes)
        zf.writestr("index.html", make_index_html(manifest).encode("utf-8"))
    return {
        "path": str(out_path),
        "count": len(entries),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
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
    if manifest.get("format") != FORMAT:
        raise KeyError("not a darspack package manifest")
    return list(manifest.get("files", []))


@dataclass
class VerifyReport:
    ok: bool
    problems: list = field(default_factory=list)   # Persian messages


def verify_package(zip_path, progress=None) -> VerifyReport:
    """Check a package against its manifest: missing / size / SHA-256."""
    problems: list[str] = []
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        try:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        except KeyError:
            return VerifyReport(False, ["manifest.json در بسته نیست — بسته معتبر نیست"])
        except (json.JSONDecodeError, UnicodeDecodeError):
            return VerifyReport(False, ["manifest.json مخدوش است — بسته معتبر نیست"])

        listed = set()
        for entry in manifest.get("files", []):
            arc = entry.get("path")
            if progress is not None:
                progress(entry.get("name", ""), arc or "")
            if not arc or arc not in names:
                problems.append(f"گم‌شده: {entry.get('name')} ({arc})")
                continue
            listed.add(arc)
            if zf.getinfo(arc).file_size != entry.get("size"):
                problems.append(f"اندازه‌ی فایل متفاوت است: {entry['name']}")
                continue
            digest = hashlib.sha256()
            with zf.open(arc) as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    digest.update(chunk)
            if digest.hexdigest() != entry.get("sha256"):
                problems.append(f"خراب یا تغییرکرده: {entry['name']}")

        for extra in sorted(names - listed - {"manifest.json", "index.html"}
                            - KNOWN_EXTRA_MEMBERS):
            problems.append(f"فایل اضافه در بسته: {extra}")
    return VerifyReport(ok=not problems, problems=problems)
