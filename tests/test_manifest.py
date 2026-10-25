"""Tests for درس‌پک packages: export → verify round-trip, tamper detection."""
import json
import zipfile

import pytest

from darspack.core import db
from darspack.core.importer import import_file
from darspack.core.library import Library
from darspack.core.manifest import (
    export_package, make_index_html, safe_name, verify_package,
)


@pytest.fixture()
def package(tmp_path):
    with Library(tmp_path / "lib") as lib:
        for name in ("نمونه سوال ریاضی فصل 3.pdf", "جزوه علوم.pdf"):
            p = tmp_path / name
            p.write_bytes(f"content of {name}".encode("utf-8"))
            import_file(lib, p)
        ids = [r["id"] for r in lib.conn.execute("SELECT id FROM files")]
        out = tmp_path / "ch3.darspack.zip"
        info = export_package(lib.conn, lib.files_dir, ids, out)
        yield out, info, lib


def test_export_shape_and_index(package):
    out, info, _ = package
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        assert "manifest.json" in names and "index.html" in names
        assert sum(n.startswith("files/") for n in names) == 2
        assert 'dir="rtl"' in zf.read("index.html").decode("utf-8")
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert manifest["format"] == "darspack-package"
        assert {e["name"] for e in manifest["files"]} == {
            "نمونه سوال ریاضی فصل 3.pdf", "جزوه علوم.pdf"}
        assert all(e.get("path") and e.get("sha256") for e in manifest["files"])
    assert info["count"] == 2 and len(info["manifest_sha256"]) == 64


def test_verify_ok_on_intact_copy(package, tmp_path):
    out, _, _ = package
    copy = tmp_path / "copied-to-usb.darspack.zip"
    copy.write_bytes(out.read_bytes())        # like copying to a USB stick
    report = verify_package(copy)
    assert report.ok and report.problems == []


def _rewrite(zip_path, mutate):
    """Copy a ZIP, letting `mutate(member_name, data)` change members."""
    out = zip_path.with_suffix(".tampered.zip")
    with zipfile.ZipFile(zip_path) as zin, \
            zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            data = mutate(info.filename, data)
            if data is None:                  # member removed
                continue
            zout.writestr(info.filename, data)
    return out


def test_verify_detects_corrupted_byte(package):
    out, _, _ = package
    victim = next(n for n in zipfile.ZipFile(out).namelist()
                  if n.startswith("files/"))
    def mutate(name, data):
        if name == victim:
            b = bytearray(data)
            b[0] ^= 0xFF                      # flip one byte
            return bytes(b)
        return data
    report = verify_package(_rewrite(out, mutate))
    assert not report.ok
    assert len(report.problems) == 1
    assert "خراب یا تغییرکرده" in report.problems[0]


def test_verify_detects_missing_member(package):
    out, _, _ = package
    victim = next(n for n in zipfile.ZipFile(out).namelist()
                  if n.startswith("files/"))
    report = verify_package(_rewrite(out, lambda n, d: None if n == victim else d))
    assert not report.ok
    assert any("گم‌شده" in p for p in report.problems)


