"""Wrapping row layout (چیدمان سطری شکستنی) for the filter bar.

A plain QHBoxLayout silently clips its fixed-width children when the
user's large font setting (Settings «اندازه‌ی قلم») makes the row wider
than the window. FlowLayout keeps the same order and sizes but wraps
onto further lines instead of clipping, each line vertically centered.

While everything fits on one line it reproduces the QHBoxLayout it
replaces — including the stretching gap (the addStretch) at its added
position, pushing the items after it to the far edge — and the stretch
collapses once wrapping starts. Mirrors the parent's layout direction:
in the RTL Persian UI the first-added item stays on the right.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QSizePolicy, QSpacerItem


class FlowLayout(QLayout):
    """A one-row QHBoxLayout that wraps instead of clipping."""

    def __init__(self, parent=None, spacing: int = 8) -> None:
        super().__init__(parent)
        self._items: list = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)

    # -- QLayout bookkeeping -------------------------------------------------

    def addItem(self, item) -> None:
        self._items.append(item)

    def addStretch(self, _stretch: int = 0) -> None:
        """Add the expanding gap at this position in the order (the
        argument matches QHBoxLayout)."""
        self._items.append(QSpacerItem(0, 0,
                                       QSizePolicy.Policy.Expanding,
                                       QSizePolicy.Policy.Minimum))

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientations:
        return Qt.Orientations(Qt.Orientation.Horizontal)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, apply=True)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(),
                      margins.top() + margins.bottom())
        return size

    # -- placement -----------------------------------------------------------

    def _lines(self, width: int) -> list[list]:
        """Greedy line breaking over the widgets; the stretch gap never
        takes part in wrapping."""
        lines: list[list] = []
        current: list = []
        for item in self._items:
            if isinstance(item, QSpacerItem):
                continue
            if current and (
                    sum(i.sizeHint().width() for i in current)
                    + self.spacing() * len(current)
                    + item.sizeHint().width() > width):
                lines.append(current)
                current = []
            current.append(item)
        if current:
            lines.append(current)
        return lines

    def _do_layout(self, rect: QRect, apply: bool) -> int:
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(),
                             -margins.right(), -margins.bottom())
        rtl = (self.parentWidget() is not None and
               self.parentWidget().layoutDirection() == Qt.RightToLeft)
        lines = self._lines(area.width())
        spacing = self.spacing()

        # While all widgets share one line the stretch gap takes the slack
        # (the QHBoxLayout behaviour); once wrapping starts it collapses.
        widgets = [i for i in self._items if not isinstance(i, QSpacerItem)]
        on_one_line = len(lines) == 1 and len(widgets) < len(self._items)
        stretch_w = 0
        if on_one_line:
            used = sum(i.sizeHint().width() for i in widgets)
            stretch_w = max(0, area.width() - used
                            - spacing * (len(self._items) - 1))

        line_of = {id(item): idx
                   for idx, line in enumerate(lines) for item in line}
        y = area.y()
        current_line = -1
        line_height = 0
        x_start = area.right() + 1 if rtl else area.x()
        x = x_start
        for item in self._items:
            if isinstance(item, QSpacerItem):
                if not on_one_line:
                    continue            # the gap collapses when wrapping
                w = stretch_w
            else:
                idx = line_of[id(item)]
                if idx != current_line:  # wrapped onto a new line
                    if current_line >= 0:
                        y += line_height + spacing
                    line_height = max(i.sizeHint().height()
                                      for i in lines[idx])
                    current_line = idx
                    x = x_start
                w = item.sizeHint().width()
            if rtl:
                left = x - w
                x -= w + spacing
            else:
                left = x
                x += w + spacing
            if isinstance(item, QSpacerItem):
                continue                # invisible; only consumes width
            hint = item.sizeHint()
            top = y + (line_height - hint.height()) // 2
            if apply:
                item.setGeometry(QRect(QPoint(left, top), hint))
        content_h = (y + line_height - area.y()) if lines else 0
        return max(0, content_h) + margins.top() + margins.bottom()
