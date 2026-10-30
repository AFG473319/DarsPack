"""The merged «فصل / درس» table cell and table display/sorting tests."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from darspack.ui.main_window import (
    TableSortItem, chapter_lesson_display, MainWindow,
)
from darspack.core.library import Library
from darspack.core.importer import import_file


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


def test_table_sort_item_numeric_and_tuple_sorting():
    item1 = TableSortItem("10 KB")
    item1.setData(TableSortItem.SORT_KEY_ROLE, 10240)

    item2 = TableSortItem("2 KB")
    item2.setData(TableSortItem.SORT_KEY_ROLE, 2048)

    item3 = TableSortItem("1.5 MB")
    item3.setData(TableSortItem.SORT_KEY_ROLE, 1572864)

    # Lexicographically, "1.5 MB" < "10 KB" < "2 KB"
    # But with SORT_KEY_ROLE, 2048 < 10240 < 1572864
    assert item2 < item1
    assert item1 < item3
    assert not (item3 < item1)

    # Tuple sorting for chapter / lesson
    c2 = TableSortItem("فصل ۲")
    c2.setData(TableSortItem.SORT_KEY_ROLE, (2, 0))
    c10 = TableSortItem("فصل ۱۰")
    c10.setData(TableSortItem.SORT_KEY_ROLE, (10, 0))

    assert c2 < c10
    assert not (c10 < c2)


def test_file_type_icons(tmp_path, qapp):
    win = MainWindow(tmp_path / "lib",
                     {"language": "fa", "font_size": 10,
                      "library": str(tmp_path / "lib")},
                     tmp_path / "settings.json")
    try:
        icon_pdf = win._file_icon_for("test.pdf")
        icon_zip = win._file_icon_for("archive.zip")
        icon_pkg = win._file_icon_for("pack.darspack")
        icon_txt = win._file_icon_for("notes.txt")

        assert not icon_pdf.isNull()
        assert not icon_zip.isNull()
        assert not icon_pkg.isNull()
        assert not icon_txt.isNull()
    finally:
        win.lib.close()


def test_copy_selected_names_and_paths(tmp_path, qapp):
    with Library(tmp_path / "lib") as lib:
        f1 = tmp_path / "f1.pdf"
        f1.write_bytes(b"data1")
        import_file(lib, f1)

        f2 = tmp_path / "f2.pdf"
        f2.write_bytes(b"data2")
        import_file(lib, f2)

    win = MainWindow(tmp_path / "lib",
                     {"language": "fa", "font_size": 10,
                      "library": str(tmp_path / "lib")},
                     tmp_path / "settings.json")
    try:
        win.table.selectAll()
        win.copy_selected_names()
        text = QApplication.clipboard().text()
        assert "f1.pdf" in text and "f2.pdf" in text

        win.copy_selected_paths()
        path_text = QApplication.clipboard().text()
        assert "files" in path_text
    finally:
        win.lib.close()
