"""The icon assets must stay loadable after every regeneration."""
import struct

from darspack import asset_path
from darspack.web import server as web_server


def test_svg_masters_parse(qapp):
    from PySide6.QtSvg import QSvgRenderer
    for name in ("darspack.svg", "darspack-small.svg"):
        assert QSvgRenderer(str(asset_path(f"icon/{name}"))).isValid()


def test_ico_carries_windows_sizes(qapp):
    from PySide6.QtGui import QIcon
    icon = QIcon(str(asset_path("icon/darspack.ico")))
    assert not icon.isNull()
    sizes = {(s.width(), s.height()) for s in icon.availableSizes()}
    assert {(16, 16), (24, 24), (32, 32), (48, 48), (256, 256)} <= sizes


def test_ico_png_frames_only_at_256():
    """Windows reads a PNG-compressed ICO frame only at 256×256. A PNG
    frame at another size makes the taskbar show its generic icon even
    though Qt and Explorer can still render the file."""
    data = asset_path("icon/darspack.ico").read_bytes()
    count = struct.unpack_from("<HHH", data, 0)[2]
    for i in range(count):
        w, h, _, _, _, _, size, offset = struct.unpack_from(
            "<BBBBHHII", data, 6 + i * 16)
        frame = data[offset:offset + size]
        if frame.startswith(b"\x89PNG\r\n\x1a\n"):
            assert (w or 256) == 256, f"PNG frame at {w or 256} px"



def test_web_client_has_favicon():
    assert (web_server.CLIENT_DIR / "favicon.ico").is_file()


def test_vazirmatn_weights_are_bundled(qapp):
    """The Persian-first UI ships its own typeface: four static weights
    plus the OFL licence. Every file must load in Qt."""
    from PySide6.QtGui import QFontDatabase

    for weight in ("Regular", "Medium", "SemiBold", "Bold"):
        path = asset_path(f"fonts/Vazirmatn-{weight}.ttf")
        assert path.is_file(), f"missing {path.name}"
        assert path.stat().st_size > 50_000
        assert QFontDatabase.addApplicationFont(str(path)) >= 0
    assert "Vazirmatn" in QFontDatabase.families()
    licence = asset_path("fonts/OFL.txt").read_text(encoding="utf-8")
    assert "SIL Open Font License" in licence


def test_pwa_icons_are_exact_sizes():
    from PySide6.QtGui import QImage

    icons = web_server.CLIENT_DIR / "icons"
    for size in (192, 512):
        path = icons / f"icon-{size}.png"
        assert path.is_file(), f"missing {path.name}"
        image = QImage(str(path))
        assert (image.width(), image.height()) == (size, size)


def test_lucide_icons_are_bundled():
    """A small, consistent line-icon set (ISC). Each file is a real SVG
    and the licence travels with them."""
    expected = {
        "plus", "package", "copy", "trash-2", "history", "chart-column",
        "share-2", "message-square", "circle-help", "info", "settings",
        "search", "folder-open", "file-text", "triangle-alert",
        "circle-check", "x", "download", "upload", "chevron-down",
        "ellipsis-vertical", "external-link",
    }
    for name in expected:
        path = asset_path(f"icons/{name}.svg")
        assert path.is_file(), f"missing {path.name}"
        text = path.read_text(encoding="utf-8")
        assert "<svg" in text and "</svg>" in text
        assert path.stat().st_size < 5000
    assert "ISC License" in asset_path("icons/LICENSE").read_text(
        encoding="utf-8")
