"""Build the DarsPack icon assets from the two SVG masters.

    python installer/make_icon.py

Why a hand-written ICO packer instead of Pillow: PySide6 is already in
the stack, and the ICO container is a 6-byte header plus one 16-byte
directory entry per image. Adding Pillow (~3 MB) just to pack the frames
would break the project's dependency budget.

The small master is used only at 16/24 px; every other size renders the
full master.
"""
from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QIODevice, QRectF
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "src" / "darspack" / "assets" / "icon"
CLIENT = ROOT / "src" / "darspack" / "web" / "client"
MASTER = ASSETS / "darspack.svg"
SMALL = ASSETS / "darspack-small.svg"

PNG_SIZES = [1024, 512, 256, 128, 64, 48, 32, 24, 16]
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]
FAVICON_SIZES = [16, 32, 48]
PWA_SIZES = [192, 512]


def source_for(size: int) -> Path:
    return SMALL if size <= 24 else MASTER


def render(svg: Path, size: int) -> QImage:
    renderer = QSvgRenderer(str(svg))
    if not renderer.isValid():
        raise SystemExit(f"invalid SVG: {svg}")
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return image


def png_bytes(image: QImage) -> bytes:
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise SystemExit("PNG encode failed")
    data = bytes(buffer.data())
    buffer.close()
    return data


def bmp_entry(image: QImage) -> bytes:
    """One uncompressed 32-bit ICO image (BMP header + XOR + AND mask)."""
    image = image.convertToFormat(QImage.Format_ARGB32)
    width, height = image.width(), image.height()
    header = struct.pack(
        "<IiiHHIIiiII", 40, width, height * 2, 1, 32, 0,
        width * height * 4, 0, 0, 0, 0)
    xor = bytearray()
    for y in range(height - 1, -1, -1):
        for x in range(width):
            pixel = image.pixel(x, y)
            xor += bytes((
                pixel & 0xFF, (pixel >> 8) & 0xFF,
                (pixel >> 16) & 0xFF, (pixel >> 24) & 0xFF))
    stride = ((width + 31) // 32) * 4
    mask = bytearray(stride * height)
    for y in range(height):
        row = (height - 1 - y) * stride
        for x in range(width):
            if image.pixelColor(x, y).alpha() < 128:
                mask[row + (x >> 3)] |= 0x80 >> (x & 7)
    return header + bytes(xor) + bytes(mask)


def ico_bytes(images: list[tuple[int, QImage]]) -> bytes:
    # Windows accepts PNG-compressed frames in an ICO only at 256×256.
    # A PNG frame at any other size makes the taskbar fall back to its
    # generic window icon (found 2026-10-29: the 128 px frame was PNG).
    payloads = [
        (size, png_bytes(image) if size >= 256 else bmp_entry(image))
        for size, image in images
    ]
    offset = 6 + 16 * len(payloads)
    directory = bytearray(struct.pack("<HHH", 0, 1, len(payloads)))
    for size, data in payloads:
        dimension = 0 if size >= 256 else size
        directory += struct.pack(
            "<BBBBHHII", dimension, dimension, 0, 0, 1, 32,
            len(data), offset)
        offset += len(data)
    return bytes(directory) + b"".join(data for _, data in payloads)


def main() -> None:
    _app = QGuiApplication(sys.argv)   # QPainter needs a live GUI app

    for size in PNG_SIZES:
        image = render(source_for(size), size)
        target = ASSETS / f"darspack-{size}.png"
        if not image.save(str(target), "PNG"):
            raise SystemExit(f"could not write {target}")

    app_icon = ico_bytes([(size, render(source_for(size), size))
                          for size in ICO_SIZES])
    (ASSETS / "darspack.ico").write_bytes(app_icon)

    favicon = ico_bytes([(size, render(SMALL, size))
                         for size in FAVICON_SIZES])
    (CLIENT / "favicon.ico").write_bytes(favicon)

    # PWA install icons: a phone's manifest needs exact 192 and 512 px PNGs
    pwa_dir = CLIENT / "icons"
    pwa_dir.mkdir(exist_ok=True)
    for size in PWA_SIZES:
        image = render(MASTER, size)
        if not image.save(str(pwa_dir / f"icon-{size}.png"), "PNG"):
            raise SystemExit(f"could not write icon-{size}.png")

    print(f"wrote {len(PNG_SIZES)} PNGs, darspack.ico "
          f"({len(app_icon)} bytes), favicon.ico ({len(favicon)} bytes), "
          f"PWA icons {PWA_SIZES}")


if __name__ == "__main__":
    main()
