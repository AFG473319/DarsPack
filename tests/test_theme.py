"""The visual system: brand tokens, legible contrast, bundled font, QSS."""
from darspack.ui import theme


def _relative_luminance(hex_color: str) -> float:
    value = hex_color.lstrip("#")
    channels = [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
              for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(a: str, b: str) -> float:
    high, low = sorted((_relative_luminance(a), _relative_luminance(b)),
                       reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_palette_contrast_passes_wcag():
    """Text pairs used in the UI must stay legible — the saffron accent
    is deliberately paired with dark text (white on saffron is 2.9:1)."""
    pairs = [
        ("text", "bg", 7.0),
        ("text", "surface", 7.0),
        ("muted", "bg", 4.5),
        ("text", "primary", 4.5),
        ("on_accent", "accent", 4.5),
        ("accent_text", "accent_soft", 4.5),
    ]
    palette = theme.PALETTE
    for foreground, background, minimum in pairs:
        ratio = _contrast(palette[foreground], palette[background])
        assert ratio >= minimum, f"{foreground}/{background}: {ratio:.2f}"


def test_vazirmatn_loads(qapp):
    assert theme.load_fonts() == "Vazirmatn"


def test_qss_covers_the_shared_widgets():
    qss = theme.build_qss()
    for selector in (
            "QMainWindow", "QDialog", "QLineEdit", "QComboBox", "QSpinBox",
            "QPushButton#Primary", "QPushButton#Secondary",
            "QPushButton#Danger", "QToolButton", "QMenu", "QTableWidget",
            "QHeaderView::section", "QScrollBar:vertical", "QTabBar::tab",
            "QProgressBar", "QStatusBar", "QToolTip"):
        assert selector in qss, f"missing style for {selector}"


def test_metrics_stay_on_the_4px_grid():
    metrics = theme.METRICS
    assert metrics["control_height"] % 2 == 0
    assert metrics["row_height"] >= metrics["control_height"]
    assert metrics["radius"] == 8


def test_qss_font_sizes_follow_the_setting():
    """Every QSS font-size scales with the setting so one setting drives
    the whole UI: an explicit QSS size would otherwise override the app
    font and leave styled widgets (nav rail, titles, chips) fixed."""
    base = theme.build_qss()
    big = theme.build_qss(font_size=18)
    small = theme.build_qss(font_size=8)
    assert "font-size: 9.5pt" in base          # unchanged at the default
    assert "font-size: 17.1pt" in big          # 9.5 * 1.8
    assert "font-size: 7.6pt" in small         # 9.5 * 0.8
    # The hierarchy survives scaling: dialog title > nav item > nav badge.
    assert "font-size: 25.2pt" in big and "font-size: 13.5pt" in big


def test_scaled_int_grows_only_for_larger_fonts():
    """Fixed chrome dimensions floor at their default so settings below
    10 pt never shrink the layout, and grow proportionally above it."""
    assert theme.scaled_int(38, 10) == 38
    assert theme.scaled_int(38, 8) == 38
    assert theme.scaled_int(38, 18) == 68      # Vazirmatn 18pt is 38px tall
    assert theme.scaled_int(210, 18) == 378    # nav rail


def test_table_has_no_single_cell_hover_patch():
    """`QTableWidget::item:hover` paints only the cell under the cursor,
    which looked like a stray coloured box in screenshots and in real
    use. Row selection is the meaningful state; no cell-level hover."""
    assert "QTableWidget::item:hover" not in theme.build_qss()


def test_menu_icon_spacing_and_border_in_qss():
    """QMenu items need explicit border styling and icon offset so icons don't
    collide with the curved hover highlight pill border."""
    qss = theme.build_qss()
    assert "QMenu::icon" in qss
    assert "left: 14px" in qss
    assert "border: 1px solid transparent;" in qss
    assert "min-width: 240px;" in qss


def test_combobox_popup_drop_down_in_qss():
    """`combobox-popup: 0` prevents Fusion style from injecting top/bottom
    spacers into the popup container."""
    qss = theme.build_qss()
    assert "combobox-popup: 0" in qss


def test_combobox_and_menu_popup_translucent(qapp):
    """Combobox popup containers and menus must have translucent backgrounds
    and frameless window flags so no square opaque box shows behind the
    rounded corners."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QComboBox, QMenu

    combo = QComboBox()
    container = combo.view().parentWidget()
    assert container is not None
    assert container.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    flags = container.windowFlags()
    assert bool(flags & Qt.WindowType.FramelessWindowHint)
    assert bool(flags & Qt.WindowType.Popup)

    menu = QMenu()
    assert menu.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    menu_flags = menu.windowFlags()
    assert bool(menu_flags & Qt.WindowType.FramelessWindowHint)
    assert bool(menu_flags & Qt.WindowType.NoDropShadowWindowHint)
    assert bool(menu_flags & Qt.WindowType.Popup)


def test_menu_fit_width_and_styled_standard_context_menu(qapp):
    """Menus must keep frameless translucent popup flags and fit all Persian
    labels and shortcuts inside the menu width without clipping."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLineEdit, QMenu
    from darspack.ui.theme import apply_menu_style

    menu = QMenu()
    menu.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    act1 = menu.addAction("خروجی بسته‌ی درس‌پک...")
    act2 = menu.addAction("باز کردن فایل")
    act2.setShortcut("Enter")
    act3 = menu.addAction("بازگردانی")
    act3.setShortcut("Ctrl+Z")

    try:
        menu.show()
        qapp.processEvents()
        for act in (act1, act2, act3):
            geom = menu.actionGeometry(act)
            assert geom.right() < menu.width()
    finally:
        menu.close()

    edit = QLineEdit("سلام")
    std_menu = edit.createStandardContextMenu()
    apply_menu_style(std_menu)
    assert std_menu.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    std_flags = std_menu.windowFlags()
    assert bool(std_flags & Qt.WindowType.Popup)
    assert bool(std_flags & Qt.WindowType.FramelessWindowHint)
    assert bool(std_flags & Qt.WindowType.NoDropShadowWindowHint)


def test_apply_palette_sets_placeholder_highlight_roles(qapp):
    from PySide6.QtGui import QColor, QPalette

    from darspack.ui import theme
    original = qapp.palette()
    try:
        theme.apply_palette(qapp)
        assert qapp.palette().color(
            QPalette.ColorRole.PlaceholderText) == QColor("#8e95a2")
        assert qapp.palette().color(
            QPalette.ColorRole.Highlight) == QColor(theme.PALETTE["selection"])
        assert qapp.palette().color(
            QPalette.ColorRole.HighlightedText) == QColor(theme.PALETTE["text"])
    finally:
        qapp.setPalette(original)

