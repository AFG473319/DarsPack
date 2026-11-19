"""Application wiring (اجراهای برنامه): settings, language, theme, fonts.

Settings live in `settings.json` inside the library folder — one place
for everything the app owns, easy to back up by copying one folder.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtCore import QLockFile, Qt, QTranslator
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from .. import APP_NAME, asset_path
from .. import i18n
from . import theme

DEFAULT_LIBRARY = Path.home() / "Documents" / "DarsPackLibrary"


class PersianTranslator(QTranslator):
    """Translate Qt's built-in dialog and button strings to Persian (Yes/No/OK/Cancel/Close)."""

    _MAPPING = {
        "&Yes": "بله",
        "Yes": "بله",
        "&No": "خیر",
        "No": "خیر",
        "&OK": "تأیید",
        "OK": "تأیید",
        "&Cancel": "لغو",
        "Cancel": "لغو",
        "&Close": "بستن",
        "Close": "بستن",
        "&Save": "ذخیره",
        "Save": "ذخیره",
        "&Open": "باز کردن",
        "Open": "باز کردن",
        "&Discard": "رد کردن",
        "Discard": "رد کردن",
        "&Apply": "اعمال",
        "Apply": "اعمال",
        "&Help": "راهنما",
        "Help": "راهنما",
    }

    def translate(self, context, sourceText, disambiguation=None, n=-1):
        if sourceText in self._MAPPING:
            return self._MAPPING[sourceText]
        # Return None (null QString) so Qt keeps unmapped native strings/shortcuts
        # instead of replacing them with an empty string.
        return None


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
        font = QFont(theme.load_fonts())
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


def acquire_instance_lock(library: Path) -> QLockFile | None:
    """One running copy per library (M20).

    Double-clicking the desktop icon twice used to open two windows on
    the same SQLite library: edits in one were invisible in the other
    until a manual refresh, and one window could delete a file the
    other still showed. The lock file lives in the library folder, so
    each library gets its own guard. A stale lock (a crashed run) is
    released automatically — QLockFile checks that the owning process
    is still alive. Returns the lock to hold, or None if another copy
    already holds it. The caller must keep the returned object alive
    for the whole session; destroying it releases the lock.
    """
    lock = QLockFile(str(library / ".darspack.lock"))
    # tryLock() takes a timeout in ms — 0 means "don't wait at all".
    return lock if lock.tryLock(0) else None


def run() -> None:
    settings, settings_path = load_settings()
    i18n.set_language(settings.get("language", "fa"))

    app = QApplication(sys.argv)
    # M20: a second copy shows a message and exits instead of opening
    # a second window on the same library.
    lock = acquire_instance_lock(Path(settings["library"]))
    if lock is None:
        QMessageBox.information(None, APP_NAME, i18n.tr("already_running"))
        return
    app._instance_lock = lock           # held until the app quits
    if i18n.language() == "fa":
        app._fa_translator = PersianTranslator(app)
        app.installTranslator(app._fa_translator)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(QIcon(str(asset_path("icon/darspack.ico"))))
    app.setLayoutDirection(
        Qt.RightToLeft if i18n.language() == "fa" else Qt.LeftToRight)
    app.setStyle("Fusion")          # one predictable base before the QSS
    theme.load_fonts()
    theme.apply_palette(app)
    app.setStyleSheet(theme.build_qss())
    apply_font_size(settings, app)
    _install_excepthook()

    from .main_window import MainWindow
    window = MainWindow(Path(settings["library"]), settings, settings_path)
    window.show()
    sys.exit(app.exec())
