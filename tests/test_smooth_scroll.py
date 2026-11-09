"""Tests for browser-grade smooth scrolling (SmoothScroller)."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QAbstractAnimation, QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent, QWheelEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QListWidget,
    QTableWidget,
)

from darspack.ui.smooth_scroll import SmoothScroller, enable_smooth_scroll


def make_wheel_event(
    angle_y: int = -120,
    angle_x: int = 0,
    pixel_x: int = 0,
    pixel_y: int = 0,
    modifiers=Qt.NoModifier,
) -> QWheelEvent:
    return QWheelEvent(
        QPointF(50, 50),
        QPointF(50, 50),
        QPoint(pixel_x, pixel_y),
        QPoint(angle_x, angle_y),
        Qt.NoButton,
        modifiers,
        Qt.ScrollUpdate,
        False,
    )


def test_smooth_scroll_configures_pixel_mode(qapp):
    table = QTableWidget(100, 5)
    # Defaults in Qt are ScrollPerItem
    assert table.verticalScrollMode() == QAbstractItemView.ScrollPerItem

    scroller = enable_smooth_scroll(table)
    assert table.verticalScrollMode() == QAbstractItemView.ScrollPerPixel
    assert table.horizontalScrollMode() == QAbstractItemView.ScrollPerPixel
    assert scroller is not None


def test_smooth_scroll_wheel_animates_vertical(qapp):
    table = QTableWidget(200, 5)
    table.resize(400, 300)
    table.show()
    qapp.processEvents()

    scroller = enable_smooth_scroll(table, step_size=95, duration=100)
    vbar = table.verticalScrollBar()
    # Populate items so scroll range is positive
    vbar.setRange(0, 2000)
    vbar.setValue(0)

    # Wheel down (negative angle delta)
    event = make_wheel_event(angle_y=-120)
    consumed = scroller.eventFilter(table.viewport(), event)
    assert consumed is True
    assert scroller._v_target == 95
    assert scroller._v_anim.state() == QAbstractAnimation.Running

    # Fast second wheel notch down accumulates
    event2 = make_wheel_event(angle_y=-120)
    scroller.eventFilter(table.viewport(), event2)
    assert scroller._v_target == 190

    # Opposite wheel notch up resets base to current value rather than old target
    vbar.setValue(100)
    event3 = make_wheel_event(angle_y=120)
    scroller.eventFilter(table.viewport(), event3)
    assert scroller._v_target == 5  # 100 - 95


def test_smooth_scroll_shift_horizontal(qapp):
    table = QTableWidget(50, 50)
    table.resize(400, 300)
    table.show()
    qapp.processEvents()

    scroller = enable_smooth_scroll(table, step_size=80, duration=100)
    hbar = table.horizontalScrollBar()
    hbar.setRange(0, 1500)
    hbar.setValue(0)

    # Shift + vertical wheel rotates horizontally
    event = make_wheel_event(angle_y=-120, modifiers=Qt.ShiftModifier)
    consumed = scroller.eventFilter(table.viewport(), event)
    assert consumed is True
    assert scroller._h_target == 80
    assert scroller._h_anim.state() == QAbstractAnimation.Running


def test_smooth_scroll_trackpad_direct_passthrough(qapp):
    table = QTableWidget(100, 5)
    scroller = enable_smooth_scroll(table)
    vbar = table.verticalScrollBar()
    vbar.setRange(0, 1000)

    # Trackpad event has non-zero pixelDelta
    trackpad_event = make_wheel_event(angle_y=-30, pixel_y=-8)
    consumed = scroller.eventFilter(table.viewport(), trackpad_event)
    # Should not intercept pixelDelta events so Qt scrolls 1:1 natively
    assert consumed is False
    assert scroller._v_target is None


def test_user_interaction_interrupts_animation(qapp):
    table = QTableWidget(100, 5)
    table.resize(400, 300)
    table.show()
    scroller = enable_smooth_scroll(table)
    vbar = table.verticalScrollBar()
    vbar.setRange(0, 1000)

    # Start scroll animation
    event = make_wheel_event(angle_y=-120)
    scroller.eventFilter(table.viewport(), event)
    assert scroller._v_anim.state() == QAbstractAnimation.Running

    # Key press interrupts
    key_event = QKeyEvent(QEvent.KeyPress, Qt.Key_Down, Qt.NoModifier)
    scroller.eventFilter(table, key_event)
    assert scroller._v_anim.state() == QAbstractAnimation.Stopped
    assert scroller._v_target is None

    # Mouse press also interrupts
    scroller.eventFilter(table.viewport(), event)
    assert scroller._v_anim.state() == QAbstractAnimation.Running
    mouse_event = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(10, 10),
        QPointF(10, 10),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    scroller.eventFilter(table.viewport(), mouse_event)
    assert scroller._v_anim.state() == QAbstractAnimation.Stopped


def test_smooth_scroll_works_on_qlistwidget(qapp):
    list_widget = QListWidget()
    list_widget.addItems([f"Item {i}" for i in range(100)])
    scroller = enable_smooth_scroll(list_widget)
    assert list_widget.verticalScrollMode() == QAbstractItemView.ScrollPerPixel
    assert scroller is not None
