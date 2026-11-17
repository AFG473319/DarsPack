"""Tests for درس‌پک packages: export → verify round-trip, tamper detection."""
import json
import zipfile
from pathlib import Path

import pytest

from darspack.core import db
from darspack.core.importer import import_file
from darspack.core.library import Library
from darspack.core.manifest import (
    export_package, make_index_html, read_manifest, safe_name, verify_package,
)


@pytest.fixture(scope="module")
def package(tmp_path_factory):
    root = tmp_path_factory.mktemp("manifest-pkg")
    with Library(root / "lib") as lib:
        for name in ("نمونه سوال ریاضی فصل 3.pdf", "جزوه علوم.pdf"):
            p = root / name
            p.write_bytes(f"content of {name}".encode("utf-8"))
            import_file(lib, p)
        ids = [r["id"] for r in lib.conn.execute("SELECT id FROM files")]
        out = root / "ch3.darspack.zip"
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


# --- A5: package import round-trips the manifest metadata -------------------

def test_export_manifest_carries_school_year_and_lesson(tmp_path):
    with Library(tmp_path / "lib") as lib:
        src = tmp_path / "فارسی درس 3.pdf"
        src.write_bytes(b"lesson content")
        import_file(lib, src, meta={"school_year": "1404-1405"})
        fid = lib.conn.execute("SELECT id FROM files").fetchone()["id"]
        out = tmp_path / "pk.zip"
        export_package(lib.conn, lib.files_dir, [fid], out)
    entries = read_manifest(out)
    assert entries[0]["lesson"] == 3 and entries[0]["chapter"] is None
    assert entries[0]["school_year"] == "1404-1405"


def test_package_import_round_trips_metadata(tmp_path):
    # the A5 story: a classmate imports an organized package and the
    # sender's chapter/lesson/kind/school_year survive — while subject/
    # tags come back as PRE-FILL, never stored
    with Library(tmp_path / "sender") as sender:
        src = tmp_path / "جزوه ریاضی درس 2.pdf"
        src.write_bytes(b"first")
        r = import_file(sender, src,
                        meta={"kind": "جزوه", "chapter": 4, "lesson": 2,
                              "school_year": "1404-1405"})
        sid = db.get_or_create(sender.conn, "subjects", "ریاضی")
        sender.conn.execute(
            "UPDATE files SET subject_id=? WHERE id=?", (sid, r.file_id))
        tid = db.get_or_create(sender.conn, "tags", "امتحانی")
        sender.conn.execute(
            "INSERT INTO file_tags(file_id, tag_id) VALUES (?,?)",
            (r.file_id, tid))
        sender.conn.commit()
        ids = [row["id"] for row in sender.conn.execute("SELECT id FROM files")]
        out = tmp_path / "pack.zip"
        export_package(sender.conn, sender.files_dir, ids, out)

    metas = {e["path"]: e for e in read_manifest(out)}

    # the receiver extracts files/ to a temp dir and imports with metas —
    # exactly what the package-import dialog will do
    with Library(tmp_path / "receiver") as receiver:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            with zipfile.ZipFile(out) as zf:
                zf.extractall(td)
            for entry in metas.values():
                extracted = Path(td) / entry["path"]
                res = import_file(
                    receiver, extracted,
                    meta={"kind": entry.get("kind"),
                          "chapter": entry.get("chapter"),
                          "lesson": entry.get("lesson"),
                          "school_year": entry.get("school_year"),
                          "subject": entry.get("subject"),
                          "tags": entry.get("tags")},
                    display_name=entry["name"])
                assert res.status == "imported"
                assert res.prefill == {"subject": "ریاضی",
                                       "tags": ["امتحانی"]}
        row = receiver.conn.execute(
            "SELECT kind, chapter, lesson, school_year, subject_id"
            " FROM files").fetchone()
        assert row["kind"] == "جزوه" and row["chapter"] == 4
        assert row["lesson"] == 2 and row["school_year"] == "1404-1405"
        assert row["subject_id"] is None          # pre-fill only, stored never


def test_duplicate_display_names_disambiguated_by_arc_key(tmp_path):
    # two DIFFERENT files both named «test.pdf»: the metas map is keyed
    # by the arc path (001 - test.pdf / 002 - test.pdf), never the name
    with Library(tmp_path / "sender") as sender:
        for i, data in enumerate((b"one", b"two")):
            src = tmp_path / f"src{i}.pdf"
            src.write_bytes(data)
            import_file(sender, src, display_name="test.pdf",
                        meta={"chapter": i + 1})
        ids = [row["id"] for row in sender.conn.execute("SELECT id FROM files")]
        out = tmp_path / "pack.zip"
        export_package(sender.conn, sender.files_dir, ids, out)

    entries = read_manifest(out)
    assert len(entries) == 2
    assert {e["path"] for e in entries} == {e["path"] for e in entries}
    assert len({e["path"] for e in entries}) == 2          # unique arc keys
    assert {e["chapter"] for e in entries} == {1, 2}       # each keeps its own


def test_read_manifest_rejects_non_darspack_manifest(tmp_path):
    z = tmp_path / "fake.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"format": "other"}))
    with pytest.raises(KeyError):
        read_manifest(z)


def test_verify_detects_corrupted_manifest_json(tmp_path):
    # A damaged or truncated manifest.json must not crash verify_package
    bad_zip = tmp_path / "corrupt_manifest.zip"
    with zipfile.ZipFile(bad_zip, "w") as zf:
        zf.writestr("manifest.json", "{not-valid-json")
    report = verify_package(bad_zip)
    assert not report.ok
    assert any("مخدوش است" in p for p in report.problems)


def test_safe_name_path_traversal():
    assert safe_name("../../secret/file.pdf") == ".._.._secret_file.pdf"
    assert safe_name("..\\..\\secret\\file.pdf") == ".._.._secret_file.pdf"
    assert safe_name("   //::*   ") == "_"
