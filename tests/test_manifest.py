"""Tests for درس‌پک packages: export → verify round-trip, tamper detection."""
import json
import zipfile

import pytest

from darspack.core.importer import import_file
from darspack.core.library import Library
from darspack.core.manifest import export_package, verify_package


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
