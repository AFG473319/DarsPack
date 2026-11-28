"""The visual system (سامانه‌ی ظاهر): one palette, one QSS, one font.

Every colour and size the UI uses lives here. Widgets never hard-code a
hex value; they use an objectName that the stylesheet paints. That keeps
the dark theme consistent and makes a future light theme a palette
swap instead of a hunt through the code.

The palette comes from the brand mark: navy #2d3f6e, cream #f6edda and
the saffron bookmark #e0a83c. Saffron is an accent only — white text on
it is 2.9:1, so primary buttons use dark text (8.5:1).
"""
from __future__ import annotations

import re
import sys
from string import Template

from PySide6.QtCore import QEvent, QObject, QRect, QRectF, Qt
from PySide6.QtGui import (
    QColor, QFontDatabase, QFontMetrics, QPainter, QPainterPath, QPalette, QPen,
)
from PySide6.QtWidgets import QApplication, QComboBox, QMenu

from .. import asset_path

FONT_FAMILY = "Vazirmatn"
# Segoe UI exists only on Windows; on Linux fall back to Noto Sans
# (Qt falls back further to the system default if that is missing too).
FONT_FALLBACK = "Segoe UI" if sys.platform == "win32" else "Noto Sans"

# The user-facing font size setting (Settings «اندازه‌ی قلم», 8–18 pt)
# drives every text size in the UI: the application font covers widgets
# without an explicit QSS size, and every hardcoded size below is written
# for the 10 pt base and scaled proportionally so titles stay bigger than
# body text and captions stay smaller at any setting.
BASE_FONT_SIZE = 10
FONT_SIZE_MIN = 8
FONT_SIZE_MAX = 18

PALETTE = {
    "bg": "#14161b",
    "surface": "#1a1d24",
    "surface_2": "#22262f",
    "surface_3": "#2a2f39",
    "header": "#1e222a",
    "alt_row": "#171a20",
    "border": "#2e3440",
    "border_soft": "#242932",
    "text": "#e9e6df",
    "muted": "#9aa0ab",
    "faint": "#6b7280",
    "primary": "#2d3f6e",
    "primary_hover": "#3a5290",
    "accent": "#e0a83c",
    "accent_hover": "#efb84f",
    "on_accent": "#1c1508",
    "accent_soft": "#3a2f18",
    "accent_text": "#f0c56a",
    "selection": "#2a3a63",
    "danger": "#d9736e",
    "danger_soft": "#3a2020",
    "success": "#8fd08f",
    "scroll": "#475166",
    "scroll_hover": "#5d6a82",
}

METRICS = {
    "control_height": 36,
    "row_height": 38,
    "radius": 8,
    "radius_card": 12,
}

