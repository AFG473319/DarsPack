"""The icon assets must stay loadable after every regeneration."""
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


def test_web_client_has_favicon():
    assert (web_server.CLIENT_DIR / "favicon.ico").is_file()
