"""Small table painters (نقاش‌های جدول).

The kind column is a rounded badge, painted by a delegate instead of a
widget per row — 2,000 rows stay cheap, and the badge stays crisp.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QApplication, QStyle, QStyledItemDelegate, QStyleOptionViewItem,
)

# subject/kind colours are deliberately muted so the eye stays on the names
KIND_BADGES = {
    "جزوه": ("#273556", "#b9c8ea"),
    "نمونه‌سوال": ("#3a2f18", "#f0c56a"),
    "کاربرگ": ("#1f3a2c", "#9ad1b1"),
    "تکلیف": ("#33283c", "#cbb2e2"),
    "سایر": ("#2a2e36", "#aab1bd"),
}


class KindBadgeDelegate(QStyledItemDelegate):
    """Paint the kind cell as a centered rounded pill."""

    def paint(self, painter, option, index) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text = opt.text
        opt.text = ""
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)
        if not text:
            return
        background, foreground = KIND_BADGES.get(text, KIND_BADGES["سایر"])
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        metrics = painter.fontMetrics()
        width = max(54, metrics.horizontalAdvance(text) + 20)
        height = 21
        rect = QRectF(option.rect.center().x() - width / 2,
                      option.rect.center().y() - height / 2, width, height)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(background))
        painter.drawRoundedRect(rect, 10, 10)
        painter.setPen(QColor(foreground))
        painter.drawText(rect, Qt.AlignCenter, text)
        painter.restore()
