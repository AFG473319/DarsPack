"""Tests for the main window's pure helper functions.

jalali_date guards the «تاریخ ورود» column: imported_at is stored as a
GREGORIAN isoformat string, so the helper must parse with the stdlib and
convert to Jalali — parsing with jdatetime directly used to pass the
Gregorian digits through unchanged (۲۰۲۶/۱۰/۲۴ dressed up as a Jalali
date). These cases pin the correct conversion, the Nowruz year boundary
and the never-crash fallback. No Qt objects needed — but importing the
module pulls in PySide6, so conftest's offscreen env applies.
"""
from darspack.ui.main_window import human_size, jalali_date


def test_jalali_date_converts_gregorian_import_dates():
    assert jalali_date("2026-10-24T13:05:00") == "1405/08/02"


def test_jalali_date_nowruz_year_boundary():
    # 21 March 2027 is 1 Farvardin 1406 — the school-year turn of the year
    assert jalali_date("2027-03-21T00:00:00") == "1406/01/01"


def test_jalali_date_bad_input_passes_through():
    # never crash the catalog table: garbage comes back as-is
    assert jalali_date("garbage") == "garbage"


def test_human_size_table():
    # the sizes column: bytes stay integers, bigger units get one decimal
    assert human_size(0) == "0 B"
    assert human_size(1023) == "1023 B"
    assert human_size(1024) == "1.0 KB"
    assert human_size(1536) == "1.5 KB"
    assert human_size(5 * 1024 ** 3) == "5.0 GB"


# --- MainWindow-level behavior (offscreen) ---------------------------------

import pytest

import darspack.ui.main_window as mw_module
from darspack.core.importer import import_file
from darspack.core.library import Library


@pytest.fixture()
def window(tmp_path, qapp):
    """One MainWindow over a throwaway library, closed afterwards."""
    win = mw_module.MainWindow(tmp_path / "lib",
                               {"language": "fa", "font_size": 10,
                                "library": str(tmp_path / "lib")},
                               tmp_path / "settings.json")
    yield win
    win.lib.close()


def test_fast_typing_triggers_exactly_one_refresh(window, monkeypatch):
    """C3: the debounced search box — three keystrokes in a row must run
    the catalog query once, after the 200 ms countdown settles."""
    from PySide6.QtTest import QTest

    calls = []
    real_search = mw_module.catalog_search

    def counting_search(*args, **kwargs):
        calls.append(1)
        return real_search(*args, **kwargs)
    monkeypatch.setattr(mw_module, "catalog_search", counting_search)

    calls.clear()
    window.search_box.setText("ریاضی")
    window.search_box.setText("ریاضی فصل")
    window.search_box.setText("ریاضی فصل ۳")
    assert calls == []                    # countdown still running
    QTest.qWait(350)
    assert len(calls) == 1                # one refresh for the whole burst


def test_filter_changes_stay_immediate(window, monkeypatch):
    """C3 scoping: only the search box is debounced — the kind filter
    refreshes the table the moment it changes."""
    calls = []
    real_search = mw_module.catalog_search

    def counting_search(*args, **kwargs):
        calls.append(1)
        return real_search(*args, **kwargs)
    monkeypatch.setattr(mw_module, "catalog_search", counting_search)

    calls.clear()
    window.kind_combo.setCurrentIndex(1)   # first real kind («جزوه»)
    assert len(calls) == 1                 # immediate, no timer wait


def test_display_strs_cache_hits_on_second_refresh(window):
    """F2.4: the Jalali/size strings are cached per file id — importing one
    file and refreshing twice formats the date/size only once."""
    src = window.lib.root.parent / "نمونه سوال ریاضی فصل 3.pdf"
    src.write_bytes(b"demo")
    import_file(window.lib, src)

    window.refresh()
    first = window._display_strs.copy()
    window.refresh()
    assert window._display_strs == first   # same dict entries, no re-format
    assert len(first) == 1                 # one cached id


def test_empty_library_shows_start_hint(window):
    """E2: a fresh library greets with the «start with import» sentence."""
    window.refresh()
    assert not window.empty_label.isHidden()
    assert window.empty_label.text() == "هنوز فایلی نیست — با «وارد کردن…» شروع کنید"


def test_search_no_result_shows_digit_hint(window):
    """E2: an empty search result gets the Persian/Latin digits hint."""
    src = window.lib.root.parent / "نمونه سوال ریاضی فصل 3.pdf"
    src.write_bytes(b"demo")
    import_file(window.lib, src)
    window.refresh()
    assert window.empty_label.isHidden()          # rows exist

    window.search_box.setText("چیزی-که-نیست")     # debounced — fire it
    window.refresh()
    assert not window.empty_label.isHidden()
    assert "اعداد فارسی" in window.empty_label.text()


