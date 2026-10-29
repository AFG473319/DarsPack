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
