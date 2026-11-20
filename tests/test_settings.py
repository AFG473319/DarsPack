"""Tests for settings loading/saving robustness (H5, H6).

load_settings must never crash startup and never silently open an empty
library: corrupt JSON, a non-dict document, mistyped values and a library
path that is a file all fall back to safe defaults and report `damaged`.
SettingsDialog._save must reject a library path that is a file and must
offer to create a missing folder.
"""
import json
import sys

import pytest
from PySide6.QtWidgets import QMessageBox

import darspack.ui.app as app_module
import darspack.ui.main_window as mw_module
from darspack.ui.app import apply_font_size, load_settings
from darspack.ui.dialogs import SettingsDialog


@pytest.fixture()
def app_default(tmp_path, monkeypatch):
    """Point the app's default library at a temp folder."""
    monkeypatch.setattr(app_module, "DEFAULT_LIBRARY", tmp_path / "lib")
    return tmp_path / "lib"


def _write_settings(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# --- H5: load_settings ------------------------------------------------------

def test_load_settings_corrupt_json_falls_back_and_reports_damaged(app_default):
    _write_settings(app_default / "settings.json", "{broken json")
    settings, path, damaged = load_settings()
    assert damaged is True
    assert settings["font_size"] == 10
    assert settings["language"] == "fa"
    assert settings["library"] == str(app_default)
    # the file is rewritten as valid JSON with the defaults
    assert json.loads(path.read_text(encoding="utf-8"))["font_size"] == 10


def test_load_settings_non_dict_json_does_not_crash(app_default):
    _write_settings(app_default / "settings.json", "[1, 2, 3]")
    settings, _, damaged = load_settings()
    assert damaged is True
    assert settings["font_size"] == 10
    assert settings["library"] == str(app_default)


def test_load_settings_bad_font_size_is_repaired(app_default):
    _write_settings(app_default / "settings.json",
                    json.dumps({"font_size": "abc"}))
    settings, _, damaged = load_settings()
    assert damaged is True
    assert settings["font_size"] == 10

    _write_settings(app_default / "settings.json",
                    json.dumps({"font_size": 99}))
    settings, _, damaged = load_settings()
    assert damaged is True
    assert settings["font_size"] == 18  # clamped to the allowed range

    _write_settings(app_default / "settings.json",
                    json.dumps({"font_size": 2}))
    settings, _, damaged = load_settings()
    assert settings["font_size"] == 8


def test_load_settings_bad_library_type(app_default):
    _write_settings(app_default / "settings.json",
                    json.dumps({"library": 123}))
    settings, _, damaged = load_settings()
    assert damaged is True
    assert settings["library"] == str(app_default)


def test_load_settings_library_is_file_falls_back(app_default, tmp_path):
    not_a_dir = tmp_path / "notadir"
    not_a_dir.write_bytes(b"i am a file")
    _write_settings(app_default / "settings.json",
                    json.dumps({"library": str(not_a_dir)}))
    settings, _, damaged = load_settings()
    assert damaged is True
    assert settings["library"] == str(app_default)


def test_load_settings_recovers_library_from_truncated_json(
        app_default, tmp_path):
    custom = tmp_path / "custom-lib"
    custom.mkdir()
    # truncated mid-write, but the "library" line survived
    _write_settings(app_default / "settings.json",
                    '{"library": "' + str(custom) + '", "font_size": 10')
    settings, _, damaged = load_settings()
    assert damaged is True  # the file is still corrupt
    assert settings["library"] == str(custom)  # ...but the library is found


def test_decode_json_string_loose_keeps_raw_windows_path():
    # A raw Windows path is not valid JSON (\\U, \\T are not escapes),
    # but the recovery must keep it literally instead of giving up —
    # and its \\r / \\t sequences are folder names, not JSON escapes.
    from darspack.ui.app import _decode_json_string_loose
    raw = r"C:\Users\runneradmin\AppData\Local\Temp\custom-lib"
    assert _decode_json_string_loose(raw) == raw
    # when every escape happens to be valid JSON, strict decoding wins
    # a properly escaped path still decodes the same way
    assert _decode_json_string_loose(r"C:\\Users\\runneradmin") == (
        r"C:\Users\runneradmin")
    assert _decode_json_string_loose(r"a\nb") == "a\nb"
    assert _decode_json_string_loose(r"\u0041") == "A"


def test_recover_library_path_keeps_raw_windows_backslashes(monkeypatch):
    # The Windows CI failure: a truncated settings.json holding a raw
    # "C:\\Users\\..." path recovered to the default library instead.
    from pathlib import Path as _Path

    from darspack.ui.app import _recover_library_path
    monkeypatch.setattr(
        _Path, "is_dir",
        lambda self: str(self) == r"C:\Users\runneradmin\custom-lib")
    recovered = _recover_library_path(
        r'{"library": "C:\Users\runneradmin\custom-lib", "font_size": 10')
    assert recovered == _Path(r"C:\Users\runneradmin\custom-lib")


@pytest.mark.skipif(sys.platform == "win32",
                    reason="backslash is a path separator on Windows")
def test_load_settings_recovers_library_with_backslash_in_name(
        app_default, tmp_path):
    # Same failure mode, end to end on POSIX: the raw backslash in the
    # truncated file must not lose the library.
    weird = tmp_path / "we\\ird-lib"
    weird.mkdir()
    _write_settings(app_default / "settings.json",
                    '{"library": "' + str(weird) + '", "font_size": 10')
    settings, _, damaged = load_settings()
    assert damaged is True
    assert settings["library"] == str(weird)


@pytest.mark.skipif(sys.platform == "win32",
                    reason="backslash is a path separator on Windows")
def test_load_settings_recovers_library_with_escape_like_backslash(
        app_default, tmp_path):
    # Backslash + "n" is a valid JSON escape, so strict decoding turns
    # this folder name into a newline — only the raw text is a real
    # folder, and the recovery must try that too.
    tricky = tmp_path / r"a\nb-lib"
    tricky.mkdir()
    _write_settings(app_default / "settings.json",
                    '{"library": "' + str(tricky) + '", "font_size": 10')
    settings, _, damaged = load_settings()
    assert damaged is True
    assert settings["library"] == str(tricky)


def test_load_settings_missing_file_is_fresh(app_default):
    settings, _, damaged = load_settings()
    assert damaged is False
    assert settings["font_size"] == 10
    assert settings["library"] == str(app_default)


def test_apply_font_size_bad_value_does_not_crash(qapp):
    apply_font_size({"font_size": "abc"})
    assert qapp.font().pointSize() == 10
    apply_font_size({"font_size": 99})
    assert qapp.font().pointSize() == 18


# --- H5: SettingsDialog tolerates damaged values ----------------------------

def test_settings_dialog_bad_font_size_does_not_crash(tmp_path, qapp):
    dlg = SettingsDialog(None, {"language": "fa", "font_size": "abc",
                                "library": ""}, tmp_path / "settings.json")
    assert dlg.font_size.value() == 10
    dlg = SettingsDialog(None, {"language": "fa", "font_size": 99,
                                "library": ""}, tmp_path / "settings.json")
    assert dlg.font_size.value() == 18


# --- H6: SettingsDialog._save validates the library path --------------------

def _dialog(tmp_path, library):
    settings = {"language": "fa", "font_size": 10, "library": library}
    return settings, SettingsDialog(None, settings,
                                    tmp_path / "settings.json")


def test_settings_save_rejects_library_path_that_is_a_file(
        tmp_path, qapp, monkeypatch):
    not_a_dir = tmp_path / "notadir"
    not_a_dir.write_bytes(b"i am a file")
    settings, dlg = _dialog(tmp_path, str(tmp_path / "lib"))
    dlg.library.setText(str(not_a_dir))
    warned = []
    monkeypatch.setattr(
        "darspack.ui.dialogs.QMessageBox.warning",
        lambda *a, **k: warned.append(a))
    dlg._save()
    assert warned  # the user is told, not silently saved
    assert settings["library"] == str(tmp_path / "lib")  # unchanged
    assert not (tmp_path / "settings.json").exists()  # nothing written


def test_settings_save_empty_library_path_is_rejected(
        tmp_path, qapp, monkeypatch):
    settings, dlg = _dialog(tmp_path, str(tmp_path / "lib"))
    dlg.library.setText("   ")
    warned = []
    monkeypatch.setattr(
        "darspack.ui.dialogs.QMessageBox.warning",
        lambda *a, **k: warned.append(a))
    dlg._save()
    assert warned
    assert settings["library"] == str(tmp_path / "lib")


def test_settings_save_missing_folder_asks_before_creating(
        tmp_path, qapp, monkeypatch):
    settings, dlg = _dialog(tmp_path, str(tmp_path / "lib"))
    missing = tmp_path / "new-lib"
    dlg.library.setText(str(missing))
    monkeypatch.setattr(
        "darspack.ui.dialogs.QMessageBox.question",
        lambda *a, **k: QMessageBox.No)
    dlg._save()
    assert not missing.exists()  # declined: not created, not saved
    assert settings["library"] == str(tmp_path / "lib")

    monkeypatch.setattr(
        "darspack.ui.dialogs.QMessageBox.question",
        lambda *a, **k: QMessageBox.Yes)
    dlg._save()
    assert missing.is_dir()  # accepted: created and saved
    assert settings["library"] == str(missing)
    saved = json.loads((tmp_path / "settings.json").read_text(
        encoding="utf-8"))
    assert saved["library"] == str(missing)


# --- H6: changing the library offers a restart ------------------------------

def test_offer_restart_no_does_nothing(tmp_path, qapp, monkeypatch):
    win = mw_module.MainWindow(
        tmp_path / "lib",
        {"language": "fa", "font_size": 10, "library": str(tmp_path / "lib")},
        tmp_path / "settings.json")
    try:
        asked = []
        monkeypatch.setattr(
            mw_module.QMessageBox, "question",
            lambda *a, **k: asked.append(True) or QMessageBox.No)
        win._offer_restart_for_library_change()
        assert asked
    finally:
        win.lib.close()


def test_offer_restart_yes_relaunches_and_quits(tmp_path, qapp, monkeypatch):
    win = mw_module.MainWindow(
        tmp_path / "lib",
        {"language": "fa", "font_size": 10, "library": str(tmp_path / "lib")},
        tmp_path / "settings.json")
    try:
        launched = []
        monkeypatch.setattr(
            mw_module.QMessageBox, "question",
            lambda *a, **k: QMessageBox.Yes)
        monkeypatch.setattr(
            "PySide6.QtCore.QProcess.startDetached",
            lambda *a, **k: launched.append(a))
        quit_called = []
        monkeypatch.setattr(
            "PySide6.QtWidgets.QApplication.quit",
            lambda: quit_called.append(True))
        win._offer_restart_for_library_change()
        assert launched  # the app is relaunched
        assert quit_called  # ...and the old process quits
    finally:
        win.lib.close()


def test_open_settings_offers_restart_when_library_changes(
        tmp_path, qapp, monkeypatch):
    settings = {"language": "fa", "font_size": 10,
                "library": str(tmp_path / "lib")}
    win = mw_module.MainWindow(tmp_path / "lib", settings,
                               tmp_path / "settings.json")
    try:
        asked = []
        monkeypatch.setattr(
            mw_module.QMessageBox, "question",
            lambda *a, **k: asked.append(True) or QMessageBox.No)

        class FakeDialog:
            def __init__(self, *a, **k):
                pass

            def exec(self):
                settings["library"] = str(tmp_path / "other-lib")
                return True

        monkeypatch.setattr(mw_module.dialogs, "SettingsDialog", FakeDialog)
        win.open_settings()
        assert asked  # the restart question was asked
    finally:
        win.lib.close()
