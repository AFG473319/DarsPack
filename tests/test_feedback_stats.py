"""Tests for the reworked «بازخورد» (feedback) flow and the background
stats worker.

Feedback contract: submit always saves locally FIRST (a failed network
call never loses feedback), then posts the same payload to the
configured endpoint in a background thread. Stats contract: the dialog
never computes on the UI thread — a worker thread does, and the user
can cancel.
"""
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from darspack.core.library import Library


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


# ---- feedback payload + local save --------------------------------------

def test_payload_shape_and_local_mirror(tmp_path):
    from types import SimpleNamespace

    from darspack.ui.dialogs import build_feedback_payload, save_feedback
    payload = build_feedback_payload(4, "fb_cat_bug", "صفحه سفید می‌شود",
                                     "@friend")
    assert payload["app"] == "DarsPack" and payload["rating"] == 4
    assert payload["category"] == "fb_cat_bug" and payload["contact"] == "@friend"
    assert payload["version"] and payload["sent_at"]

    lib = Library(tmp_path / "lib").open()
    parent = SimpleNamespace(lib=lib)
    save_feedback(parent, payload)
    lib.close()
    line = (tmp_path / "lib" / "feedback.jsonl").read_text(
        encoding="utf-8").strip()
    assert json.loads(line) == payload        # exact same shape as the POST


def test_poster_success_against_local_server(qapp):
    """The poster must deliver the JSON body to a real HTTP endpoint."""
    from darspack.ui.workers import FeedbackPoster

    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            received.append(json.loads(self.rfile.read(length)))
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        results = []
        payload = {"app": "DarsPack", "message": "test"}
        poster = FeedbackPoster(
            f"http://127.0.0.1:{server.server_port}/", payload)
        poster.done.connect(results.append)
        poster.start()
        deadline = time.time() + 10
        while not results and time.time() < deadline:
            qapp.processEvents()
            time.sleep(0.02)
        poster.wait(5000)
        assert results == [True]
        assert received == [payload]          # exact JSON reached the server
    finally:
        server.shutdown()


def test_poster_reports_failure_without_raising(qapp):
    from darspack.ui.workers import FeedbackPoster

    results = []
    poster = FeedbackPoster("http://127.0.0.1:9/", {"x": 1})   # nothing listens
    poster.done.connect(results.append)
    poster.start()
    deadline = time.time() + 15
    while not results and time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.05)
    poster.wait(5000)
    assert results == [False]                 # clean failure, no exception


# ---- stats: background worker with cancel -------------------------------

def test_stats_worker_matches_library_stats(tmp_path, qapp):
    from darspack.ui.dialogs import library_stats
    from darspack.ui.workers import StatsWorker

    with Library(tmp_path / "lib") as lib:
        for i in range(5):
            p = tmp_path / f"f{i}.pdf"
            p.write_bytes(b"x")
            from darspack.core.importer import import_file
            import_file(lib, p)
        worker = StatsWorker(str(tmp_path / "lib"))
        results = []
        worker.done.connect(results.append)
        worker.start()
        deadline = time.time() + 15
        while not results and time.time() < deadline:
            qapp.processEvents()
            time.sleep(0.02)
        worker.wait(5000)
        assert results and results[0] is not None
        assert results[0] == library_stats(lib.conn)


def test_stats_worker_cancel_returns_none(tmp_path, qapp):
    from darspack.ui.workers import StatsWorker

    with Library(tmp_path / "lib") as lib:
        p = tmp_path / "f.pdf"
        p.write_bytes(b"x")
        from darspack.core.importer import import_file
        import_file(lib, p)
        worker = StatsWorker(str(tmp_path / "lib"))
        worker.cancel()                       # cancelled before start
        results = []
        worker.done.connect(results.append)
        worker.start()
        deadline = time.time() + 15
        while not results and time.time() < deadline:
            qapp.processEvents()
            time.sleep(0.02)
        worker.wait(5000)
        assert results == [None]              # no results dialog on cancel
