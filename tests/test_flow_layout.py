"""FlowLayout: the filter bar must wrap instead of clipping.

The user's font setting scales the fixed-width filter widgets; a plain
QHBoxLayout silently clipped the row's far end once the row outgrew the
window. FlowLayout wraps to further lines while reproducing the
QHBoxLayout it replaced on a single line (order, stretch gap, RTL).
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton, QWidget

from darspack.ui.flow_layout import FlowLayout


def _button(text: str) -> QPushButton:
    return QPushButton(text)


def test_single_line_mimics_hbox_with_stretch(qapp):
    """While everything fits, the tail items are pushed to the far edge
    by the stretch gap — exactly the QHBoxLayout behaviour."""
    host = QWidget()
    host.resize(400, 40)
    lay = FlowLayout(host)
    first = _button("AAA")
    last = _button("BBB")
    lay.addWidget(first)
    lay.addStretch()
    lay.addWidget(last)
    host.show()
    qapp.processEvents()                       # let the layout settle
    assert first.geometry().left() == 0
    assert last.geometry().right() >= 395      # pushed to the far edge
    assert first.geometry().bottom() <= 40     # still one line


def test_wraps_instead_of_clipping(qapp):
    """Items that no longer fit move to the next line, none of them
    outside the layout's width."""
    host = QWidget()
    host.resize(250, 100)
    lay = FlowLayout(host)
    buttons = [_button("AAAAAAAAAA"), _button("BBBBBBBBBB"),
               _button("CCCCCCCCCC")]
    for btn in buttons:
        lay.addWidget(btn)
    host.show()
    qapp.processEvents()                       # let the layout settle
    assert lay.heightForWidth(250) > buttons[0].sizeHint().height()
    for btn in buttons:
        assert btn.x() >= 0
        assert btn.x() + btn.width() <= 251
        assert btn.y() >= 0


def test_rtl_flows_right_to_left(qapp):
    """In the RTL Persian UI the first-added item stays on the right."""
    host = QWidget()
    host.setLayoutDirection(Qt.RightToLeft)
    lay = FlowLayout(host)
    first = _button("AAA")
    second = _button("BBB")
    lay.addWidget(first)
    lay.addWidget(second)
    host.resize(400, 40)
    host.show()
    qapp.processEvents()                       # let the layout settle
    assert first.geometry().right() >= 395
    assert second.geometry().right() < first.geometry().left()
