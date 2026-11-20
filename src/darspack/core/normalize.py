"""Persian text normalization (نرمال‌سازی متن فارسی).

Display keeps the user's original text exactly as typed. These helpers
build *match keys* instead — used for search and for comparing file
names — so that typing style never changes what matches:

- Arabic ي/ك become Persian ی/ک  (typing «رياضي» finds «ریاضی»)
- Arabic and Persian digits become Latin digits  («فصل ۳» matches «فصل 3»)
- diacritics (اعراب) and tatweel are removed
- ZWNJ (نیم‌فاصله) is treated as a space, so «نمونه‌سوال» matches «نمونه سوال»
- whitespace collapses to single spaces
"""
from __future__ import annotations

import unicodedata

# Arabic letters commonly mistyped for their Persian equivalents.
_AR_TO_FA = str.maketrans({"ي": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه"})

# All ten Arabic-Indic and Extended Arabic-Indic digits → ASCII 0-9.
_TO_LATIN = str.maketrans("۰۱۲۳۴۵۶۷۸۹" + "٠١٢٣٤٥٦٧٨٩", "0123456789" * 2)
_TO_PERSIAN = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

ZWNJ = "\u200c"

# One table for normalize(): the three substitutions above plus dropping
# combining marks (fatha, kasra, sukun, …) and tatweel (کشیده), and
# treating ZWNJ as a space. Disjoint character sets, so a single pass
# gives exactly what three chained passes used to.
_NORMALIZE_TABLE = {
    **_AR_TO_FA,
    **_TO_LATIN,
    ord(ZWNJ): " ",
    **{cp: None for cp in (*range(0x064B, 0x0660), 0x0670, 0x0640)},
}


def latin_digits(text: str) -> str:
    """Convert Persian/Arabic digits to Latin digits."""
    return text.translate(_TO_LATIN)


def persian_digits(text: str) -> str:
    """Convert Latin digits to Persian digits (for UI display)."""
    return text.translate(_TO_PERSIAN)


def normalize(text: str) -> str:
    """Canonical form used for matching keys (see module docstring)."""
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    # str.split() splits on the same Unicode whitespace runs the old
    # regex matched, and drops leading/trailing whitespace too.
    return " ".join(text.translate(_NORMALIZE_TABLE).split())


def match_key(text: str) -> str:
    """normalize + casefold — the key for names, tags, subjects, queries."""
    return normalize(text).casefold()
