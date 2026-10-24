"""Metadata suggestions from Persian filenames (پیشنهاد فراداده).

Students and teachers already encode metadata in filenames — «نمونه
سوال ریاضی نهم فصل 3.pdf». This module reads exactly that and proposes
subject / chapter / kind. Suggestions are *shown for review* in the
import dialog; nothing is applied silently.
"""
from __future__ import annotations

import re

from .normalize import latin_digits, match_key

# Default subject list (فهرست دروس دوره اول متوسطه); editable in the app later.
DEFAULT_SUBJECTS = [
    "ریاضی", "علوم", "علوم تجربی", "فارسی", "عربی", "دینی", "انگلیسی",
    "مطالعات اجتماعی", "هنر", "کار و فناوری", "تربیت بدنی",
    "آمادگی دفاعی", "سلامت و بهداشت", "تفکر و سبک زندگی", "کارگاه",
]

# Keyword → file kind (نوع فایل). Keys are matched after normalization,
# so «نمونه‌سوال» with a half-space also matches the «نمونه سوال» key.
_KIND_HINTS = {
    "نمونه سوال": "نمونه‌سوال", "نمونه سوالات": "نمونه‌سوال",
    "امتحان": "نمونه‌سوال", "آزمون": "نمونه‌سوال",
    "جزوه": "جزوه", "خلاصه": "جزوه", "جزوات": "جزوه",
    "کاربرگ": "کاربرگ", "ورقه": "کاربرگ",
    "تکلیف": "تکلیف", "تمرین": "تکلیف", "پروژه": "تکلیف", "مشی": "تکلیف",
}

# «فصل سه» style chapter words (school books have up to 12+ chapters).
_WORD_NUMBERS = {"یک": 1, "دو": 2, "سه": 3, "چهار": 4, "پنج": 5, "شش": 6,
                 "هفت": 7, "هشت": 8, "نه": 9, "ده": 10, "یازده": 11,
                 "دوازده": 12}

_CHAPTER_RE = re.compile(r"فصل\s*([0-9]{1,2})")
MAX_CHAPTER = 40  # sanity bound — anything larger is not a school chapter


def suggest(filename_stem: str, subjects=None) -> dict:
    """Suggest {'subject', 'chapter', 'kind'} from a filename (no extension).

    Every value may be None. The importer turns subject names into ids;
    here we keep it string-based so the function is trivially testable.
    """
    key = match_key(latin_digits(filename_stem))
    out: dict = {"subject": None, "chapter": None, "kind": None}

    for subj in (subjects if subjects is not None else DEFAULT_SUBJECTS):
        if match_key(subj) in key:
            out["subject"] = subj
            break

    m = _CHAPTER_RE.search(key)
    if m and int(m.group(1)) <= MAX_CHAPTER:
        out["chapter"] = int(m.group(1))
    else:
        for word, num in _WORD_NUMBERS.items():
            if f"فصل {word}" in key:
                out["chapter"] = num
                break

    for hint, kind in _KIND_HINTS.items():
        if match_key(hint) in key:
            out["kind"] = kind
            break
    return out
