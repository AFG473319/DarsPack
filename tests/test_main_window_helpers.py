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
