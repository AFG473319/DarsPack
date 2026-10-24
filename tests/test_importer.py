"""Tests for the import pipeline (وارد کردن): dedup-at-import and crash safety."""
import pytest

from darspack.core.importer import import_file, import_paths
from darspack.core.library import Library


@pytest.fixture()
def lib(tmp_path):
    with Library(tmp_path / "lib") as library:
        yield library


@pytest.fixture()
def sample(tmp_path):
    def make(name: str, data: bytes = b"lesson-content") -> object:
        p = tmp_path / name
        p.write_bytes(data)
        return p
    return make


def test_import_creates_row_and_file(lib, sample):
    r = import_file(lib, sample("نمونه سوال ریاضی فصل 3.pdf"))
    assert r.status == "imported" and r.file_id == 1
    row = lib.conn.execute("SELECT * FROM files WHERE id=1").fetchone()
    assert row["original_name"] == "نمونه سوال ریاضی فصل 3.pdf"
    assert row["stored_name"] == "000001.pdf"
    assert (lib.files_dir / "000001.pdf").exists()
    assert row["kind"] == "نمونه‌سوال"          # suggestion applied
    assert row["chapter"] == 3


def test_identical_file_is_reported_as_duplicate(lib, sample):
    first = import_file(lib, sample("a.pdf"))
    again = import_file(lib, sample("b.pdf", data=b"lesson-content"))
    assert again.status == "duplicate"
    assert again.existing_id == first.file_id
    count = lib.conn.execute("SELECT COUNT(*) c FROM files").fetchone()["c"]
    assert count == 1                            # nothing re-stored


def test_keep_duplicate_overrides(lib, sample):
    import_file(lib, sample("a.pdf"))
    kept = import_file(lib, sample("b.pdf", data=b"lesson-content"),
                       keep_duplicate=True)
    assert kept.status == "imported"
    count = lib.conn.execute("SELECT COUNT(*) c FROM files").fetchone()["c"]
    assert count == 2


def test_crash_mid_import_rolls_back(tmp_path, sample, monkeypatch):
    src = sample("crash.pdf")
    with Library(tmp_path / "lib") as lib:
        import darspack.core.importer as importer
        def boom(*args, **kwargs):
            raise OSError("simulated crash during rename")
        monkeypatch.setattr(importer.os, "replace", boom)
        with pytest.raises(OSError):
            import_file(lib, src)
        count = lib.conn.execute("SELECT COUNT(*) c FROM files").fetchone()["c"]
        assert count == 0                        # row rolled back
        monkeypatch.undo()

    # reopening sweeps the leftover tmp file, and the import now succeeds
    with Library(tmp_path / "lib") as lib:
        leftovers = list(lib.files_dir.glob("tmp_*"))
        assert leftovers == []
        assert import_file(lib, src).status == "imported"


def test_import_folder_recursively(lib, tmp_path):
    folder = tmp_path / "from-telegram"
    (folder / "sub").mkdir(parents=True)
    (folder / "1.pdf").write_bytes(b"one")
    (folder / "sub" / "2.pdf").write_bytes(b"two")
    results = import_paths(lib, [folder])
    assert [r.status for r in results] == ["imported", "imported"]
    assert {r.path.name for r in results} == {"1.pdf", "2.pdf"}
