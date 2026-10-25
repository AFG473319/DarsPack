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
# The canonical science subject is «علوم تجربی» (the official textbook name —
# design decision 2026-10-24): the bare «علوم» entry is gone so the two can
# never fight over the same filename.
DEFAULT_SUBJECTS = [
    "ریاضی", "علوم تجربی", "فارسی", "عربی", "دینی", "انگلیسی",
    "مطالعات اجتماعی", "هنر", "کار و فناوری", "تربیت بدنی",
    "آمادگی دفاعی", "سلامت و بهداشت", "تفکر و سبک زندگی", "کارگاه",
]

# Keyword → file kind (نوع فایل). Keys are matched after normalization,
# so «نمونه‌سوال» with a half-space also matches the «نمونه سوال» key.
_KIND_HINTS = {
    "نمونه سوال": "نمونه‌سوال", "نمونه سوالات": "نمونه‌سوال",
    "امتحان": "نمونه‌سوال", "آزمون": "نمونه‌سوال",
    "بانک سوال": "نمونه‌سوال", "سوالات": "نمونه‌سوال", "سوال": "نمونه‌سوال",
    "تست": "نمونه‌سوال",
    "جزوه": "جزوه", "خلاصه": "جزوه", "جزوات": "جزوه",
    "مرور": "جزوه", "جمع بندی": "جزوه", "فرمول": "جزوه",
    "کاربرگ": "کاربرگ", "ورقه": "کاربرگ",
    "تکلیف": "تکلیف", "تمرین": "تکلیف", "پروژه": "تکلیف", "مشی": "تکلیف",
}

# «فصل سه» style chapter words (school books have up to 12+ chapters).
_WORD_NUMBERS = {"یک": 1, "دو": 2, "سه": 3, "چهار": 4, "پنج": 5, "شش": 6,
                 "هفت": 7, "هشت": 8, "نه": 9, "ده": 10, "یازده": 11,
                 "دوازده": 12}
# Read-only alias for other modules (search parses «فصل سه» queries too);
# the table itself stays private to this module.
WORD_NUMBERS = _WORD_NUMBERS

_CHAPTER_RE = re.compile(r"فصل\s*([0-9]{1,2})")
_LESSON_RE = re.compile(r"درس\s*([0-9]{1,2})")
MAX_CHAPTER = 40  # sanity bound — anything larger is not a school chapter
# درس reuses the same bound: junior-high books have at most ~12 of each.

# Grade words in filenames («نمونه سوال ریاضی نهم»); a display hint only.
_GRADES = ("نهم", "هشتم", "هفتم")


def suggest(filename_stem: str, subjects=None) -> dict:
    """Suggest {'subject', 'chapter', 'lesson', 'kind', 'grade'} from a filename.

    The stem carries no extension. Every value may be None. The importer
    turns subject names into ids; here we keep it string-based so the
    function is trivially testable. chapter is the «فصل» number and lesson
    the «درس» number — stored in separate columns because a file may have
    either, both, or neither (design decision 2026-10-24).
    """
    key = match_key(latin_digits(filename_stem))
    out: dict = {"subject": None, "chapter": None, "lesson": None,
                 "kind": None, "grade": None}

    # Longest match first: «علوم تجربی» must beat any shorter overlap, and
    # a custom subject list gets the same courtesy.
    for subj in sorted(subjects if subjects is not None else DEFAULT_SUBJECTS,
                       key=lambda s: len(match_key(s)), reverse=True):
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

    m = _LESSON_RE.search(key)
    if m and int(m.group(1)) <= MAX_CHAPTER:
        out["lesson"] = int(m.group(1))
    else:
        for word, num in _WORD_NUMBERS.items():
            if f"درس {word}" in key:
                out["lesson"] = num
                break

    for hint, kind in _KIND_HINTS.items():
        if match_key(hint) in key:
            out["kind"] = kind
            break

    for grade in _GRADES:
        if grade in key:
            out["grade"] = grade
            break
    return out
