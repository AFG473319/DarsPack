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


# --- more normalization promises (module docstring claims, now pinned) ---

ZWNJ = "\u200c"   # نیم‌فاصله — written as an escape so counts are unambiguous

MORE_CASES = [
    ("جـــزوه", "جزوه"),            # tatweel (کشیده) removed
    ("مكتبة", "مکتبه"),             # Arabic ة → ه (plus ك → ک)
    ("ریاضی\n\tنهم", "ریاضی نهم"),  # tabs/newlines collapse, not just spaces
    (ZWNJ + "ریاضی" + ZWNJ, "ریاضی"),            # edge ZWNJ → space → stripped
    ("نمونه" + ZWNJ + ZWNJ + "سوال", "نمونه سوال"),  # double ZWNJ collapses
]


def test_normalize_more_table():
    for raw, expected in MORE_CASES:
        assert normalize(raw) == expected, f"normalize({raw!r})"


def test_normalize_none_is_empty():
    # the defensive `if not text` branch — None arrives from Qt line edits
    # more often than you would think
    assert normalize(None) == ""


def test_full_digit_tables_convert_to_latin():
    # every digit of BOTH tables (Persian ۰-۹ and Arabic-Indic ٠-٩),
    # not just the two spot-checked above
    assert latin_digits("۰۱۲۳۴۵۶۷۸۹") == "0123456789"
    assert latin_digits("٠١٢٣٤٥٦٧٨٩") == "0123456789"


def test_persian_digits_only_touches_latin_digits():
    # documented scope of the DISPLAY helper: Latin→Persian only, so an
    # Arabic-Indic digit passes through unchanged — pinned so a future
    # widening of the mapping is a deliberate decision
    assert persian_digits("٤") == "٤"


def test_normalize_all_arabic_diacritics():
    # Fatha, Kasra, Damma, Tanwin (Fath/Damm/Kasr), Shadda, Sukun
    raw = "دَرْسٌ مُهِمٌّ وَمُفِيدٌ"
    assert normalize(raw) == "درس مهم ومفید"


def test_match_key_none_and_whitespace():
    assert match_key(None) == ""
    assert match_key("   \t\n  ") == ""
    assert latin_digits("") == ""
    assert persian_digits("") == ""
    assert latin_digits(None) == ""
    assert persian_digits(None) == ""
