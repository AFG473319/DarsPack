"""Tinted Lucide icons (آیکون‌ها) for the desktop UI.

Lucide's SVGs use `currentColor`, which Qt's SVG renderer does not
resolve. Each icon is rendered once per (name, colour, size) and tinted
with SourceIn, then cached — no duplicate coloured SVG files.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from .. import asset_path
from .theme import PALETTE

_CACHE: dict = {}


def tinted_pixmap(name: str, color: str = None, size: int = 20,
                  ratio: float = 2.0) -> QPixmap:
    color = color or PALETTE["text"]
    key = (name, color, size, ratio)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    path = asset_path(f"icons/{name}.svg")
    if not path.is_file():
        return QPixmap()
    renderer = QSvgRenderer(str(path))
    if not renderer.isValid():
        return QPixmap()
    pixmap = QPixmap(int(size * ratio), int(size * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    # Render into the LOGICAL rect: without it the SVG keeps its own
    # 24 px default and is cropped when the requested size is smaller.
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    painter = QPainter(pixmap)
    painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
    painter.fillRect(pixmap.rect(), QColor(color))
    painter.end()
    _CACHE[key] = pixmap
    return pixmap


def icon(name: str, color: str = None, size: int = 20) -> QIcon:
    """A QIcon for `name` with matching disabled dim tint; empty when missing."""
    pixmap = tinted_pixmap(name, color, size)
    if pixmap.isNull():
        return QIcon()
    qicon = QIcon(pixmap)
    disabled = tinted_pixmap(name, PALETTE["faint"], size)
    if not disabled.isNull():
        qicon.addPixmap(disabled, QIcon.Mode.Disabled)
    return qicon
