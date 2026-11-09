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

from string import Template

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QComboBox, QMenu

from .. import asset_path

FONT_FAMILY = "Vazirmatn"
FONT_FALLBACK = "Segoe UI"

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
    "scroll": "#3a4150",
}

METRICS = {
    "control_height": 36,
    "row_height": 38,
    "radius": 8,
    "radius_card": 12,
}

_QSS = Template("""
* { font-family: "Vazirmatn", "Segoe UI"; }
QMainWindow, QDialog { background: $bg; }
QWidget { color: $text; }
QWidget#AppBar { background: $surface; border-bottom: 1px solid $border_soft; }
QWidget#FilterBar { background: $surface; border-bottom: 1px solid $border; }

QLabel { background: transparent; }
QLabel#BrandTitle { font-size: 15pt; font-weight: 700; }
QLabel#BrandSub { color: $muted; font-size: 9.5pt; }
QLabel#DialogTitle { font-size: 14pt; font-weight: 700; }
QLabel#DialogHint { color: $muted; font-size: 9.5pt; }
QLabel#Muted { color: $muted; }
QLabel#EmptyHint { color: $muted; font-size: 14px; }
QLabel#SuccessText { color: $success; }
QLabel#PinDigits {
    font-size: 30px; font-weight: 700; letter-spacing: 6px;
}
QLabel#WarnPill {
    background: $accent_soft; color: $accent_text; border-radius: 11px;
    padding: 3px 12px; font-weight: 600;
}
QPushButton#WarnPill {
    background: $accent_soft; color: $accent_text; border: none;
    border-radius: 11px; padding: 3px 12px; font-weight: 600;
}
QPushButton#WarnPill:hover { background: #4a3b1d; }

QFrame#BannerCard {
    background: $surface; border: 1px solid $border_soft;
    border-radius: $radius; padding: 12px 16px;
}
QFrame#BulkBar {
    background: $surface; border: 1px solid $border;
    border-radius: $radius; padding: 6px 12px;
}
QPushButton#BulkBtn {
    background: $surface_2; color: $text; border: 1px solid $border;
    border-radius: 6px; padding: 5px 12px; font-size: 9.5pt;
}
QPushButton#BulkBtn:hover {
    background: $surface_3; border-color: $accent; color: $accent_text;
}
QPushButton#BulkBtn:pressed { background: $primary; }

QLineEdit, QComboBox, QSpinBox, QTextEdit {
    background: $surface_2; border: 1px solid $border;
    border-radius: $radius; padding: 6px 10px; min-height: 20px;
    selection-background-color: $primary; selection-color: $text;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QTextEdit:focus {
    border: 1px solid $accent;
}
QFrame#SearchShell {
    background: $surface_2; border: 1px solid $border;
    border-radius: $radius;
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
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {
    color: $faint; background: $surface; border-color: $border_soft;
}
QComboBox {
    combobox-popup: 0;
}
QComboBoxPrivateContainer {
    background: transparent;
}
QComboBox::drop-down { border: 0; width: 24px; }
QComboBox QAbstractItemView {
    background: $surface_2; border: 1px solid $border;
    border-radius: $radius; padding: 4px; outline: 0;
    selection-background-color: $primary; selection-color: $text;
}
QSpinBox::up-button, QSpinBox::down-button {
    width: 18px; border: 0; background: transparent;
}
QCheckBox { spacing: 8px; }
QCheckBox::indicator, QAbstractItemView::indicator {
    width: 18px; height: 18px; border-radius: 5px;
    border: 1px solid $border; background: $surface_2;
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
QCheckBox:focus { color: $text; }
QTextEdit { padding: 8px 10px; }

QPushButton {
    background: $surface_2; color: $text; border: 1px solid $border;
    border-radius: $radius; padding: 7px 14px; min-height: 20px;
}
QPushButton:hover { background: $surface_3; }
QPushButton:pressed { background: $primary; }
QPushButton:disabled {
    background: $surface; color: $faint; border-color: $border_soft;
}
QPushButton:focus { border: 1px solid $accent; }
QPushButton#Primary {
    background: $accent; color: $on_accent; border: none;
    font-weight: 600; padding: 7px 16px;
}
QPushButton#Primary:hover { background: $accent_hover; }
QPushButton#Primary:pressed { background: $accent; }
QPushButton#Secondary {
    background: $surface_2; color: $text; border: 1px solid $border;
}
QPushButton#Secondary:hover { background: $surface_3; }
QPushButton#EmptyCta {
    background: $accent; color: $on_accent; border: none;
    font-weight: 600; padding: 8px 18px;
}
QPushButton#EmptyCta:hover { background: $accent_hover; }
QPushButton#Danger {
    background: transparent; color: $danger; border: 1px solid $danger;
}
QPushButton#Danger:hover { background: $danger_soft; }
QPushButton#Ghost {
    background: transparent; border: 1px solid $border; color: $muted;
}
QPushButton#Ghost:hover { background: $surface_2; color: $text; }
QPushButton#Star {
    background: transparent; border: none; padding: 0;
    font-size: 26px; color: $faint;
}
QPushButton#Star:hover { color: $muted; }
QPushButton#Star:checked { color: $accent; }

QToolButton {
    background: transparent; color: $text; border: 1px solid $border;
    border-radius: $radius; padding: 6px 12px; min-height: 20px;
}
QToolButton:hover { background: $surface_2; }
QToolButton:pressed { background: $primary; }
QToolButton:disabled { color: $faint; border-color: $border_soft; }
QToolButton::menu-indicator { image: none; }
QToolButton#IconGhost {
    border: none; padding: 6px 8px; color: $muted; font-size: 15px;
}
QToolButton#IconGhost:hover { background: $surface_2; color: $text; }

QMenu {
    background: $surface_2; border: 1px solid $border;
    border-radius: $radius; padding: 4px; min-width: 220px;
}
QMenu::item { padding: 8px 18px; border-radius: 6px; }
QMenu::item:selected { background: $primary; }
QMenu::item:disabled { color: $faint; }
QMenu::separator { height: 1px; background: $border; margin: 5px 8px; }

QTableWidget {
    background: $surface; alternate-background-color: $alt_row;
    border: 1px solid $border; border-radius: $radius;
    gridline-color: transparent; selection-background-color: $selection;
    selection-color: $text;
}
QTableWidget::item {
    padding: 0 10px; border-bottom: 1px solid $border_soft;
}
QTableWidget::item:selected { background: $selection; color: $text; }

QTableWidget QComboBox, QTableWidget QSpinBox, QTableWidget QLineEdit {
    background: $surface_2; border: 1px solid $border_soft;
    border-radius: 6px; padding: 3px 8px; min-height: 26px;
}
QTableWidget QComboBox:hover, QTableWidget QSpinBox:hover, QTableWidget QLineEdit:hover {
    border-color: $muted;
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
QScrollBar:horizontal {
    background: transparent; height: 10px; margin: 2px;
}
QScrollBar::handle:horizontal {
    background: $scroll; border-radius: 5px; min-width: 28px;
}
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QTabWidget::pane {
    border: 1px solid $border; border-radius: $radius; top: -1px;
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
}
QStatusBar::item { border: 0; }
QToolTip {
    background: $surface_2; color: $text; border: 1px solid $border;
    padding: 4px 8px;
}
""")


def load_fonts() -> str:
    """Register the bundled Vazirmatn weights; return the usable family.

    Falls back to Segoe UI if the files are missing so a damaged build
    still starts with readable Persian.
    """
    for weight in ("Regular", "Medium", "SemiBold", "Bold"):
        path = asset_path(f"fonts/Vazirmatn-{weight}.ttf")
        if path.is_file():
            QFontDatabase.addApplicationFont(str(path))
    families = set(QFontDatabase.families())
    return FONT_FAMILY if FONT_FAMILY in families else FONT_FALLBACK


def build_qss(palette: dict | None = None) -> str:
    """The whole stylesheet, with optional palette overrides."""
    values = dict(PALETTE)
    values.update(METRICS)
    values.update(palette or {})
    check_icon = asset_path("icons/check.svg")
    values["check_icon"] = str(check_icon).replace("\\", "/")
    return _QSS.substitute(values)


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

_orig_menu_init = QMenu.__init__


def _patched_menu_init(self, *args, **kwargs):
    _orig_menu_init(self, *args, **kwargs)
    self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)


QMenu.__init__ = _patched_menu_init