_QSS = Template("""
* { font-family: "Vazirmatn", "Segoe UI Variable", "Segoe UI"; }
QMainWindow, QDialog { background: $bg; }
QWidget { color: $text; }
QWidget#AppBar { background: $surface; border-bottom: 1px solid rgba(255, 255, 255, 0.06); }
QWidget#FilterBar { background: transparent; border: none; }

/* Fluent Windows 11 Navigation Rail */
QWidget#NavRail {
    background: #141720;
    border-left: 1px solid rgba(255, 255, 255, 0.05);
}
QToolButton#NavItem {
    background: transparent;
    color: #cfd4dc;
    border: 1px solid transparent;
    border-radius: 7px;
    padding: 6px 16px;
    font-size: 9.5pt;
    font-weight: 500;
    text-align: right;
}
QToolButton#NavItem:hover {
    background: #1d2330;
    color: #ffffff;
    border: 1px solid #2b3446;
}
QToolButton#NavItem:pressed {
    background: #181d28;
}
QToolButton#NavItem[active="true"] {
    background: #202634;
    color: #ffffff;
    font-weight: 600;
    border: 1px solid #2e384b;
}
QToolButton#NavItem[active="true"]:hover {
    background: #252c3c;
    border: 1px solid #39455c;
}
QToolButton#NavItem:focus {
    border: 1px solid $accent;
}
QToolButton#NavItem[hasBadge="true"] {
    padding: $nav_badge_padding;
}
QFrame#NavIndicator {
    background: $accent;
    border: none;
    border-radius: 1px;
}
QLabel#NavSectionHeader {
    color: #7b8393;
    font-size: 8.5pt;
    font-weight: 700;
    padding: 12px 12px 4px 12px;
}
QLabel#NavBadge {
    background: rgba(230, 179, 77, 0.16);
    color: #f6c453;
    border-radius: 9px;
    padding: 0px 6px;
    font-size: 7.5pt;
    font-weight: 700;
    border: 1px solid rgba(230, 179, 77, 0.30);
}
QFrame#NavDivider {
    background: rgba(255, 255, 255, 0.07);
    max-height: 1px;
    margin: 8px 6px;
}

/* Fluent CommandBar & Page Header */
QWidget#CommandBar {
    background: $surface;
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}
QWidget#FilterBar QComboBox, QWidget#FilterBar QToolButton {
    min-height: 16px;
    padding: 3px 10px;
    font-size: 9pt;
}
QWidget#FilterBar QToolButton[hasDropdown="true"] {
    padding: $filter_dropdown_padding;
}
QWidget#FilterBar QToolButton#IconGhost {
    padding: 0px;
}
QLabel#PageTitle {
    font-size: 15pt;
    font-weight: 700;
}
QLabel#PageSubtitle {
    color: $muted;
    font-size: 9pt;
}

/* Fluent View Segment Buttons */
QToolButton#SegmentBtn {
    background: $surface_2;
    color: $muted;
    border: 1px solid $border;
    border-radius: 8px;
    padding: 4px 8px;
}
QToolButton#SegmentBtn:hover {
    background: #323b4c;
    border-color: #4a576e;
    color: #ffffff;
}
QToolButton#SegmentBtn[active="true"] {
    background: $primary;
    color: #ffffff;
    border-color: $primary_hover;
    font-weight: 600;
}
QToolButton#SegmentBtn:focus, QWidget#FilterBar QToolButton:focus {
    border: 1px solid $accent;
}
QFrame#SegmentGroup {
    background: $surface_2;
    border: 1px solid $border;
    border-radius: 8px;
}
QFrame#SegmentGroup QToolButton#SegmentBtn {
    background: transparent;
    border: none;
    border-radius: 6px;
}
QFrame#SegmentGroup QToolButton#SegmentBtn:hover {
    background: #2c3547;
}
QFrame#SegmentGroup QToolButton#SegmentBtn[active="true"] {
    background: $primary;
    color: #ffffff;
}

/* Fluent InfoBar Banner */
QFrame#InfoBar {
    background: $surface_2;
    border: 1px solid $border;
    border-right: 4px solid $accent;
    border-radius: 8px;
    padding: 6px 14px;
}
QFrame#InfoBar[type="success"] {
    border-right: 4px solid $success;
}
QLabel#InfoBarText {
    color: $text;
    font-size: 9.5pt;
}
QPushButton#InfoBarAction {
    background: $accent;
    color: $on_accent;
    border: none;
    border-radius: 6px;
    padding: 4px 12px;
    font-weight: 600;
    font-size: 9pt;
}
QPushButton#InfoBarAction:hover {
    background: $accent_hover;
}
QToolButton#InfoBarClose {
    background: transparent;
    border: none;
    border-radius: 4px;
    padding: 2px;
}
QToolButton#InfoBarClose:hover {
    background: $surface_3;
}

/* Fluent Filter Chips */
QPushButton#FilterChip {
    background: $surface_2;
    color: $muted;
    border: 1px solid $border_soft;
    border-radius: 13px;
    padding: 3px 12px;
    font-size: 9pt;
}
QPushButton#FilterChip:hover {
    background: #323b4c;
    color: #ffffff;
    border-color: #4a576e;
}
QPushButton#FilterChip[checked="true"] {
    background: $primary;
    color: #ffffff;
    border-color: $accent;
    font-weight: 600;
}

/* Fluent Cards Grid View */
QScrollArea#CardGridScroll {
    background: transparent;
    border: none;
}
QWidget#CardGridContainer {
    background: transparent;
}
QFrame#FileCard {
    background: $surface;
    border: 1px solid $border_soft;
    border-radius: 10px;
    padding: 10px 12px;
}
QFrame#FileCard:hover {
    background: $surface_2;
    border: 1px solid $border;
}
QFrame#FileCard[selected="true"] {
    background: $selection;
    border: 1px solid $accent;
}
QLabel#CardTitle {
    font-size: 9.5pt;
    font-weight: 600;
    color: $text;
}
QLabel#CardMeta {
    font-size: 8.5pt;
    color: $muted;
}
QLabel#CardKindChip {
    border-radius: 5px;
    padding: 2px 7px;
    font-size: 8pt;
    font-weight: 600;
}
QLabel#CardSubjChip {
    background: $surface_3;
    color: $text;
    border-radius: 5px;
    padding: 2px 7px;
    font-size: 8pt;
}

QLabel { background: transparent; }
QLabel#BrandTitle { font-size: 15pt; font-weight: 700; }
QLabel#BrandSub { color: $muted; font-size: 9.5pt; }
QLabel#DialogTitle { font-size: 14pt; font-weight: 700; }
QLabel#DialogHint { color: $muted; font-size: 9.5pt; }
QLabel#Counter { color: $muted; font-size: 8.5pt; }
QLabel#Muted { color: $muted; }
QLabel#EmptyHint { color: $muted; font-size: 10.5pt; }
QLabel#SuccessText { color: $success; }
QLabel#PinDigits {
    font-size: 22.5pt; font-weight: 700; letter-spacing: 6px;
}
QLabel#WarnPill {
    background: $accent_soft; color: $accent_text; border-radius: 11px;
    padding: 3px 12px; font-weight: 600;
}
QPushButton#WarnPill {
    background: rgba(230, 179, 77, 0.08);
    color: #f4c96b;
    border: 1px solid rgba(230, 179, 77, 0.24);
    border-radius: 9px;
    padding: 3px 11px;
    margin: 2px 0px;
    font-size: 8.5pt;
    font-weight: 500;
    min-height: 18px;
}
QPushButton#WarnPill:hover {
    background: rgba(230, 179, 77, 0.16);
    border-color: rgba(230, 179, 77, 0.45);
    color: #ffe094;
}

QFrame#BannerCard {
    background: $surface; border: 1px solid $border_soft;
    border-radius: $radius;
}
QFrame#StepCard {
    background: $surface_2; border: 1px solid $border_soft;
    border-radius: 8px;
}
QFrame#InfoCallout {
    background: rgba(224, 168, 60, 0.07);
    border: 1px solid rgba(224, 168, 60, 0.28);
    border-radius: 8px;
}
QFrame#SuccessCard {
    background: rgba(143, 208, 143, 0.08);
    border: 1px solid rgba(143, 208, 143, 0.35);
    border-radius: 8px;
}
QFrame#DangerCard {
    background: rgba(217, 115, 110, 0.09);
    border: 1px solid rgba(217, 115, 110, 0.40);
    border-radius: 8px;
}
QFrame#DropZone {
    background: $surface_2;
    border: 1.5px dashed #4a5870;
    border-radius: 10px;
}
QFrame#DropZone[dragActive="true"] {
    background: #232d42;
    border: 1.5px dashed $accent;
}
QFrame#SlideCard {
    background: $surface; border: 1px solid $border;
    border-radius: 10px;
}
QScrollArea, QScrollArea > QWidget#qt_scrollarea_viewport,
QScrollArea#TabScrollArea, QWidget#TabScrollViewport, QWidget#TabScrollContent {
    background: transparent;
    border: none;
}
QFrame#BulkBar {
    background: $surface; border: 1px solid $border;
    border-radius: $radius;
}
QPushButton#BulkBtn {
    background: $surface_2; color: $text; border: 1px solid $border;
    border-radius: 6px; padding: 5px 11px; font-size: 9.5pt;
}
QPushButton#BulkBtn:hover {
    background: #323b4c; border-color: #4d5d77; color: #ffffff;
}
QPushButton#BulkBtn:pressed { background: $primary; }
QPushButton#BulkBtn:focus { border: 1px solid $accent; }

QLineEdit, QComboBox, QSpinBox, QTextEdit {
    background: $surface_2; border: 1px solid $border;
    border-radius: $radius; padding: 6px 10px; min-height: 22px;
    selection-background-color: $primary; selection-color: $text;
}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QTextEdit:hover {
    border-color: #455269;
}
QLineEdit:read-only {
    background: $surface; color: $muted;
}
QComboBox QLineEdit, QSpinBox QLineEdit {
    padding: 0px; border: none; background: transparent; min-height: 0px;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QTextEdit:focus {
    border: 1px solid $accent;
}
QFrame#SearchShell {
    background: $surface_2; border: 1px solid $border;
    border-radius: 18px;
}
QFrame#SearchShell[focused="true"] { border: 1px solid $accent; }
QLineEdit#SearchField {
    background: transparent; border: none; padding: 0;
}
QLineEdit#SearchField:focus { border: none; }
QToolButton#SearchClear {
    border: none; background: transparent; padding: 0;
}
QToolButton#SearchClear:hover {
    background: $surface_3; border-radius: 6px;
}
QToolButton#SearchClear:focus {
    border: 1px solid $accent; border-radius: 6px;
}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {
    color: $faint; background: $surface; border-color: $border_soft;
}
QComboBox {
    combobox-popup: 0;
}
QComboBoxPrivateContainer {
    background: transparent;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: $combo_dropdown_pos;
    border: 0;
    width: 24px;
}
QComboBox::down-arrow {
    image: url("$chevron_down_icon");
    width: 14px;
    height: 14px;
}
QComboBox[emptyList="true"]::down-arrow { image: none; width: 0; height: 0; }
QComboBox[emptyList="true"]::drop-down { width: 4px; }
QComboBox QAbstractItemView {
    background: $surface_2; border: 1px solid $border;
    border-radius: $radius; padding: 4px; outline: 0;
    selection-background-color: $primary; selection-color: $text;
}
QSpinBox::up-button, QSpinBox::down-button {
    width: 18px; border: 0; background: transparent;
}
QSpinBox::up-arrow {
    image: url("$chevron_up_icon");
    width: 12px;
    height: 12px;
}
QSpinBox::down-arrow {
    image: url("$chevron_down_icon");
    width: 12px;
    height: 12px;
}
QCheckBox { spacing: 8px; }
QCheckBox::indicator, QAbstractItemView::indicator {
    width: 18px; height: 18px; border-radius: 5px;
    border: 1px solid #4d5669; background: $surface_2;
}
QCheckBox::indicator:hover, QAbstractItemView::indicator:hover {
    border-color: $muted;
}
QCheckBox::indicator:checked, QAbstractItemView::indicator:checked {
    background: $accent; border: 1px solid $accent;
    image: url($check_icon);
}
QCheckBox::indicator:checked:hover, QAbstractItemView::indicator:checked:hover {
    background: $accent_hover; border: 1px solid $accent_hover;
}
QCheckBox::indicator:disabled, QAbstractItemView::indicator:disabled {
    border-color: $border_soft; background: $surface;
}
QCheckBox:focus::indicator {
    border-color: $accent;
}
QCheckBox:focus { color: $text; }
QTextEdit { padding: 8px 10px; }

QPushButton {
    background: $surface_2; color: $text; border: 1px solid $border;
    border-radius: $radius; padding: 7px 14px; min-height: 20px;
}
QPushButton:hover {
    background: #323b4c;
    border: 1px solid #4d5d77;
    color: #ffffff;
}
QPushButton:pressed { background: $primary; }
QPushButton:disabled {
    background: $surface; color: $faint; border-color: $border_soft;
}
QPushButton:focus { border: 1px solid $accent; }
QPushButton#Primary {
    background: $accent; color: $on_accent; border: 1px solid transparent;
    font-weight: 600; padding: 7px 16px;
}
QPushButton#Primary:hover {
    background: $accent_hover;
    border: 1px solid #ffd875;
}
QPushButton#Primary:pressed { background: $accent; }
QPushButton#Primary:focus { border: 1px solid #ffffff; }
QPushButton#Secondary {
    background: $surface_2; color: $text; border: 1px solid $border;
}
QPushButton#Secondary:hover {
    background: #323b4c;
    border: 1px solid #4d5d77;
    color: #ffffff;
}
QPushButton#Secondary:focus { border: 1px solid $accent; }
QPushButton#EmptyCta {
    background: $accent; color: $on_accent; border: none;
    font-weight: 600; padding: 8px 18px;
}
QPushButton#EmptyCta:hover {
    background: $accent_hover;
    border: 1px solid #ffd875;
}
QPushButton#EmptyCta:focus { border: 1px solid #ffffff; }
QPushButton#Danger {
    background: transparent; color: $danger; border: 1px solid $danger;
}
QPushButton#Danger:hover {
    background: #482323;
    border: 1px solid #e58782;
    color: #ffffff;
}
QPushButton#Danger:disabled {
    background: transparent; color: $faint; border-color: $border_soft;
}
QPushButton#Danger:focus { border: 1px solid #ff9d96; }
QPushButton#Ghost {
    background: transparent; border: 1px solid $border; color: $muted;
}
QPushButton#Ghost:hover {
    background: #283140;
    border: 1px solid #455269;
    color: #ffffff;
}
QPushButton#Ghost:focus { border: 1px solid $accent; color: $text; }
QPushButton#Star {
    background: transparent; border: 1px solid transparent; padding: 0;
    border-radius: 8px; color: transparent; font-size: 1px;
}
QPushButton#Star:hover {
    background: #252b36;
    border: 1px solid #3c495e;
}

QToolButton {
    background: transparent; color: $text; border: 1px solid $border;
    border-radius: $radius; padding: 6px 12px; min-height: 20px;
}
QToolButton:hover {
    background: #323b4c;
    border: 1px solid #4d5d77;
    color: #ffffff;
}
QToolButton:pressed { background: $primary; }
QToolButton:disabled { color: $faint; border-color: $border_soft; }
QToolButton::menu-indicator {
    image: none;
    width: 0px;
    height: 0px;
    margin: 0px;
    padding: 0px;
}
QToolButton[hasDropdown="true"]::menu-indicator {
    image: none;
    width: 0px;
    height: 0px;
}
QToolButton#IconGhost {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 0px;
    margin: 0px;
    color: $muted;
}
QToolButton#IconGhost:hover {
    background: #2a3444;
    border: 1px solid #4a5870;
    color: #ffffff;
}
QToolButton#IconGhost:pressed {
    background: #1e2532;
    border: 1px solid #3c495e;
}
QToolButton#IconGhost:focus {
    border: 1px solid $accent;
}

QMenu {
    background: $surface_2;
    border: 1px solid #3c495e;
    border-radius: 8px;
    padding: 4px 4px;
    min-width: 240px;
}
QMenu::item {
    border: 1px solid transparent;
    padding: $menu_item_padding;
    margin: 1px 4px;
    border-radius: 6px;
    min-width: 140px;
    color: $text;
}
QMenu::icon {
    left: 14px;
}
QMenu::item:selected {
    background: #323b4c;
    border-color: #4a5870;
    color: #ffffff;
}
QMenu::item:disabled {
    color: $faint;
}
QMenu::item:disabled:selected {
    background: transparent;
    border-color: transparent;
    color: $faint;
}
QMenu::separator {
    height: 1px;
    background: rgba(255, 255, 255, 0.08);
    margin: 4px 8px;
}

QTableWidget {
    background: $surface;
    alternate-background-color: $alt_row;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 8px;
    gridline-color: transparent;
    selection-background-color: $selection;
    selection-color: $text;
}
QTableWidget::item {
    padding: 0 10px; border-bottom: 1px solid $border_soft;
}
QTableWidget#InlineEditTable::item {
    padding: 0 3px;
}
QTableWidget::item:selected { background: $selection; color: $text; }

QTableWidget QComboBox, QTableWidget QSpinBox, QTableWidget QLineEdit {
    background: $surface_2; border: 1px solid $border;
    border-radius: 6px; padding: 2px 8px; min-height: 20px; font-size: 9.5pt;
}
QTableWidget QComboBox:hover, QTableWidget QSpinBox:hover, QTableWidget QLineEdit:hover {
    border-color: #4a5870;
}
QTableWidget QComboBox:focus, QTableWidget QSpinBox:focus, QTableWidget QLineEdit:focus {
    border-color: $accent; background: $surface_3;
}

QHeaderView {
    background: $header; border: none;
}
QHeaderView::section {
    background: $header; color: $muted; padding: 9px 10px;
    border: none; border-bottom: 1px solid $border; font-weight: 600;
}
QHeaderView::section:first {
    $header_first_radius
}
QHeaderView::section:last {
    $header_last_radius
}
QHeaderView::section:vertical {
    background: $header; color: $muted; border: none; border-left: 1px solid $border;
}
QTableCornerButton::section { background: $header; border: none; }
QAbstractScrollArea::corner { background: $surface; border: none; }

QScrollBar:vertical {
    background: transparent; width: 10px; margin: 2px;
}
QScrollBar::handle:vertical {
    background: $scroll; border-radius: 5px; min-height: 28px;
}
QScrollBar::handle:vertical:hover {
    background: $scroll_hover;
}
QScrollBar:horizontal {
    background: transparent; height: 10px; margin: 2px;
}
QScrollBar::handle:horizontal {
    background: $scroll; border-radius: 5px; min-width: 28px;
}
QScrollBar::handle:horizontal:hover {
    background: $scroll_hover;
}
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QTabWidget::pane {
    border: none; border-top: 1px solid $border; border-radius: 0px;
}
QTabBar::tab {
    background: transparent; color: $muted; padding: 8px 14px;
    border-bottom: 2px solid transparent;
}
QTabBar::tab:selected { color: $text; border-bottom: 2px solid $accent; }
QTabBar::tab:hover { color: $text; }

QListWidget {
    background: $surface; border: 1px solid $border; border-radius: $radius;
}
QListWidget::item { padding: 8px; border-bottom: 1px solid $border_soft; }
QListWidget::item:selected { background: $selection; }

QProgressBar {
    background: $surface_2; border: none; border-radius: 4px;
}
QProgressBar::chunk { background: $accent; border-radius: 4px; }

QStatusBar {
    background: $surface; border-top: 1px solid $border; color: $muted;
    min-height: 34px; padding: 4px 20px;
}
QStatusBar::item { border: 0; }
QToolTip {
    background: $surface_2; color: $text; border: 1px solid $border;
    padding: 4px 8px;
}
""")


