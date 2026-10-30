"""The desktop icon helper: real pixmaps, tinting, cache, safe misses."""
from darspack.ui import icons


def test_icon_renders_a_tinted_pixmap(qapp):
    icon = icons.icon("plus", "#e0a83c", 20)
    assert not icon.isNull()
    pixmap = icon.pixmap(20, 20)
    assert not pixmap.isNull()
    assert pixmap.width() >= 20


def test_icon_cache_reuses_the_pixmap(qapp):
    first = icons.tinted_pixmap("search", "#e9e6df", 18)
    second = icons.tinted_pixmap("search", "#e9e6df", 18)
    assert first.cacheKey() == second.cacheKey()


def test_missing_icon_is_empty(qapp):
    assert icons.icon("no-such-icon").isNull()


def test_icon_fills_and_centers_its_canvas(qapp):
    """The SVG must be rendered into the logical icon rect, not at its
    own default size — otherwise a 24 px drawing in an 18 px canvas is
    cropped at the edges."""
    from PySide6.QtGui import qAlpha

    pixmap = icons.tinted_pixmap("package", "#ffffff", 18)
    image = pixmap.toImage()
    # a correctly scaled Lucide icon keeps its ~2/24 viewBox margin, so
    # the outermost device-pixel border must stay transparent
    for x in range(image.width()):
        assert qAlpha(image.pixel(x, 0)) == 0
        assert qAlpha(image.pixel(x, image.height() - 1)) == 0
    for y in range(image.height()):
        assert qAlpha(image.pixel(0, y)) == 0
        assert qAlpha(image.pixel(image.width() - 1, y)) == 0
