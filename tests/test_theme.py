"""The visual system: brand tokens, legible contrast, bundled font, QSS."""
import contextlib

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


@contextlib.contextmanager
def _with_light_theme(qapp):
    """Context: switch to light, yield, restore dark (the default look)."""
    from darspack.ui import theme
    theme.apply_theme(qapp, "light")
    try:
        yield
    finally:
        theme.apply_theme(qapp, "dark")
    assert theme.PALETTE == theme.DARK_PALETTE


def test_light_palette_covers_every_dark_key():
    """A key present in dark but missing in light would leave a dark patch."""
    assert theme.LIGHT_PALETTE.keys() == theme.DARK_PALETTE.keys()
    assert theme.theme_overrides("dark") is theme.DARK_PALETTE
    assert theme.theme_overrides("light") is theme.LIGHT_PALETTE
    assert theme.theme_overrides("nonsense") is theme.DARK_PALETTE


def test_light_palette_contrast_passes_wcag():
    pairs = [
        ("text", "bg", 7.0),
        ("text", "surface", 7.0),
        ("muted", "bg", 4.5),
        ("text_on_primary", "primary", 4.5),
        ("on_accent", "accent", 4.5),
        ("accent_text", "accent_soft", 4.5),
        ("selection_text", "selection", 4.5),
        ("nav_active_text", "nav_active_bg", 4.5),
    ]
    palette = theme.LIGHT_PALETTE
    for foreground, background, minimum in pairs:
        ratio = _contrast(palette[foreground], palette[background])
        assert ratio >= minimum, f"{foreground}/{background}: {ratio:.2f}"


def test_brand_accents_survive_the_light_theme():
    """Navy and saffron stay as accents; only surfaces/text/borders flip."""
    for key in ("primary", "accent", "on_accent"):
        assert theme.LIGHT_PALETTE[key] == theme.PALETTE[key]


def test_dark_palette_definitions_do_not_drift():
    """The frozen dark snapshot must equal the literal PALETTE at import."""
    literal = {
        "bg": "#14161b", "surface": "#1a1d24", "surface_2": "#22262f",
        "surface_3": "#2a2f39", "header": "#1e222a", "alt_row": "#171a20",
        "border": "#2e3440", "border_soft": "#242932", "text": "#e9e6df",
        "muted": "#9aa0ab", "faint": "#6b7280", "primary": "#2d3f6e",
        "primary_hover": "#3a5290", "accent": "#e0a83c",
        "accent_hover": "#efb84f", "on_accent": "#1c1508",
        "accent_soft": "#3a2f18", "accent_text": "#f0c56a",
        "selection": "#2a3a63", "danger": "#d9736e", "danger_soft": "#3a2020",
        "success": "#8fd08f", "scroll": "#475166", "scroll_hover": "#5d6a82",
    }
    for key, value in literal.items():
        assert theme.DARK_PALETTE[key] == value, key


def test_apply_theme_switches_palette_qss_and_back(qapp):
    from darspack.ui import theme
    theme.apply_theme(qapp, "light")
    try:
        assert theme.active_theme() == "light"
        assert theme.PALETTE["nav_bg"] == theme.LIGHT_PALETTE["nav_bg"]
        qss = qapp.styleSheet()
        assert theme.LIGHT_PALETTE["nav_bg"] in qss
        assert theme.DARK_PALETTE["nav_bg"] not in qss
    finally:
        theme.apply_theme(qapp, "dark")
    assert theme.active_theme() == "dark"
    assert theme.PALETTE == theme.DARK_PALETTE
    assert theme.DARK_PALETTE["nav_bg"] in qapp.styleSheet()


def test_light_qss_has_no_dark_surfaces_left(qapp):
    with _with_light_theme(qapp):
        qss = theme.build_qss()
        # every dark-only surface/border/hover value must be gone
        for leftover in ("#141720", "#202634", "#323b4c", "#482323",
                         "#242a38", "#3a4457", "#7b8393", "#cfd4dc",
                         "#f6c453", "#3c495e"):
            assert leftover not in qss, leftover
        # selection stays a light navy tint with dark text
        assert theme.LIGHT_PALETTE["selection"] in qss
        assert theme.LIGHT_PALETTE["selection_text"] in qss


def test_kind_badges_follow_the_active_theme(qapp):
    from darspack.ui.delegates import (
        KIND_BADGES, KIND_BADGES_LIGHT, kind_badges)
    assert kind_badges() is KIND_BADGES
    with _with_light_theme(qapp):
        assert kind_badges() is KIND_BADGES_LIGHT
    assert kind_badges() is KIND_BADGES


def test_menu_painter_uses_the_live_palette(qapp):
    """The custom menu painter must follow the theme without rebuilds."""
    from PySide6.QtWidgets import QMenu
    menu = QMenu()
    menu.addAction("حذف")
    with _with_light_theme(qapp):
        theme._MenuStyler._paint_menu(menu)   # must not raise on light colours
    theme._MenuStyler._paint_menu(menu)