def load_fonts() -> str:
    """Register the bundled Vazirmatn weights; return the usable family.

    Falls back to Segoe UI on Windows (Noto Sans on Linux) if the files
    are missing so a damaged build still starts with readable Persian.
    """
    for weight in ("Regular", "Medium", "SemiBold", "Bold"):
        path = asset_path(f"fonts/Vazirmatn-{weight}.ttf")
        if path.is_file():
            QFontDatabase.addApplicationFont(str(path))
    families = set(QFontDatabase.families())
    return FONT_FAMILY if FONT_FAMILY in families else FONT_FALLBACK


def current_font_size(app: QApplication | None = None) -> float:
    """The size the application font is set to — the user's setting.

    Falls back to BASE_FONT_SIZE before any apply_font_size() has run
    (early widget construction, plain tests) or when the platform font
    sits outside the settings range.
    """
    app = app or QApplication.instance()
    size = app.font().pointSize() if app is not None else -1
    if not FONT_SIZE_MIN <= size <= FONT_SIZE_MAX:
        return float(BASE_FONT_SIZE)
    return float(size)


def font_scale(font_size: float | None = None) -> float:
    """Multiplier mapping every hardcoded size onto the user's setting.

    All sizes in the stylesheet and the one-off inline styles are written
    for the 10 pt default; scaling them by setting / base keeps the
    relative hierarchy (titles > body > captions) at any font size.
    Without an explicit size the base scale (1.0) is returned — callers
    that follow the live setting use scaled_px()/scaled_int() instead.
    """
    size = BASE_FONT_SIZE if font_size is None else float(font_size)
    if not FONT_SIZE_MIN <= size <= FONT_SIZE_MAX:
        size = float(BASE_FONT_SIZE)
    return size / BASE_FONT_SIZE


