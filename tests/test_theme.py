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


def test_table_has_no_single_cell_hover_patch():
    """`QTableWidget::item:hover` paints only the cell under the cursor,
    which looked like a stray coloured box in screenshots and in real
    use. Row selection is the meaningful state; no cell-level hover."""
    assert "QTableWidget::item:hover" not in theme.build_qss()


def test_menu_icon_spacing_and_border_in_qss():
    """QMenu items need explicit border styling and icon offset so icons don't
    collide with the curved hover highlight pill border."""
    qss = theme.build_qss()
    assert "QMenu::icon { left: 14px; }" in qss
    assert "border: 1px solid transparent;" in qss
    assert "min-width: 240px;" in qss

