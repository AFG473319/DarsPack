"""Tests for the import pipeline (وارد کردن): dedup-at-import and crash safety."""
import pytest

from darspack.core.importer import import_file, import_paths
from darspack.core.library import Library
from darspack.core.normalize import match_key
from darspack.core.schoolyear import current_school_year


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


def test_duplicate_skip_is_recorded_for_saved_space(lib, sample):
    """E5: a skipped duplicate records the bytes the library never copied;
    a duplicate the user explicitly chose to keep records nothing."""
    import_file(lib, sample("a.pdf"))
    import_file(lib, sample("b.pdf"))                          # skipped
    import_file(lib, sample("c.pdf"), keep_duplicate=True)     # kept on purpose
    skips = lib.conn.execute(
        "SELECT size_bytes, original_name FROM import_skips").fetchall()
    assert len(skips) == 1
    assert skips[0]["size_bytes"] == len(b"lesson-content")
    assert skips[0]["original_name"] == "b.pdf"


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


# --- the flag-only contract, catalog stamping, and dormant parameters ----

def test_original_file_is_never_touched(lib, sample):
    # the flagship rule: files are COPIED into the library — the source
    # keeps its exact bytes and modification time afterwards
    src = sample("قیمت‌مند.pdf", b"precious bytes")
    before = (src.stat().st_mtime_ns, src.read_bytes())
    import_file(lib, src)
    assert src.exists()
    assert (src.stat().st_mtime_ns, src.read_bytes()) == before


def test_missing_file_is_an_error_result(lib, tmp_path):
    r = import_file(lib, tmp_path / "نیست.pdf")
    assert r.status == "error"
    assert r.message_fa.startswith("فایل پیدا نشد")


def test_same_batch_duplicate_is_detected(lib, tmp_path):
    # dedup works WITHIN one batch too, not only against the old catalog
    a = tmp_path / "a.pdf"
    a.write_bytes(b"same-bytes")
    b = tmp_path / "b.pdf"
    b.write_bytes(b"same-bytes")
    results = import_paths(lib, [a, b])
    assert [r.status for r in results] == ["imported", "duplicate"]


def test_batch_survives_a_missing_file(lib, tmp_path):
    a = tmp_path / "ok.pdf"
    a.write_bytes(b"data")
    results = import_paths(lib, [a, tmp_path / "gone.pdf"])
    assert [r.status for r in results] == ["imported", "error"]


def test_empty_file_imports(lib, sample):
    r = import_file(lib, sample("خالی.pdf", b""))
    assert r.status == "imported"
    row = lib.conn.execute("SELECT size_bytes FROM files WHERE id=?",
                           (r.file_id,)).fetchone()
    assert row["size_bytes"] == 0


def test_catalog_stamps_match_key_and_school_year(lib, sample):
    # search and dedup silently depend on both stamps being written at
    # import time — this file name is typed with Arabic ك and ي on purpose
    name = "كاربرگ فيزيك.pdf"
    import_file(lib, sample(name))
    row = lib.conn.execute("SELECT name_norm, school_year FROM files").fetchone()
    assert row["name_norm"] == match_key(name)
    assert row["school_year"] == current_school_year()


def test_file_without_extension_stored_without_dot(lib, sample):
    # the flat-storage convention: stored_name is just the zero-padded id
    # plus the source suffix — no suffix means NO dot
    import_file(lib, sample("بدون-پسوند"))
    row = lib.conn.execute("SELECT stored_name FROM files").fetchone()
    assert row["stored_name"] == "000001"


def test_display_name_drives_catalog_and_suggestion(lib, tmp_path):
    # web uploads arrive as random-named temp files; the catalog name and
    # the suggestion must come from the display name, not the temp name
    tmp = tmp_path / "upload-a1b2c3"
    tmp.write_bytes(b"phone upload")
    r = import_file(lib, tmp, display_name="کاربرگ فیزیک فصل 2.pdf")
    assert r.status == "imported"
    row = lib.conn.execute(
        "SELECT original_name, name_norm, kind, chapter FROM files").fetchone()
    assert row["original_name"] == "کاربرگ فیزیک فصل 2.pdf"
    assert row["name_norm"] == match_key("کاربرگ فیزیک فصل 2.pdf")
    assert row["kind"] == "کاربرگ" and row["chapter"] == 2


