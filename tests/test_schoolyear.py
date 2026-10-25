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
    # (This tests jdatetime's leap-year table, not our code — the app leans
    # on that contract, so it stays documented here.)
    assert school_year(jdatetime.date(1403, 12, 30)) == "1403-1404"


def test_non_leap_year_esfand_30_rejected():
    # again jdatetime's contract, not ours: 1402 is not a leap year
    with pytest.raises(ValueError):
        jdatetime.date(1402, 12, 30)


def test_today_has_a_school_year():
    assert "-" in current_school_year()


# --- the full boundary table: Mehr starts the next school year ----------

@pytest.mark.parametrize("month,expected", [
    (1, "1404-1405"), (2, "1404-1405"), (3, "1404-1405"),
    (4, "1404-1405"), (5, "1404-1405"), (6, "1404-1405"),
    (7, "1405-1406"), (8, "1405-1406"), (9, "1405-1406"),
    (10, "1405-1406"), (11, "1405-1406"), (12, "1405-1406"),
])
def test_all_twelve_months_of_year_1405(month, expected):
    assert school_year(jdatetime.date(1405, month, 15)) == expected


def test_current_school_year_honors_today_argument():
    # the injectable `today` parameter was never tested — it is what makes
    # this function testable without waiting for real Mehr
    assert current_school_year(today=jdatetime.date(1405, 7, 1)) == "1405-1406"
    assert current_school_year(today=jdatetime.date(1405, 6, 31)) == "1404-1405"
