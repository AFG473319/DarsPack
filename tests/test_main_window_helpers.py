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