def test_school_year_filter_isolates_years(tmp_path, qapp):
    """A3: the year filter combo shows only one school year's files, and
    the «سال» column carries each file's year."""
    from darspack.core.normalize import persian_digits

    with Library(tmp_path / "lib") as lib:
        for name, year in (("جزوه ریاضی فصل 1.pdf", "1404-1405"),
                           ("جزوه ریاضی فصل 2.pdf", "1405-1406"),
                           ("جزوه ریاضی فصل 3.pdf", "1405-1406")):
            src = tmp_path / name
            src.write_bytes(f"content {name}".encode("utf-8"))
            import_file(lib, src, meta={"school_year": year})
        win = mw_module.MainWindow(lib.root,
                                   {"language": "fa", "font_size": 10,
                                    "library": str(lib.root)},
                                   tmp_path / "settings.json")
        try:
            idx = win.year_combo.findData("1404-1405")
            assert idx > 0                       # listed after «همه‌ی سال‌ها»
            win.year_combo.setCurrentIndex(idx)  # fires refresh itself
            assert [r["original_name"] for r in win.last_rows] == \
                ["جزوه ریاضی فصل 1.pdf"]

            win.year_combo.setCurrentIndex(win.year_combo.findData("1405-1406"))
            assert len(win.last_rows) == 2

            win.year_combo.setCurrentIndex(0)    # «همه‌ی سال‌ها»
            assert len(win.last_rows) == 3
            # «سال» column (index 6) shows the Persian-digit year label
            shown = win.table.item(0, 6).text()
            assert shown == persian_digits("1404-1405") or \
                shown == persian_digits("1405-1406")
        finally:
            win.lib.close()


# --- E3: confirmed manual delete (design-approved 2026-10-24) -------------

from PySide6.QtWidgets import QMessageBox


def test_delete_moves_file_to_trash_and_removes_row(tmp_path, qapp, monkeypatch):
    """E3: the confirmed delete MOVES the stored file to files/.trash
    (never unlinked), deletes the row + its tag links, and logs the
    action. Re-importing the same content works afterwards."""
    with Library(tmp_path / "lib") as lib:
        src = tmp_path / "جزوه اشتباهی.pdf"
        src.write_bytes(b"wrong file")
        import_file(lib, src)
        fid = lib.conn.execute("SELECT id FROM files").fetchone()["id"]
        with lib.conn:      # explicit commit — an open transaction would
            #                # block the window's connection (WAL writer)
            lib.conn.execute(
                "INSERT INTO file_tags(file_id, tag_id) VALUES (?, ?)",
                (fid, lib.conn.execute(
                    "INSERT INTO tags(name, normalized) VALUES ('x', 'x')")
                 .lastrowid))

        win = mw_module.MainWindow(lib.root,
                                   {"language": "fa", "font_size": 10,
                                    "library": str(lib.root)},
                                   tmp_path / "settings.json")
        try:
            monkeypatch.setattr(
                QMessageBox, "question",
                staticmethod(lambda *a, **k: QMessageBox.Yes))
            win.delete_file(fid)

            assert lib.conn.execute(
                "SELECT COUNT(*) c FROM files").fetchone()["c"] == 0
            assert lib.conn.execute(
                "SELECT COUNT(*) c FROM file_tags").fetchone()["c"] == 0
            trash = lib.files_dir / ".trash"
            trashed = list(trash.iterdir())
            assert len(trashed) == 1          # the file MOVED, not erased
            assert trashed[0].read_bytes() == b"wrong file"
            action = lib.conn.execute(
                "SELECT action, detail FROM activity_log ORDER BY id DESC LIMIT 1"
            ).fetchone()
            assert action["action"] == "delete"
            assert "جزوه اشتباهی" in action["detail"]

            # re-importing the same content works — the row is gone
            result = import_file(lib, src)
            assert result.status == "imported"
        finally:
            win.lib.close()


def test_delete_declined_keeps_everything(tmp_path, qapp, monkeypatch):
    """E3: «No» in the confirmation changes nothing — flag-only rule."""
    with Library(tmp_path / "lib") as lib:
        src = tmp_path / "جزوه مهم.pdf"
        src.write_bytes(b"keep me")
        import_file(lib, src)
        fid = lib.conn.execute("SELECT id FROM files").fetchone()["id"]

        win = mw_module.MainWindow(lib.root,
                                   {"language": "fa", "font_size": 10,
                                    "library": str(lib.root)},
                                   tmp_path / "settings.json")
        try:
            monkeypatch.setattr(
                QMessageBox, "question",
                staticmethod(lambda *a, **k: QMessageBox.No))
            win.delete_file(fid)
            assert lib.conn.execute(
                "SELECT COUNT(*) c FROM files").fetchone()["c"] == 1
            assert src.exists()
            assert win.table.rowCount() == 1   # table still shows it
        finally:
            win.lib.close()


def test_sweep_never_touches_the_trash(tmp_path):
    """E3 safety net: files/.trash is a subfolder of files/ and
    sweep_orphans only reconciles top-level files — a trashed file
    survives a library reopen with unknown leftovers around it."""
    with Library(tmp_path / "lib") as lib:
        src = tmp_path / "a.pdf"
        src.write_bytes(b"a")
        import_file(lib, src)
        fid = lib.conn.execute("SELECT id FROM files").fetchone()["id"]
        trash = lib.files_dir / ".trash"
        trash.mkdir(exist_ok=True)
        (lib.files_dir / "tmp_009.pdf").write_bytes(b"leftover")
        import shutil
        shutil.move(str(lib.stored_path(
            lib.conn.execute("SELECT * FROM files").fetchone())),
            str(trash / "000001.pdf"))
        lib.conn.execute("DELETE FROM files WHERE id=?", (fid,))
        lib.conn.commit()

    with Library(tmp_path / "lib") as lib2:      # reopen → sweep runs
        assert (trash / "000001.pdf").exists()   # trash untouched
        assert not (lib2.files_dir / "tmp_009.pdf").exists()  # tmp swept
