"""Jalali school-year helpers (سال تحصیلی).

The Iranian school year starts on 1 Mehr (مهر, month 7) and is named
after the two calendar years it spans, e.g. «1405-1406». Storing the
school year per file lets a student keep this year's and last year's
نمونه‌سوال side by side without confusion.
"""
from __future__ import annotations

import jdatetime

MONTH_MEHR = 7  # Jalali month 7 = Mehr; school starts on its first day


def school_year(jdate: jdatetime.date) -> str:
    """Return the school-year label («1405-1406») a Jalali date belongs to."""
    if jdate.month >= MONTH_MEHR:
        return f"{jdate.year}-{jdate.year + 1}"
    return f"{jdate.year - 1}-{jdate.year}"


def current_school_year(today: jdatetime.date | None = None) -> str:
    return school_year(today if today is not None else jdatetime.date.today())