def test_verify_flags_extra_files(package):
    out, _, _ = package
    def mutate(name, data):
        return data
    extra = out.with_suffix(".extra.zip")
    with zipfile.ZipFile(out) as zin, \
            zipfile.ZipFile(extra, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            zout.writestr(info.filename, zin.read(info.filename))
        zout.writestr("files/999 - extra.pdf", b"sneaked in")
    report = verify_package(extra)
    assert not report.ok
    assert any("فایل اضافه" in p for p in report.problems)


# --- safe_name, more verify branches, and the manifest format contract ---

def test_safe_name_replaces_every_unsafe_character():
    for bad in ("\\", "/", ":", "*", "?", '"', "<", ">", "|", "\n"):
        assert safe_name(f"a{bad}b") == "a_b", f"safe_name with {bad!r}"
    assert safe_name("نمونه سوال.pdf") == "نمونه سوال.pdf"   # Persian kept


def test_safe_name_blank_becomes_file():
    # a name with nothing left after replacing/stripping still needs a
    # ZIP member name — the fallback is literally "file"
    assert safe_name("") == "file"
    assert safe_name("   ") == "file"


def test_verify_detects_truncated_member(package):
    # a half-copied file (interrupted USB copy) has the right hash table
    # entry but the wrong size — the size check must catch it
    out, _, _ = package
    victim = next(n for n in zipfile.ZipFile(out).namelist()
                  if n.startswith("files/"))
    report = verify_package(_rewrite(out, lambda n, d: d[:-5] if n == victim else d))
    assert not report.ok
    assert any("اندازه‌ی فایل متفاوت است" in p for p in report.problems)


def test_verify_rejects_zip_without_manifest(tmp_path):
    # files but no manifest: the package explains nothing — invalid
    bare = tmp_path / "bare.zip"
    with zipfile.ZipFile(bare, "w") as zf:
        zf.writestr("files/001 - x.pdf", b"data")
    report = verify_package(bare)
    assert report.ok is False
    assert report.problems == ["manifest.json در بسته نیست — بسته معتبر نیست"]


def test_verify_raises_on_non_zip_input(tmp_path):
    # known quirk (⚖️): a non-zip file raises BadZipFile instead of coming
    # back as a Persian report — the desktop verify dialog calls this
    # straight from a file picker, so a corrupt zip currently shows the
    # crash dialog. Pinned as current behavior; the maintainer decides in the
    # later review whether verify_package should catch it instead.
    not_a_zip = tmp_path / "not-a-zip.zip"
    not_a_zip.write_bytes(b"just some bytes")
    with pytest.raises(zipfile.BadZipFile):
        verify_package(not_a_zip)


def test_manifest_entry_carries_classification(tmp_path):
    # the package must carry the whole catalog row — not just name/sha —
    # so the recipient's library keeps subject/chapter/kind/tags
    with Library(tmp_path / "lib") as lib:
        src = tmp_path / "نمونه سوال ریاضی فصل 3.pdf"
        src.write_bytes(b"classified content")
        import_file(lib, src)
        fid = lib.conn.execute("SELECT id FROM files").fetchone()["id"]
        sid = db.get_or_create(lib.conn, "subjects", "ریاضی")
        tid = db.get_or_create(lib.conn, "tags", "امتحان")
        lib.conn.execute(
            "UPDATE files SET subject_id=?, chapter=3, kind='نمونه‌سوال' WHERE id=?",
            (sid, fid))
        lib.conn.execute(
            "INSERT INTO file_tags(file_id, tag_id) VALUES (?,?)", (fid, tid))
        lib.conn.commit()

        out = tmp_path / "ch3.darspack.zip"
        export_package(lib.conn, lib.files_dir, [fid], out)

    manifest = json.loads(
        zipfile.ZipFile(out).read("manifest.json").decode("utf-8"))
    assert manifest["format"] == "darspack-package"
    assert manifest["version"] == 1
    entry, = manifest["files"]
    assert entry["subject"] == "ریاضی"
    assert entry["chapter"] == 3
    assert entry["kind"] == "نمونه‌سوال"
    assert entry["tags"] == ["امتحان"]


def test_export_of_empty_selection_makes_valid_package(tmp_path):
    with Library(tmp_path / "lib") as lib:
        out = tmp_path / "empty.darspack.zip"
        info = export_package(lib.conn, lib.files_dir, [], out)
    assert info["count"] == 0
    report = verify_package(out)
    assert report.ok and report.problems == []


def test_export_unknown_id_raises(tmp_path):
    # callers must filter ids first (the UI passes selection ids only) —
    # a bad id is a programming error, not a reportable package problem
    with Library(tmp_path / "lib") as lib:
        with pytest.raises(KeyError):
            export_package(lib.conn, lib.files_dir, [424242],
                           tmp_path / "x.zip")


def test_index_html_escapes_file_names():
    # the index opens in any browser; a file named like HTML must render
    # as text, never as markup
    manifest = {"created": "2026-10-24T10:00:00",
                "files": [{"name": "<b>x</b>", "subject": None,
                           "chapter": None, "kind": None}]}
    page = make_index_html(manifest)
    assert "&lt;b&gt;x&lt;/b&gt;" in page
    assert "<b>x</b>" not in page
