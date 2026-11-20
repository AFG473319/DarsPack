"""ImportDialog: pick buttons, drag&drop, the keep flag.

The import *work* itself is covered by the MainWindow tests; this file
pins the dialog's own contract: it hands the chosen paths + keep flag to
the parent's import worker and closes.
"""
from pathlib import Path

import pytest
from PySide6.QtCore import QMimeData, QUrl
from PySide6.QtWidgets import QFileDialog

from darspack.ui.dialogs import ImportDialog


class _Recorder:
    """Parent double: records what run_import_worker is asked to do."""

    def __init__(self):
        self.calls = []

    def run_import_worker(self, paths, keep=False):
        self.calls.append((list(paths), keep))


class _FakeEvent:
    """Drop/drag event double (QDragEnterEvent has no public constructor)."""

    def __init__(self, urls=None):
        self._mime = QMimeData()
        if urls:
            self._mime.setUrls(urls)
        self.accepted = False
        self.ignored = False

    def mimeData(self):
        return self._mime

    def acceptProposedAction(self):
        self.accepted = True

    def ignore(self):
        self.ignored = True


@pytest.fixture()
def dialog(qapp):
    dlg = ImportDialog(None)
    recorder = _Recorder()
    dlg.parent_window = recorder
    return dlg, recorder


def test_start_passes_paths_and_keep_flag_to_worker(dialog):
    dlg, recorder = dialog
    dlg.keep.setChecked(True)
    dlg._start([Path("a.pdf"), Path("b.pdf")])
    assert recorder.calls == [([Path("a.pdf"), Path("b.pdf")], True)]


def test_pick_files_starts_import_on_selection(dialog, monkeypatch, tmp_path):
    dlg, recorder = dialog
    f = tmp_path / "ریاضی.pdf"
    monkeypatch.setattr(
        QFileDialog, "getOpenFileNames",
        staticmethod(lambda *a, **k: ([str(f)], "")))
    dlg._pick_files()
    assert recorder.calls == [([str(f)], False)]


def test_pick_files_does_nothing_when_cancelled(dialog, monkeypatch):
    dlg, recorder = dialog
    monkeypatch.setattr(
        QFileDialog, "getOpenFileNames",
        staticmethod(lambda *a, **k: ([], "")))
    dlg._pick_files()
    assert recorder.calls == []


def test_pick_folder_starts_import_on_selection(dialog, monkeypatch, tmp_path):
    dlg, recorder = dialog
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory",
        staticmethod(lambda *a, **k: str(tmp_path)))
    dlg._pick_folder()
    assert recorder.calls == [([str(tmp_path)], False)]


def test_drag_enter_accepts_url_mimes(dialog):
    dlg, _ = dialog
    ev = _FakeEvent(urls=[QUrl.fromLocalFile(str(Path("x.pdf")))])
    dlg.dragEnterEvent(ev)
    assert ev.accepted and not ev.ignored


def test_drag_enter_ignores_mimes_without_urls(dialog):
    dlg, _ = dialog
    ev = _FakeEvent()
    dlg.dragEnterEvent(ev)
    assert ev.ignored and not ev.accepted


def test_drop_starts_import_for_local_files(dialog, tmp_path):
    dlg, recorder = dialog
    f = tmp_path / "ریاضی.pdf"
    ev = _FakeEvent(urls=[QUrl.fromLocalFile(str(f))])
    dlg.dropEvent(ev)
    assert ev.accepted
    # dropEvent passes the URL's local path back, with posix-style slashes
    assert recorder.calls == [([f.as_posix()], False)]


def test_drop_ignores_non_local_urls(dialog):
    dlg, recorder = dialog
    ev = _FakeEvent(urls=[QUrl("https://example.com/f.pdf")])
    dlg.dropEvent(ev)
    assert ev.ignored
    assert recorder.calls == []