def test_meta_overrides_suggestions(lib, sample):
    # known quirk (⚖️): the `meta` parameter is a tested-but-dormant API —
    # no caller passes it today. Kept and pinned here so a decision to
    # remove it (simpler surface to defend) is made on purpose.
    import_file(lib, sample("ناشناخته.pdf"),
                meta={"chapter": 9, "kind": "جزوه",
                      "school_year": "1400-1401"})
    row = lib.conn.execute(
        "SELECT chapter, kind, school_year FROM files").fetchone()
    assert row["chapter"] == 9 and row["kind"] == "جزوه"
    assert row["school_year"] == "1400-1401"


def test_reopen_sweeps_orphans_but_keeps_real_files(tmp_path, sample):
    # sweep_orphans reconciles files/ with the catalog after a crash: a
    # tmp_* leftover AND a numbered file whose row rolled back are both
    # deleted on purpose — the catalog is the source of truth
    src = sample("سالم.pdf")
    with Library(tmp_path / "lib") as lib:
        import_file(lib, src)
        real = lib.files_dir / "000001.pdf"
        assert real.exists()
        (lib.files_dir / "tmp_7.pdf").write_bytes(b"tmp leftover")
        (lib.files_dir / "999999.pdf").write_bytes(b"orphan of a rolled-back row")

    with Library(tmp_path / "lib") as lib:
        assert not (lib.files_dir / "tmp_7.pdf").exists()
        assert not (lib.files_dir / "999999.pdf").exists()
        assert real.exists() and real.read_bytes() == b"lesson-content"


# --- C4: the duplicate message names the twin ------------------------------

def test_duplicate_message_names_the_existing_file(lib, sample):
    first = import_file(lib, sample("جزوه ریاضی فصل 3.pdf"))
    again = import_file(lib, sample("دانلود (1).pdf", data=b"lesson-content"))
    assert again.status == "duplicate"
    assert first.file_id == 1
    assert "جزوه ریاضی فصل 3.pdf" in again.message_fa
    assert "تکرار" in again.message_fa


# --- lesson storage + the A5 prefill contract ------------------------------

def test_lesson_suggestion_is_stored(lib, sample):
    # «درس» is parsed like «فصل» but lands in its OWN column (design
    # decision 2026-10-24: a file may have درس, فصل, both, or neither)
    import_file(lib, sample("فارسی درس 3.pdf"))
    row = lib.conn.execute("SELECT chapter, lesson FROM files").fetchone()
    assert row["lesson"] == 3 and row["chapter"] is None


def test_meta_lesson_override(lib, sample):
    import_file(lib, sample("ناشناخته.pdf"), meta={"lesson": 7})
    row = lib.conn.execute("SELECT lesson FROM files").fetchone()
    assert row["lesson"] == 7


def test_manifest_subject_tags_are_prefill_only(lib, sample):
    # A5 contract: subject/tags from a درس‌پک manifest must NEVER be
    # stored — they ride back on the result for the classify dialog
    r = import_file(lib, sample("جزوه فیزیک.pdf"),
                    meta={"kind": "جزوه", "chapter": 2, "lesson": 1,
                          "school_year": "1404-1405",
                          "subject": "فیزیک", "tags": ["امتحانی"]})
    assert r.status == "imported"
    row = lib.conn.execute(
        "SELECT subject_id, kind, chapter, lesson, school_year FROM files"
    ).fetchone()
    assert row["subject_id"] is None            # never auto-applied
    assert row["kind"] == "جزوه" and row["chapter"] == 2 and row["lesson"] == 1
    assert row["school_year"] == "1404-1405"
    assert r.prefill == {"subject": "فیزیک", "tags": ["امتحانی"]}


def test_prefill_is_none_for_ordinary_imports(lib, sample):
    r = import_file(lib, sample("فقط-نام.pdf"))
    assert r.prefill is None


def test_duplicate_of_package_file_still_carries_prefill(lib, sample):
    import_file(lib, sample("اول.pdf"),
                meta={"subject": "فیزیک", "tags": ["امتحانی"]})
    again = import_file(lib, sample("دوم.pdf", data=b"lesson-content"),
                        meta={"subject": "فیزیک", "tags": ["امتحانی"]})
    assert again.status == "duplicate"
    assert again.prefill == {"subject": "فیزیک", "tags": ["امتحانی"]}


