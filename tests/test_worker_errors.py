"""Regression tests for the silent-import-hang bug (2026-10-24).

A file that fails mid-import (locked by another program, unreadable)
used to kill the worker thread before the `done` signal — the UI stayed
on «در حال وارد کردن» forever with no error anywhere. These tests lock
in the contract: one bad file is counted and reported; `done` always
fires; the rest of the batch still imports.
"""
import time

from pathlib import Path

import pytest

import darspack.core.importer as importer
from darspack.core.importer import import_paths
from darspack.core.library import Library


@pytest.fixture()
def batch(tmp_path, monkeypatch):
    """A folder: two good files + one that fails like a locked file."""
    folder = tmp_path / "from-telegram"
    folder.mkdir()
    (folder / "good1.pdf").write_bytes(b"one")
    (folder / "good2.pdf").write_bytes(b"two")
    (folder / "bad.pdf").write_bytes(b"boom")
    original = importer.shutil.copy2

    def fake_copy2(src, dst, **kwargs):
        if Path(str(src)).name == "bad.pdf":
            raise PermissionError("file locked by another program")
        return original(src, dst, **kwargs)

    monkeypatch.setattr(importer.shutil, "copy2", fake_copy2)
    return folder


def test_batch_import_survives_a_bad_file(tmp_path, batch):
    with Library(tmp_path / "lib") as lib:
        results = import_paths(lib, [batch])
        statuses = {r.path.name: r.status for r in results}
        assert statuses["good1.pdf"] == "imported"
        assert statuses["good2.pdf"] == "imported"
        assert statuses["bad.pdf"] == "error"
        error = next(r for r in results if r.status == "error")
        assert "PermissionError" in error.message_fa
        count = lib.conn.execute("SELECT COUNT(*) c FROM files").fetchone()["c"]
        assert count == 2


def test_import_worker_always_emits_done(tmp_path, batch):
    from PySide6.QtCore import QCoreApplication

    from darspack.ui.workers import ImportWorker

    app = QCoreApplication.instance() or QCoreApplication([])
    received = []
    worker = ImportWorker(str(tmp_path / "lib"), [batch], keep_duplicates=True)
    worker.done.connect(lambda *args: received.append(args))
    worker.start()
    deadline = time.time() + 30
    while not received and time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)
    worker.wait(5000)
    assert received, "done never emitted — the UI would hang on 'importing'"
    imported, duplicates, errors, messages, new_ids = received[0]
    assert (imported, duplicates, errors) == (2, 0, 1)
    assert any("bad.pdf" in m for m in messages)
    assert len(new_ids) == 2            # ids for the classification dialog


def test_import_worker_reports_progress(tmp_path):
    """The UI progress contract: (1, total, name) then (2, total, name)."""
    from PySide6.QtCore import QCoreApplication

    from darspack.ui.workers import ImportWorker

    folder = tmp_path / "from"
    folder.mkdir()
    (folder / "one.pdf").write_bytes(b"1")
    (folder / "two.pdf").write_bytes(b"2")

    app = QCoreApplication.instance() or QCoreApplication([])
    progress, received = [], []
    worker = ImportWorker(str(tmp_path / "lib"), [folder])
    worker.progress.connect(lambda d, t, n: progress.append((d, t, n)))
    worker.done.connect(lambda *args: received.append(args))
    worker.start()
    deadline = time.time() + 30
    while not (received and len(progress) >= 2) and time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)
    worker.wait(5000)
    # iter_files sorts, so one.pdf is imported first
    assert progress[:2] == [(1, 2, "one.pdf"), (2, 2, "two.pdf")]


def test_catastrophic_failure_still_reports_and_logs(tmp_path, monkeypatch):
    """If even opening the library dies, `done` must still fire — and the
    windowed exe needs the traceback in error.log (it has no console)."""
    import darspack.ui.workers as workers_mod
    from PySide6.QtCore import QCoreApplication

    from darspack.ui.workers import ImportWorker

    (tmp_path / "lib").mkdir()          # error.log's parent must exist

    def boom(self):
        raise RuntimeError("disk gone")
    monkeypatch.setattr(workers_mod.Library, "open", boom)

    app = QCoreApplication.instance() or QCoreApplication([])
    received = []
    worker = ImportWorker(str(tmp_path / "lib"), [tmp_path])
    worker.done.connect(lambda *args: received.append(args))
    worker.start()
    deadline = time.time() + 30
    while not received and time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)
    worker.wait(5000)
    assert received, "done never emitted on a catastrophic failure"
    imported, duplicates, errors, messages, new_ids = received[0]
    assert (imported, duplicates, errors) == (0, 0, 1)
    assert any("خطای غیرمنتظره" in m for m in messages)
    log = (tmp_path / "lib" / "error.log").read_text(encoding="utf-8")
    assert "import crashed" in log
    assert "RuntimeError" in log
