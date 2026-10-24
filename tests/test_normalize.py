"""Tests for Persian normalization (نرمال‌سازی)."""
from darspack.core.normalize import latin_digits, match_key, normalize, persian_digits

# (input, expected normalize() output)
CASES = [
    ("ریاضی", "ریاضی"),                     # already clean
    ("رياضي نهم", "ریاضی نهم"),             # Arabic ي → Persian ی
    ("كاربرگ", "کاربرگ"),                   # Arabic ك → Persian ک
    ("فصل ۳", "فصل 3"),                     # Persian digit → Latin
    ("فصل ٤", "فصل 4"),                     # Arabic-Indic digit → Latin
    ("نمونه‌سوال", "نمونه سوال"),           # ZWNJ treated as space
    ("ریاضی   نهم", "ریاضی نهم"),           # collapsed spaces
    ("  جزوه  ", "جزوه"),                   # stripped
    ("جزءُ", "جزء"),                        # diacritics removed
]


def test_normalize_table():
    for raw, expected in CASES:
        assert normalize(raw) == expected, f"normalize({raw!r})"


def test_match_key_casefolds_latin():
    assert match_key("Algebra.PDF") == "algebra.pdf"


def test_digit_conversions_roundtrip():
    assert persian_digits("1405") == "۱۴۰۵"
    assert latin_digits("۱۴۰۵") == "1405"
    assert latin_digits("٤٥٦") == "456"


def test_empty_and_none_safety():
    assert normalize("") == ""
    assert match_key("   ") == ""
