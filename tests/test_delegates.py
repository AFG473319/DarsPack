"""Table cell/label/badge helpers (نقاش‌های جدول)."""
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter, qAlpha
from PySide6.QtWidgets import (
    QTableWidget, QTableWidgetItem, QStyleOptionViewItem,
)

from darspack.ui.delegates import (
    FileNameDelegate, FileNameLabel, KindBadgeDelegate, KeycapDelegate,
    paint_filename_badge, split_filename_ext,
)


def _alpha_pixels(image):
    return sum(1 for x in range(image.width()) for y in range(image.height())
               if qAlpha(image.pixel(x, y)) > 0)


def test_split_filename_ext_table():
    assert split_filename_ext("ریاضی فصل 3.pdf") == ("ریاضی فصل 3", "PDF")
    assert split_filename_ext("نمونه سوال.TAR") == ("نمونه سوال", "TAR")
    assert split_filename_ext("بدون-پسوند") == ("بدون-پسوند", "")
    assert split_filename_ext("a.b.c") == ("a.b", "C")
    assert split_filename_ext("name.") == ("name.", "")
    assert split_filename_ext(".hidden") == (".hidden", "")
    assert split_filename_ext("name.1234567") == ("name.1234567", "")
    assert split_filename_ext("name.1") == ("name", "1")


def test_file_name_label_size_hint_respects_the_floor(qapp):
    assert FileNameLabel("").sizeHint().width() == 120
    assert FileNameLabel("جزوه").sizeHint().width() >= 120
    assert FileNameLabel("جزوه").minimumSizeHint().width() == 120


def _badge_image(text):
    image = QImage(220, 40, QImage.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    paint_filename_badge(painter, QRectF(0, 0, 220, 40), painter.font(), text,
                         text_color=QColor("#ffffff"), selected=False, rtl=False)
    painter.end()
    return image


def test_paint_filename_badge_draws_names_and_nothing_for_empty():
    assert _alpha_pixels(_badge_image("")) == 0
    assert _alpha_pixels(_badge_image("نمونه سوال.pdf")) > 0


def _table_render(delegate, text):
    """Paint one QTableWidget cell through `delegate` onto a QImage."""
    table = QTableWidget(1, 1)
    table.setItem(0, 0, QTableWidgetItem(text))
    table.setItemDelegate(delegate)
    index = table.model().index(0, 0)
    option = QStyleOptionViewItem()
    option.rect = table.visualItemRect(table.item(0, 0))
    option.widget = table
    image = QImage(220, 40, QImage.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    delegate.paint(painter, option, index)
    painter.end()
    return image


def test_kind_badge_delegate_paint_named_beats_empty():
    named = _table_render(KindBadgeDelegate(), "جزوه")
    empty = _table_render(KindBadgeDelegate(), "")
    assert _alpha_pixels(named) > 0
    assert _alpha_pixels(named) > _alpha_pixels(empty)


def test_keycap_delegate_paint_draws_the_keycap():
    assert _alpha_pixels(_table_render(KeycapDelegate(), "Ctrl+Z")) > 0


def test_file_name_delegate_paint_draws_the_badge():
    assert _alpha_pixels(_table_render(FileNameDelegate(), "نمونه سوال.pdf")) > 0
