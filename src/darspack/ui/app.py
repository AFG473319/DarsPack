"""Application wiring (اجراهای برنامه): settings, language, theme, fonts.

Settings live in `settings.json` inside the library folder — one place
for everything the app owns, easy to back up by copying one folder.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from .. import APP_NAME
from .. import i18n
from ..core.library import Library

DEFAULT_LIBRARY = Path.home() / "Documents" / "DarsPackLibrary"

# Dark theme via QSS — Qt's CSS dialect. One stylesheet, no per-widget colors.
DARK_QSS = """
QWidget { background-color: #1e1f24; color: #e8e8ea; font-family: 'Segoe UI'; }
QLineEdit, QComboBox, QSpinBox, QTextEdit {
    background-color: #2a2b31; border: 1px solid #3a3b42;
    border-radius: 6px; padding: 5px 8px;
}
QPushButton {
    background-color: #2d3f6e; border: none; border-radius: 6px;
    padding: 7px 12px;
}
QPushButton:hover { background-color: #3a5290; }
QPushButton:disabled { background-color: #33343a; color: #88888f; }
QTableWidget {
    background-color: #23242a; gridline-color: #3a3b42;
    border: 1px solid #3a3b42; border-radius: 6px;
}
QHeaderView::section {
    background-color: #2a2b31; border: none; padding: 6px;
}
QTableWidget::item:selected { background-color: #2d3f6e; }
QStatusBar { color: #a0a0a8; }
QListWidget { background-color: #23242a; border: 1px solid #3a3b42; }
QTabWidget::pane { border: 1px solid #3a3b42; }
QLabel { background: transparent; }
"""


def load_settings() -> tuple[dict, Path]:
    """Read settings.json from the (possibly default) library folder."""
    library = DEFAULT_LIBRARY
    bootstrap = library / "settings.json"
    if bootstrap.exists():
        try:
            settings = json.loads(bootstrap.read_text(encoding="utf-8"))
            library = Path(settings.get("library", library))
        except (json.JSONDecodeError, OSError):
            settings = {}
    else:
        settings = {}
    library.mkdir(parents=True, exist_ok=True)
    settings.setdefault("library", str(library))
    settings.setdefault("language", "fa")
    settings.setdefault("font_size", 10)
    path = library / "settings.json"
    path.write_text(json.dumps(settings, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return settings, path


def apply_font_size(settings: dict, app: QApplication | None = None) -> None:
    app = app or QApplication.instance()
    if app is not None:
        font = QFont("Segoe UI")
        font.setPointSize(int(settings.get("font_size", 10)))
        app.setFont(font)


def _install_excepthook() -> None:
    """Show unexpected crashes instead of dying silently.

    The windowed exe has no console, so without this an uncaught
    exception in the UI thread would close the app with no message.
    """
    import traceback
    from PySide6.QtWidgets import QMessageBox

    def hook(etype, value, tb):
        text = "".join(traceback.format_exception(etype, value, tb))[-1500:]
        try:
            QMessageBox.critical(None, APP_NAME, text)
        except Exception:
            pass
        sys.__excepthook__(etype, value, tb)

    sys.excepthook = hook


def run() -> None:
    settings, settings_path = load_settings()
    i18n.set_language(settings.get("language", "fa"))

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setLayoutDirection(
        Qt.RightToLeft if i18n.language() == "fa" else Qt.LeftToRight)
    app.setStyleSheet(DARK_QSS)
    apply_font_size(settings, app)
    _install_excepthook()

    from .main_window import MainWindow
    window = MainWindow(Path(settings["library"]), settings, settings_path)
    window.show()
    sys.exit(app.exec())