def scaled_px(px: float, font_size: float | None = None) -> str:
    """A one-off QSS size in px, scaled like the fonts around it.

    Follows the application font (the user's setting) unless an explicit
    size is passed.
    """
    if font_size is None:
        font_size = current_font_size()
    return f"{px * font_scale(font_size):g}px"


def scaled_int(value: int, font_size: float | None = None) -> int:
    """A pixel height/width sized for the default font, grown for larger
    settings so scaled-up text never clips (never shrunk below the
    comfortable default for settings under the base size).

    Follows the application font (the user's setting) unless an explicit
    size is passed.
    """
    if font_size is None:
        font_size = current_font_size()
    scale = font_scale(font_size)
    if scale <= 1.0:
        return value
    return max(value, round(value * scale))


_FONT_SIZE_RE = re.compile(r"(font-size:\s*)(\d+(?:\.\d+)?)pt\b")


def build_qss(palette: dict | None = None, font_size: float | None = None) -> str:
    """The whole stylesheet, with optional palette overrides.

    `font_size` (the user's setting) scales every font-size in the sheet
    proportionally: an explicit QSS size overrides the application font,
    so scaling the sheet is what makes the setting reach the nav rail,
    titles, chips, dialogs — the whole UI, not just plain widgets.
    """
    values = dict(PALETTE)
    values.update(METRICS)
    values.update(palette or {})
    check_icon = asset_path("icons/check.svg")
    values["check_icon"] = str(check_icon).replace("\\", "/")
    chevron_down_icon = asset_path("icons/chevron-down-muted.svg")
    values["chevron_down_icon"] = str(chevron_down_icon).replace("\\", "/")
    chevron_up_icon = asset_path("icons/chevron-up-muted.svg")
    values["chevron_up_icon"] = str(chevron_up_icon).replace("\\", "/")
    try:
        from .. import i18n
        is_fa = (i18n.language() == "fa")
    except Exception:
        is_fa = True
    values["menu_item_padding"] = "6px 14px 6px 14px" if is_fa else "6px 32px 6px 14px"
    values["nav_badge_padding"] = "6px 16px 6px 38px" if is_fa else "6px 38px 6px 16px"
    values["filter_dropdown_padding"] = "3px 10px 3px 26px" if is_fa else "3px 26px 3px 10px"
    values["combo_dropdown_pos"] = "center right"
    values["header_first_radius"] = (
        "border-top-right-radius: 7px;" if is_fa else "border-top-left-radius: 7px;"
    )
    values["header_last_radius"] = (
        "border-top-left-radius: 7px;" if is_fa else "border-top-right-radius: 7px;"
    )
    qss = _QSS.substitute(values)
    scale = font_scale(font_size)
    if scale != 1.0:
        qss = _FONT_SIZE_RE.sub(
            lambda m: f"{m.group(1)}{float(m.group(2)) * scale:g}pt", qss)
    return qss


