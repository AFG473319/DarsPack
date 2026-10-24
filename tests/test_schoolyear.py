"""Tests for Jalali school-year boundaries (سال تحصیلی)."""
import jdatetime
import pytest

from darspack.core.schoolyear import current_school_year, school_year


def test_mehr_1_starts_new_year():
    assert school_year(jdatetime.date(1405, 7, 1)) == "1405-1406"


def test_late_shahrivar_belongs_to_previous_year():
    assert school_year(jdatetime.date(1405, 6, 31)) == "1404-1405"


def test_mid_year():
    assert school_year(jdatetime.date(1405, 9, 15)) == "1405-1406"
    assert school_year(jdatetime.date(1406, 3, 20)) == "1405-1406"


def test_leap_year_esfand_30_exists():
    # 1403 is a Jalali leap year: Esfand 30 (اسفند ۳۰) is valid.
    assert school_year(jdatetime.date(1403, 12, 30)) == "1403-1404"


def test_non_leap_year_esfand_30_rejected():
    with pytest.raises(ValueError):
        jdatetime.date(1402, 12, 30)   # 1402 is not a leap year


def test_today_has_a_school_year():
    assert "-" in current_school_year()
