"""PackageWorker (M24): verify/export run off the UI thread, with cancel.

Verifying/exporting a package used to run on the UI thread — the whole
window froze on a big package, with no progress and no cancel button.
The worker mirrors ImportWorker: `done` always fires (even on cancel or
error), and a cancelled export deletes the partial ZIP it was writing.
"""
import time
import zipfile

from darspack.core.importer import import_file
from darspack.core.library import Library
from darspack.core.manifest import export_package, verify_package
from darspack.ui.workers import PackageWorker


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

    Uses the session-scoped `qapp` fixture: creating a throwaway
    QCoreApplication here and destroying it before a QApplication
    exists in the same process corrupts the heap on Python 3.14. One
    shared QApplication for the whole run, as conftest.py prescribes.
    Returns the `done` dict; the thread is joined before returning,
    so nothing outlives the test.
    """
    from PySide6.QtTest import QSignalSpy

    from darspack.ui.workers import start_worker

    spy = QSignalSpy(worker.done)
    thread = start_worker(worker)
    _wait_signal(worker.done, timeout)
    assert spy.count() > 0, "PackageWorker done never emitted"
    thread.wait(5000)
    return spy.at(0)[0]


def _corrupt_member(zip_path, tmp_path):
    """Rewrite the ZIP with one member's bytes changed (bad sha256)."""
    broken = tmp_path / "broken.zip"
    with zipfile.ZipFile(zip_path) as src, zipfile.ZipFile(
            broken, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename.startswith("files/"):
                data = data + b"tampered"
            dst.writestr(item, data)
    return broken


def _lib_with_file(tmp_path, name="نمونه سوال ریاضی فصل 3.pdf"):
    lib = Library(tmp_path / "lib")
    lib.open()
    src = tmp_path / name
    src.write_bytes(b"demo content " + name.encode("utf-8"))
    import_file(lib, src)
    file_id = lib.conn.execute("SELECT id FROM files").fetchone()["id"]
    return lib, file_id


def test_verify_worker_reports_ok(tmp_path):
    lib, file_id = _lib_with_file(tmp_path)
    try:
        out = tmp_path / "pkg.zip"
        export_package(lib.conn, lib.files_dir, [file_id], out)
        result = _run_worker(
            PackageWorker(str(lib.root), "verify", str(out)))
        assert result["kind"] == "verify"
        assert result["report"].ok is True
    finally:
        lib.close()


def test_verify_worker_reports_corrupted_package(tmp_path):
    lib, file_id = _lib_with_file(tmp_path)
    try:
        out = tmp_path / "pkg.zip"
        export_package(lib.conn, lib.files_dir, [file_id], out)
        broken = _corrupt_member(out, tmp_path)
        result = _run_worker(
            PackageWorker(str(lib.root), "verify", str(broken)))
        assert result["report"].ok is False
        assert result["report"].problems, "expected an issue for tampered bytes"
    finally:
        lib.close()


def test_export_worker_writes_a_valid_package(tmp_path):
    lib, file_id = _lib_with_file(tmp_path)
    try:
        out = tmp_path / "exported.zip"
        result = _run_worker(
            PackageWorker(str(lib.root), "export", str(out), [file_id]))
        assert result["kind"] == "export"
        assert result["info"]["count"] == 1
        assert out.exists()
        assert verify_package(str(out)).ok is True
    finally:
        lib.close()


def test_export_worker_error_reports_and_leaves_no_partial_zip(tmp_path):
    lib, _file_id = _lib_with_file(tmp_path)
    try:
        out = tmp_path / "exported.zip"
        result = _run_worker(
            PackageWorker(str(lib.root), "export", str(out), [999999]))
        assert "error" in result
        assert not out.exists()
    finally:
        lib.close()


def test_export_worker_cancel_deletes_partial_zip(tmp_path, monkeypatch):
    lib, _file_id = _lib_with_file(tmp_path)
    try:
        for i in range(4):
            src = tmp_path / f"extra{i}.pdf"
            src.write_bytes(b"demo" * 1024)
            import_file(lib, src)
        ids = [r["id"] for r in lib.conn.execute("SELECT id FROM files")]

        # slow the zip down so cancel has time to land mid-export
        real_write = zipfile.ZipFile.write

        def slow_write(self, *args, **kwargs):
            time.sleep(0.3)
            return real_write(self, *args, **kwargs)

        monkeypatch.setattr(zipfile.ZipFile, "write", slow_write)

        out = tmp_path / "exported.zip"
        worker = PackageWorker(str(lib.root), "export", str(out), ids)
        worker.progress.connect(lambda *_: worker.cancel())
        result = _run_worker(worker)
        assert result.get("cancelled") is True
        assert not out.exists(), "cancelled export left a partial ZIP"
    finally:
        lib.close()


def test_package_progress_dialog_updates_bar_and_label(qapp):
    from darspack.ui.dialogs import PackageProgressDialog
    dlg = PackageProgressDialog(None, "Title", "Start")
    # nothing known yet: indeterminate range, the label shows the first note
    assert dlg._bar.maximum() == 0
    dlg.set_progress(3, 0, "Stage")
    assert dlg._bar.maximum() == 0 and dlg._label.text() == "Stage"
    dlg.set_progress(0, 10, "Step 1")
    assert dlg._bar.maximum() == 10 and dlg._bar.value() == 0
    dlg.set_progress(10, 10, "Step 2")
    assert dlg._bar.value() == 10 and dlg._label.text() == "Step 2"
    dlg.set_progress(1, 2, "")          # empty name keeps the label
    assert dlg._label.text() == "Step 2" and dlg._bar.value() == 1
