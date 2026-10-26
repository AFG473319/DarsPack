"""The merged «فصل / درس» table cell (the user asked why the lesson
number was missing: the subject column header «درس» and the new lesson
field collided, and the table never showed lesson at all)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from darspack.ui.main_window import chapter_lesson_display


def test_chapter_only():
    assert chapter_lesson_display(3, None) == "فصل ۳"


def test_lesson_only():
    assert chapter_lesson_display(None, 5) == "درس ۵"


def test_both():
    assert chapter_lesson_display(2, 5) == "فصل ۲ / درس ۵"


def test_neither():
    assert chapter_lesson_display(None, None) == "—"


def test_two_digit_numbers_use_persian_digits():
    assert chapter_lesson_display(12, None) == "فصل ۱۲"
