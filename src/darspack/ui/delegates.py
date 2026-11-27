"""Small table painters (نقاش‌های جدول).

The kind column is a rounded badge, painted by a delegate instead of a
widget per row — 2,000 rows stay cheap, and the badge stays crisp.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPalette
from PySide6.QtWidgets import (
    QApplication, QLabel, QSizePolicy, QStyle, QStyledItemDelegate, QStyleOptionViewItem,
)

from .. import i18n
from . import theme

# subject/kind colours are deliberately muted so the eye stays on the names
KIND_BADGES = {
    "جزوه": ("#273556", "#b9c8ea"),
    "نمونه‌سوال": ("#3a2f18", "#f0c56a"),
    "کاربرگ": ("#1f3a2c", "#9ad1b1"),
    "تکلیف": ("#33283c", "#cbb2e2"),
    "سایر": ("#2a2e36", "#aab1bd"),
}

# Light-mode pairs: a light tinted background with a dark colour of the
# same hue — an inversion of the dark pairs would leave washed-out text.
KIND_BADGES_LIGHT = {
    "جزوه": ("#e2e8f6", "#2f4070"),
    "نمونه‌سوال": ("#f6ecd4", "#8a6410"),
    "کاربرگ": ("#ddf0e4", "#2e6e4c"),
    "تکلیف": ("#ece2f4", "#5f3d82"),
    "سایر": ("#e8eaee", "#565d69"),
}


def kind_badges() -> dict:
    """The kind-colour pairs for the active theme (table rows and cards)."""
    if theme.active_theme() == "light":
        return KIND_BADGES_LIGHT
    return KIND_BADGES


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
        badges = kind_badges()
        background, foreground = badges.get(text, badges["سایر"])
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        metrics = painter.fontMetrics()
        width = max(54, metrics.horizontalAdvance(text) + 20)
        height = 21
        rect = QRectF(option.rect.center().x() - width / 2,
                      option.rect.center().y() - height / 2, width, height)
        border_color = QColor(foreground)
        border_color.setAlpha(75)
        painter.setPen(border_color)
        painter.setBrush(QColor(background))
        painter.drawRoundedRect(rect, 10, 10)
        painter.setPen(QColor(foreground))
        painter.drawText(rect, Qt.AlignCenter, text)
        painter.restore()


def split_filename_ext(name: str) -> tuple[str, str]:
    """Split an ASCII file extension into `(stem, EXT)` for badge display."""
    dot = name.rfind(".")
    if 0 < dot < len(name) - 1:
        ext = name[dot + 1:]
        if ext.isascii() and ext.isalnum() and 1 <= len(ext) <= 6:
            return name[:dot], ext.upper()
    return name, ""


def paint_filename_badge(
    painter: QPainter,
    rect: QRectF,
    font: QFont,
    text: str,
    *,
    text_color: QColor,
    selected: bool,
    rtl: bool,
    inline_badge: bool = False,
) -> None:
    """Paint a filename stem plus a muted ASCII extension pill without BiDi glitches."""
    if not text:
        return
    stem, ext = split_filename_ext(text)
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)

    painter.setFont(font)
    fm = painter.fontMetrics()

    if ext:
        badge_font = QFont(font)
        badge_font.setPointSizeF(max(7.2, badge_font.pointSizeF() - 1.5))
        badge_font.setWeight(QFont.DemiBold)
        bm = QFontMetrics(badge_font)
        ext_w = max(36, bm.horizontalAdvance(ext) + 12)
        ext_h = max(19, bm.height() + 4)
        gap = 8
        cy = rect.center().y()

        if inline_badge:
            max_stem_w = max(24.0, rect.width() - ext_w - gap - 4)
            elided = fm.elidedText(stem, Qt.ElideMiddle, int(max_stem_w))
            drawn_w = min(float(fm.horizontalAdvance(elided)), max_stem_w)
            if rtl:
                stem_rect = QRectF(
                    rect.right() - drawn_w, rect.top(), drawn_w + 1, rect.height()
                )
                bx = stem_rect.left() - gap - ext_w
            else:
                stem_rect = QRectF(
                    rect.left(), rect.top(), drawn_w + 1, rect.height()
                )
                bx = stem_rect.right() + gap
        else:
            elided = None
            if rtl:
                bx = rect.left() + 4
                stem_rect = QRectF(
                    bx + ext_w + gap, rect.top(),
                    max(24.0, rect.right() - (bx + ext_w + gap)),
                    rect.height(),
                )
            else:
                bx = rect.right() - ext_w - 4
                stem_rect = QRectF(
                    rect.left(), rect.top(),
                    max(24.0, bx - gap - rect.left()),
                    rect.height(),
                )

        badge_rect = QRectF(bx, cy - ext_h / 2, ext_w, ext_h)
        pal = theme.PALETTE
        painter.setPen(QColor(
            pal["ext_border_sel"] if selected else pal["ext_border"]))
        painter.setBrush(QColor(
            pal["ext_bg_sel"] if selected else pal["ext_bg"]))
        painter.drawRoundedRect(badge_rect, 5, 5)
        painter.setFont(badge_font)
        painter.setPen(QColor(
            pal["ext_text_sel"] if selected else pal["ext_text"]))
        painter.drawText(badge_rect, Qt.AlignCenter, ext)

        painter.setFont(font)
        if elided is None:
            elided = fm.elidedText(stem, Qt.ElideMiddle, int(stem_rect.width()))
    else:
        stem_rect = QRectF(rect)
        elided = fm.elidedText(stem, Qt.ElideMiddle, int(stem_rect.width()))

    painter.setPen(text_color)
    align = (Qt.AlignRight if rtl else Qt.AlignLeft) | Qt.AlignAbsolute | Qt.AlignVCenter
    painter.drawText(stem_rect, align, i18n.isolate_rtl(elided))
    painter.restore()


class FileNameLabel(QLabel):
    """QLabel that keeps the raw filename in `.text()` while painting the stem
    and an inline extension pill cleanly in RTL/LTR banners."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def sizeHint(self) -> QSize:
        fm = self.fontMetrics()
        stem, ext = split_filename_ext(self.text())
        badge_w = 0
        if ext:
            badge_font = QFont(self.font())
            badge_font.setPointSizeF(max(7.2, badge_font.pointSizeF() - 1.5))
            badge_font.setWeight(QFont.DemiBold)
            badge_w = max(36, QFontMetrics(badge_font).horizontalAdvance(ext) + 12) + 8
        w = fm.horizontalAdvance(stem) + badge_w + 8
        return QSize(max(120, min(640, w)), max(fm.height() + 8, 28))

    def minimumSizeHint(self) -> QSize:
        return QSize(120, max(self.fontMetrics().height() + 8, 28))

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        rtl = self.layoutDirection() == Qt.RightToLeft
        color = self.palette().color(QPalette.ColorRole.WindowText)
        paint_filename_badge(
            painter, QRectF(self.rect()), self.font(), self.text(),
            text_color=color, selected=False, rtl=rtl, inline_badge=True,
        )