def apply_palette(app) -> None:
    """Apply dark palette roles that QSS does not cover (e.g. PlaceholderText)."""
    pal = app.palette()
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor("#8e95a2"))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(PALETTE["selection"]))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(PALETTE["text"]))
    app.setPalette(pal)


def setup_combobox(combo: QComboBox) -> None:
    """Ensure the combobox popup container is translucent and frameless,
    preventing any un-rounded rectangular background artifact from showing
    behind the rounded dropdown menu."""
    container = combo.view().parentWidget()
    if container is not None:
        container.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        container.setWindowFlags(
            Qt.WindowType.Popup
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )


_orig_combo_init = QComboBox.__init__


def _patched_combo_init(self, *args, **kwargs):
    _orig_combo_init(self, *args, **kwargs)
    setup_combobox(self)


QComboBox.__init__ = _patched_combo_init

_orig_combo_set_view = QComboBox.setView


def _patched_combo_set_view(self, view):
    _orig_combo_set_view(self, view)
    setup_combobox(self)


QComboBox.setView = _patched_combo_set_view

def _action_parts(action) -> tuple[str, str]:
    """Split a QAction label and its tab-separated / key-sequence shortcut."""
    raw = (action.text() or "").replace("&", "")
    parts = raw.split("\t", 1)
    label = parts[0].strip()
    shortcut = parts[1].strip() if len(parts) > 1 else ""
    if not shortcut and not action.shortcut().isEmpty():
        shortcut = action.shortcut().toString()
    return label, shortcut


