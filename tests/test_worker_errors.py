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


def _wait_signal(signal, timeout=30):
    """Run a nested event loop until `signal` fires or the timeout hits.

    This is what QSignalSpy.wait() does internally — but wait() itself
    times out on signals emitted from another thread in this PySide6
    build (verified on 3.12 and 3.14: it returns False even though the
    signal arrives, and the emitting thread stalls until wait returns),
    so wait on a plain loop that quits on the signal instead. The
    caller checks the spy's count to tell a real emission from a
    timeout. Never a processEvents/sleep poll: the loop wakes only
    when the signal (or the timer) fires.
    """
    from PySide6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    signal.connect(loop.quit)
    timer.start(timeout * 1000)
    loop.exec()


def _run_worker(worker, timeout=30):
    """Start the worker on its own thread and wait for `done` — the
    spy records the payload; the nested loop wakes on the signal.
    Returns the `done` payloads, each as a list. The thread is joined
    before returning, so nothing outlives the test."""
    from PySide6.QtTest import QSignalSpy

    from darspack.ui.workers import start_worker

    spy = QSignalSpy(worker.done)
    thread = start_worker(worker)
    _wait_signal(worker.done, timeout)
    assert spy.count() > 0, \
        "done never emitted — the UI would hang on 'importing'"
    thread.wait(5000)
    return [list(spy.at(i)) for i in range(spy.count())]


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


def test_import_worker_always_emits_done(tmp_path, batch, qapp):
    from darspack.ui.workers import ImportWorker

    worker = ImportWorker(str(tmp_path / "lib"), [batch], keep_duplicates=True)
    received = _run_worker(worker)
    imported, duplicates, errors, messages, new_ids = received[0]
    assert (imported, duplicates, errors) == (2, 0, 1)
    assert any("bad.pdf" in m for m in messages)
    assert len(new_ids) == 2            # ids for the classification dialog


def test_import_worker_reports_progress(tmp_path, qapp):
    """The UI progress contract: (1, total, name) then (2, total, name)."""
    from PySide6.QtTest import QSignalSpy

    from darspack.ui.workers import ImportWorker, start_worker

    folder = tmp_path / "from"
    folder.mkdir()
    (folder / "one.pdf").write_bytes(b"1")
    (folder / "two.pdf").write_bytes(b"2")

    worker = ImportWorker(str(tmp_path / "lib"), [folder])
    progress_spy = QSignalSpy(worker.progress)
    done_spy = QSignalSpy(worker.done)
    thread = start_worker(worker)
    _wait_signal(worker.done)
    assert done_spy.count() > 0, "done never emitted"
    thread.wait(5000)
    progress = [tuple(progress_spy.at(i))
                for i in range(progress_spy.count())]
    # iter_files sorts, so one.pdf is imported first
    assert progress[:2] == [(1, 2, "one.pdf"), (2, 2, "two.pdf")]


def test_catastrophic_failure_still_reports_and_logs(tmp_path, monkeypatch, qapp):
    """If even opening the library dies, `done` must still fire — and the
    windowed exe needs the traceback in error.log (it has no console).

    Uses the session-scoped `qapp` fixture: creating a throwaway
    QCoreApplication per test and destroying it before a QApplication
    exists in the same process corrupts the heap on Python 3.14
    (access violation in the CI 3.14 job; heap corruption under
    PYTHONMALLOC=debug locally). One shared QApplication for the
    whole run, as conftest.py prescribes.
    """
    import darspack.ui.workers as workers_mod

    from darspack.ui.workers import ImportWorker

    (tmp_path / "lib").mkdir()          # error.log's parent must exist

    def boom(self):
        raise RuntimeError("disk gone")
    monkeypatch.setattr(workers_mod.Library, "open", boom)

    worker = ImportWorker(str(tmp_path / "lib"), [tmp_path])
    received = _run_worker(worker)
    imported, duplicates, errors, messages, new_ids = received[0]
    assert (imported, duplicates, errors) == (0, 0, 1)
    assert any("خطای غیرمنتظره" in m for m in messages)
    log = (tmp_path / "lib" / "error.log").read_text(encoding="utf-8")
    assert "import crashed" in log
    assert "RuntimeError" in log


def test_import_worker_cancel_stops_between_files(tmp_path, monkeypatch, qapp):
    """M21: cancel() stops the worker after the current file; done still
    fires (the window relies on that to close cleanly mid-import)."""
    import darspack.ui.workers as workers_mod

    from darspack.ui.workers import ImportWorker

    folder = tmp_path / "from"
    folder.mkdir()
    for i in range(5):
        (folder / f"f{i}.pdf").write_bytes(b"x")

    real_import = workers_mod.import_file

    def slow_import(lib, path, **kwargs):
        time.sleep(0.4)
        return real_import(lib, path, **kwargs)

    monkeypatch.setattr(workers_mod, "import_file", slow_import)

    from PySide6.QtTest import QSignalSpy

    from darspack.ui.workers import start_worker

    worker = ImportWorker(str(tmp_path / "lib"), [folder])
    progress_spy = QSignalSpy(worker.progress)
    done_spy = QSignalSpy(worker.done)
    thread = start_worker(worker)
    _wait_signal(worker.progress)
    assert progress_spy.count() > 0, "no progress before cancel"
    worker.cancel()          # lands while the first file is still copying
    _wait_signal(worker.done)
    assert done_spy.count() > 0, "done never emitted after cancel"
    thread.wait(5000)
    imported, duplicates, errors, messages, new_ids = done_spy.at(0)
    assert imported < 5, "cancel did not stop the import"
    assert imported >= 1, "the file in flight should still finish"