def test_import_zero_byte_file(lib, sample):
    r = import_file(lib, sample("خالی.pdf", data=b""))
    assert r.status == "imported"
    row = lib.conn.execute("SELECT size_bytes, sha256 FROM files WHERE id=?", (r.file_id,)).fetchone()
    assert row["size_bytes"] == 0
    assert row["sha256"] == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_import_file_without_extension(lib, sample):
    r = import_file(lib, sample("جزوه_بدون_پسوند", data=b"content"))
    assert r.status == "imported"
    row = lib.conn.execute("SELECT stored_name, original_name FROM files WHERE id=?", (r.file_id,)).fetchone()
    assert row["original_name"] == "جزوه_بدون_پسوند"
    assert row["stored_name"] == f"{r.file_id:06d}"
    assert (lib.files_dir / row["stored_name"]).exists()


def test_import_nonexistent_file_returns_error_result(lib, tmp_path):
    r = import_file(lib, tmp_path / "nonexistent.pdf")
    assert r.status == "error"
    assert "پیدا نشد" in r.message_fa


def test_import_paths_empty(lib, tmp_path):
    empty_dir = tmp_path / "empty_folder"
    empty_dir.mkdir()
    assert import_paths(lib, []) == []
    assert import_paths(lib, [empty_dir]) == []

# --- H1: the copy must not hold the write lock ---------------------------

def test_copy_does_not_hold_the_write_lock(lib, sample, monkeypatch):
    """H1: while the file copy runs, another connection can still write —
    this is the phone-upload case: a second writer used to fail with
    'database is locked' because the copy ran inside the transaction.
    The copy is faked slow (1 s); the probe connection only waits 0.5 s,
    so it only succeeds if no lock is held during the copy."""
    import sqlite3
    import time
    import darspack.core.importer as importer
    src = sample("slow.pdf", b"y" * 4096)
    real_copy2 = importer.shutil.copy2
    wrote = []

    def slow_copy(s, d, *a, **k):
        time.sleep(1.0)  # a big file's copy takes real time
        other = sqlite3.connect(str(lib.db_path), timeout=0.5)
        try:
            other.execute(
                "INSERT INTO activity_log(ts, action, detail)"
                " VALUES ('t', 'probe', 'x')")
            other.commit()
            wrote.append(True)
        finally:
            other.close()
        return real_copy2(s, d, *a, **k)

    monkeypatch.setattr(importer.shutil, "copy2", slow_copy)
    r = import_file(lib, src)
    assert r.status == "imported"
    assert wrote == [True]


def test_concurrent_same_content_imports_yield_one_row(tmp_path, monkeypatch):
    """M2: two imports of the same content at the same moment must not
    create two rows — one wins, the other reports duplicate. The copy
    is faked slow so both threads are inside the import at once."""
    import threading
    import time
    import darspack.core.importer as importer
    root = tmp_path / "lib"
    a = tmp_path / "a.pdf"
    a.write_bytes(b"same-content")
    b = tmp_path / "b.pdf"
    b.write_bytes(b"same-content")
    lib_a = Library(root).open()
    lib_b = Library(root).open()
    real_copy2 = importer.shutil.copy2

    def slow_copy(s, d, *a, **k):
        time.sleep(0.05)  # widen the race: both threads copy at once
        return real_copy2(s, d, *a, **k)

    monkeypatch.setattr(importer.shutil, "copy2", slow_copy)
    barrier = threading.Barrier(2)
    results, errors = [], []

    def worker(lib, src):
        try:
            barrier.wait(timeout=10)
            results.append(import_file(lib, src))
        except Exception as exc:  # noqa: BLE001 — collected, asserted below
            errors.append(exc)

    t1 = threading.Thread(target=worker, args=(lib_a, a))
    t2 = threading.Thread(target=worker, args=(lib_b, b))
    try:
        t1.start()
        t2.start()
        t1.join(timeout=15)
        t2.join(timeout=15)
        assert not t1.is_alive() and not t2.is_alive()
    finally:
        lib_a.close()
        lib_b.close()
    assert errors == []
    assert sorted(r.status for r in results) == ["duplicate", "imported"]
    with Library(root) as lib:
        count = lib.conn.execute("SELECT COUNT(*) c FROM files").fetchone()["c"]
    assert count == 1
