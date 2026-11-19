"""Application wiring (اجراهای برنامه): settings, language, theme, fonts.

Settings live in `settings.json` inside the library folder — one place
for everything the app owns, easy to back up by copying one folder.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTranslator
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication

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


FONT_SIZE_MIN = 8
FONT_SIZE_MAX = 18


def sanitize_settings(settings: dict) -> tuple[dict, bool]:
    """Validate a settings dict in place; return (settings, damaged).

    Mistyped values fall back to safe defaults instead of crashing
    startup (H5): a corrupt settings.json must never open an empty
    library silently or raise AttributeError on a non-dict document.
    `damaged` is True when anything had to be repaired.
    """
    if not isinstance(settings, dict):
        return {}, True
    damaged = False
    language = settings.get("language", "fa")
    if language not in ("fa", "en"):
        settings["language"] = "fa"
        damaged = True
    raw_size = settings.get("font_size", 10)
    if isinstance(raw_size, bool) or not isinstance(raw_size, (int, float, str)):
        settings["font_size"] = 10
        damaged = True
    else:
        try:
            size = int(raw_size)
        except (TypeError, ValueError):
            settings["font_size"] = 10
            damaged = True
        else:
            clamped = max(FONT_SIZE_MIN, min(FONT_SIZE_MAX, size))
            settings["font_size"] = clamped
            if clamped != size:
                damaged = True
    library = settings.get("library")
    if library is not None and (not isinstance(library, str)
                                or not library.strip()):
        settings.pop("library", None)
        damaged = True
    return settings, damaged


_LIBRARY_RE = re.compile(r'"library"\s*:\s*"((?:[^"\\]|\\.)*)"')


def _recover_library_path(raw_text: str) -> Path | None:
    """Best-effort recovery of the library path from a damaged settings.json.

    A file truncated mid-write usually still holds the "library" line;
    if that path is a real folder, the user's library is found instead
    of silently opening an empty default one (H5). Returns None when
    nothing usable can be recovered.
    """
    match = _LIBRARY_RE.search(raw_text)
    if not match:
        return None
    try:
        value = json.loads(f'"{match.group(1)}"')
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value)
    return path if path.is_dir() else None


def load_settings() -> tuple[dict, Path, bool]:
    """Read settings.json from the (possibly default) library folder.

    Returns (settings, settings_path, damaged). A corrupt file, a
    non-dict document, or mistyped values never crash startup and
    never silently open an empty library: values fall back to safe
    defaults, the last known library path is recovered when it is
    still readable, and `damaged` tells run() to warn the user (H5).
    A library path that points at a file (not a folder) — the H6
    brick — falls back to the default library instead of crashing
    the next launch.
    """
    library = DEFAULT_LIBRARY
    bootstrap = library / "settings.json"
    settings: dict = {}
    damaged = False
    if bootstrap.exists():
        try:
            raw_text = bootstrap.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            damaged = True
        else:
            try:
                parsed = json.loads(raw_text)
            except json.JSONDecodeError:
                damaged = True
                recovered = _recover_library_path(raw_text)
                if recovered is not None:
                    library = recovered
            else:
                if not isinstance(parsed, dict):
                    damaged = True
                else:
                    settings = parsed
    settings, bad_values = sanitize_settings(settings)
    damaged = damaged or bad_values
    raw_library = settings.get("library")
    if isinstance(raw_library, str) and raw_library.strip():
        candidate = Path(raw_library)
        if candidate.exists() and not candidate.is_dir():
            # a file, not a folder (H6's brick): fall back, warn
            settings["library"] = str(library)
            damaged = True
        else:
            library = candidate
    try:
        library.mkdir(parents=True, exist_ok=True)
    except OSError:
        library = DEFAULT_LIBRARY
        settings["library"] = str(library)
        damaged = True
        try:
            library.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    settings.setdefault("library", str(library))
    settings.setdefault("language", "fa")
    settings.setdefault("font_size", 10)
    path = library / "settings.json"
    try:
        path.write_text(json.dumps(settings, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    except OSError:
        pass  # read-only folder: keep running with in-memory settings
    return settings, path, damaged


def apply_font_size(settings: dict, app: QApplication | None = None) -> None:
    app = app or QApplication.instance()
    if app is not None:
        font = QFont(theme.load_fonts())
        try:
            size = int(settings.get("font_size", 10))
        except (TypeError, ValueError):
            size = 10
        font.setPointSize(max(FONT_SIZE_MIN, min(FONT_SIZE_MAX, size)))
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
    settings, settings_path, damaged = load_settings()
    i18n.set_language(settings.get("language", "fa"))

    app = QApplication(sys.argv)
    if damaged:
        # Plain warning, not a silent fallback: the user must know the
        # app did not open their usual library (H5).
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(
            None, i18n.tr("settings_damaged_title"),
            i18n.tr("settings_damaged_msg"))
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