class KeycapDelegate(QStyledItemDelegate):
    """Paint keyboard shortcuts inside crisp styled `<kbd>` keycap pills while
    preserving the raw text in `QTableWidgetItem`."""

    def paint(self, painter, option, index) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text = opt.text
        opt.text = ""
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)
        if not text:
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setLayoutDirection(Qt.LeftToRight)
        key_font = QFont("Consolas", 9, QFont.Bold)
        painter.setFont(key_font)
        fm = painter.fontMetrics()
        parts = [p.strip() for p in text.split("+")] if " + " in text else [text]
        gap = 4
        plus_w = fm.horizontalAdvance("+") + 4
        pill_widths = [max(26, fm.horizontalAdvance(p) + 14) for p in parts]
        total_w = sum(pill_widths) + (len(parts) - 1) * (plus_w + gap * 2)
        h = 22
        y = option.rect.center().y() - h / 2
        x = option.rect.center().x() - total_w / 2
        pal = theme.PALETTE
        for idx, (part, pw) in enumerate(zip(parts, pill_widths)):
            pill = QRectF(x, y, pw, h)
            painter.setPen(QColor(pal["keycap_border"]))
            painter.setBrush(QColor(pal["keycap_bg"]))
            painter.drawRoundedRect(pill, 6, 6)
            painter.setPen(QColor(pal["keycap_text"]))
            painter.drawText(pill, Qt.AlignCenter, part)
            x += pw + gap
            if idx < len(parts) - 1:
                plus_rect = QRectF(x, y, plus_w, h)
                painter.setPen(QColor(pal["keycap_plus"]))
                painter.drawText(plus_rect, Qt.AlignCenter, "+")
                x += plus_w + gap
        painter.restore()


class FileNameDelegate(QStyledItemDelegate):
    """Render filenames cleanly in RTL/LTR tables with a muted extension badge
    so Latin extensions (e.g. PDF, PNG) never collide with Persian numerals or
    strand a leading dot at the end of a line."""

    _split_ext = staticmethod(split_filename_ext)

    def __init__(self, parent=None, *, filename_role: int | None = None):
        super().__init__(parent)
        self._filename_role = filename_role

    def paint(self, painter, option, index) -> None:
        if self._filename_role is not None and not index.data(self._filename_role):
            super().paint(painter, option, index)
            return
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text = opt.text
        style = opt.widget.style() if opt.widget else QApplication.style()
        text_rect = style.subElementRect(QStyle.SE_ItemViewItemText, opt, opt.widget)
        opt.text = ""
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)
        selected = bool(opt.state & QStyle.State_Selected)
        rtl = opt.direction == Qt.RightToLeft
        text_color = (
            opt.palette.color(QPalette.ColorRole.HighlightedText)
            if selected else opt.palette.color(QPalette.ColorRole.Text)
        )
        paint_filename_badge(
            painter, QRectF(text_rect), opt.font, text,
            text_color=text_color, selected=selected, rtl=rtl, inline_badge=True,
        )