def _menu_layout_width(menu: QMenu) -> int:
    """Compute a balanced menu width for tight icon-text gaps and shortcuts."""
    fm = QFontMetrics(menu.font())
    visible = [a for a in menu.actions() if a.isVisible() and not a.isSeparator()]
    has_icons = any(not a.icon().isNull() for a in visible)
    max_label = max((fm.horizontalAdvance(_action_parts(a)[0]) for a in visible), default=0)
    max_sc = max((fm.horizontalAdvance(_action_parts(a)[1]) for a in visible), default=0)
    w = 34 + max_label
    if has_icons:
        w += 16 + 9
    if max_sc:
        w += 24 + max_sc
    return max(168, w)


class _MenuStyler(QObject):
    """Paint QMenu panels, tight icon-text gaps, hover pills, and aligned shortcuts."""

    def eventFilter(self, obj, event) -> bool:
        if isinstance(obj, QMenu):
            etype = event.type()
            if etype == QEvent.Show:
                if obj.property("_dp_base_min_w") is None:
                    obj.setProperty("_dp_base_min_w", obj.minimumWidth())
                base_min = int(obj.property("_dp_base_min_w") or 0)
                obj.setMinimumWidth(0)
                obj.setMaximumWidth(16777215)
                obj.ensurePolished()
                w = max(base_min, _menu_layout_width(obj), obj.sizeHint().width())
                obj.setFixedWidth(w)
                obj.adjustSize()
            elif etype == QEvent.Paint:
                self._paint_menu(obj)
                return True
        return False

    @staticmethod
    def _paint_menu(menu: QMenu) -> None:
        painter = QPainter(menu)
        painter.setRenderHint(QPainter.Antialiasing)

        bg_rect = QRectF(menu.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(bg_rect, 8, 8)
        painter.fillPath(path, QColor(PALETTE["surface_2"]))
        painter.setPen(QPen(QColor("#3c495e"), 1))
        painter.drawPath(path)

        rtl = menu.layoutDirection() == Qt.RightToLeft
        visible = [a for a in menu.actions() if a.isVisible()]
        has_icons = any((not a.isSeparator()) and (not a.icon().isNull()) for a in visible)
        active = menu.activeAction()

        painter.setFont(menu.font())
        icon_size = 16
        icon_gap = 9

        for act in visible:
            rect = menu.actionGeometry(act)
            if not rect.isValid():
                continue
            if act.isSeparator():
                y = rect.center().y()
                painter.setPen(QPen(QColor(255, 255, 255, 22), 1))
                painter.drawLine(rect.left() + 10, y, rect.right() - 10, y)
                continue

            enabled = act.isEnabled()
            hovered = enabled and (act is active)

            pill = rect.adjusted(6, 1, -6, -1)
            if hovered:
                painter.setBrush(QColor("#323b4c"))
                painter.setPen(QPen(QColor("#4a5870"), 1))
                painter.drawRoundedRect(QRectF(pill).adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)

            content = pill.adjusted(10, 0, -10, 0)
            if has_icons:
                if rtl:
                    icon_rect = QRect(
                        content.right() - icon_size + 1,
                        content.center().y() - icon_size // 2,
                        icon_size, icon_size,
                    )
                    text_left = content.left()
                    text_right = icon_rect.left() - icon_gap
                else:
                    icon_rect = QRect(
                        content.left(),
                        content.center().y() - icon_size // 2,
                        icon_size, icon_size,
                    )
                    text_left = icon_rect.right() + 1 + icon_gap
                    text_right = content.right()
                if not act.icon().isNull():
                    mode = act.icon().Mode.Normal if enabled else act.icon().Mode.Disabled
                    act.icon().paint(painter, icon_rect, Qt.AlignCenter, mode)
            else:
                text_left = content.left()
                text_right = content.right()

            label, shortcut = _action_parts(act)
            text_rect = QRect(
                text_left, content.top(),
                max(20, text_right - text_left + 1), content.height(),
            )
            fg = (
                QColor("#ffffff") if hovered
                else QColor(PALETTE["text"] if enabled else PALETTE["faint"])
            )
            painter.setPen(fg)
            label_align = (
                (Qt.AlignRight if rtl else Qt.AlignLeft)
                | Qt.AlignAbsolute
                | Qt.AlignVCenter
            )
            painter.drawText(text_rect, label_align, label)

            if shortcut:
                sc_color = (
                    QColor("#d0d7e3") if hovered
                    else QColor(PALETTE["muted"] if enabled else PALETTE["faint"])
                )
                painter.setPen(sc_color)
                # Explicit physical outer alignment so narrow keys like Del
                # share the same outer edge as Ctrl+Z / Ctrl+A.
                sc_align = (
                    (Qt.AlignLeft if rtl else Qt.AlignRight)
                    | Qt.AlignAbsolute
                    | Qt.AlignVCenter
                )
                painter.drawText(text_rect, sc_align, shortcut)

        painter.end()


def apply_menu_style(menu: QMenu) -> QMenu:
    """Attach translucent framing and custom item painting to any QMenu,
    including C++-constructed menus such as QLineEdit.createStandardContextMenu."""
    # FramelessWindowHint + NoDropShadowWindowHint are required on Windows so
    # Qt enables WS_EX_LAYERED for WA_TranslucentBackground (preventing black corners).
    menu.setWindowFlags(
        Qt.WindowType.Popup
        | Qt.WindowType.FramelessWindowHint
        | Qt.WindowType.NoDropShadowWindowHint
    )
    menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    if not menu.property("_dp_menu_styled"):
        menu.setProperty("_dp_menu_styled", True)
        menu.setStyleSheet(
            "QMenu { min-width: 0px; } "
            "QMenu::item { min-width: 0px; padding: 6px 12px; }"
        )
        menu._menu_styler = _MenuStyler(menu)
        menu.installEventFilter(menu._menu_styler)
    return menu


_orig_menu_init = QMenu.__init__


def _patched_menu_init(self, *args, **kwargs):
    _orig_menu_init(self, *args, **kwargs)
    apply_menu_style(self)


QMenu.__init__ = _patched_menu_init
