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


def test_poster_success_against_local_server(qapp):
    """The poster must deliver the JSON body to a real HTTP endpoint."""
    from PySide6.QtTest import QSignalSpy

    from darspack.ui.workers import FeedbackPoster, start_worker

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
        payload = {"app": "DarsPack", "message": "test"}
        poster = FeedbackPoster(
            f"http://127.0.0.1:{server.server_port}/", payload)
        spy = QSignalSpy(poster.done)
        thread = start_worker(poster)
        _wait_signal(poster.done, 10)
        assert spy.count() > 0, "poster done never emitted"
        thread.wait(5000)
        assert spy.at(0) == [True]
        assert received == [payload]          # exact JSON reached the server
    finally:
        server.shutdown()


def test_poster_reports_failure_without_raising(qapp):
    from PySide6.QtTest import QSignalSpy

    from darspack.ui.workers import FeedbackPoster, start_worker

    poster = FeedbackPoster("http://127.0.0.1:9/", {"x": 1}, timeout=0.2)   # nothing listens
    spy = QSignalSpy(poster.done)
    thread = start_worker(poster)
    _wait_signal(poster.done, 5)
    assert spy.count() > 0, "poster done never emitted"
    thread.wait(5000)
    assert spy.at(0) == [False]               # clean failure, no exception


# ---- stats: background worker with cancel -------------------------------

def test_stats_worker_matches_library_stats(tmp_path, qapp):
    from PySide6.QtTest import QSignalSpy

    from darspack.ui.dialogs import library_stats
    from darspack.ui.workers import StatsWorker, start_worker

    with Library(tmp_path / "lib") as lib:
        for i in range(5):
            p = tmp_path / f"f{i}.pdf"
            p.write_bytes(b"x")
            from darspack.core.importer import import_file
            import_file(lib, p)
        worker = StatsWorker(str(tmp_path / "lib"))
        spy = QSignalSpy(worker.done)
        thread = start_worker(worker)
        _wait_signal(worker.done, 15)
        assert spy.count() > 0, "stats done never emitted"
        thread.wait(5000)
        assert spy.at(0)[0] is not None
        assert spy.at(0)[0] == library_stats(lib.conn)


def test_stats_worker_cancel_returns_none(tmp_path, qapp):
    from PySide6.QtTest import QSignalSpy

    from darspack.ui.workers import StatsWorker, start_worker

    with Library(tmp_path / "lib") as lib:
        p = tmp_path / "f.pdf"
        p.write_bytes(b"x")
        from darspack.core.importer import import_file
        import_file(lib, p)
        worker = StatsWorker(str(tmp_path / "lib"))
        worker.cancel()                       # cancelled before start
        spy = QSignalSpy(worker.done)
        thread = start_worker(worker)
        _wait_signal(worker.done, 15)
        assert spy.count() > 0, "stats done never emitted"
        thread.wait(5000)
        assert spy.at(0) == [None]            # no results dialog on cancel


# ---- feedback: the unsent queue, drafts and limits ------------------------

def _flush_dialog(dlg):
    """deleteLater + flush deferred deletions INSIDE the test. If they
    stay pending, a later test's event-loop wait (QTest.qWait) processes
    them after the parent widget's Python wrapper is gone — the exact
    access-violation crash class documented in test_ui_dialogs."""
    from PySide6.QtCore import QCoreApplication, QEvent

    dlg.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def _dialog_parent(tmp_path, qapp):
    """A real widget stand-in for MainWindow (the dialogs read lib from
    it), with an EMPTY sidecar state the test controls."""
    from PySide6.QtWidgets import QWidget

    lib = Library(tmp_path / "lib").open()
    parent = QWidget()
    parent.lib = lib
    return parent


@pytest.fixture()
def fake_boxes(monkeypatch):
    """Replace QMessageBox inside the dialogs module: no modal can ever
    block a test, and what *would* have popped up is recorded."""
    from PySide6.QtWidgets import QMessageBox

    class FakeBox:
        Standard = QMessageBox
        Yes = QMessageBox.Yes
        No = QMessageBox.No
        Retry = QMessageBox.Retry
        Close = QMessageBox.Close
        Ok = QMessageBox.Ok
        ActionRole = QMessageBox.ActionRole
        popped = []

        @staticmethod
        def question(parent, title, text, *rest, **kw):
            FakeBox.popped.append(("question", title, text, kw))
            return FakeBox.next_answer

        @staticmethod
        def information(parent, title, text, *rest, **kw):
            FakeBox.popped.append(("info", title, text, kw))

        @staticmethod
        def warning(parent, title, text, *rest, **kw):
            FakeBox.popped.append(("warning", title, text, kw))

        @staticmethod
        def critical(parent, title, text, *rest, **kw):
            FakeBox.popped.append(("critical", title, text, kw))

    FakeBox.popped = []
    FakeBox.next_answer = QMessageBox.Yes
    monkeypatch.setattr("darspack.ui.dialogs.QMessageBox", FakeBox)
    return FakeBox


@pytest.fixture()
def stub_poster(monkeypatch):
    """A FeedbackPoster that never touches the network: the tests drive
    done(False)/done(True) manually to try the retry paths."""
    from PySide6.QtCore import QObject, Signal

    created = []

    class StubPoster(QObject):
        done = Signal(bool)

        def __init__(self, endpoint, payload, timeout=8):
            super().__init__()
            self.endpoint = endpoint
            self.payload = payload
            created.append(self)

        def run(self):
            pass                    # the test emits `done` when it wants

    monkeypatch.setattr("darspack.ui.dialogs.FeedbackPoster", StubPoster)
    return created


def test_pending_queue_roundtrip_and_exact_drop(tmp_path):
    """The queue is the retry contract: an entry leaves it only on a
    real 2xx, by exact payload identity (never a neighbour's entry)."""
    from types import SimpleNamespace

    from darspack.ui.dialogs import (
        build_feedback_payload, drop_pending, load_pending, queue_pending,
    )
    lib = Library(tmp_path / "lib").open()
    parent = SimpleNamespace(lib=lib)
    a = build_feedback_payload(5, "fb_cat_bug", "شکسته", "")
    b = build_feedback_payload(2, "fb_cat_idea", "پیشنهاد", "")
    assert queue_pending(parent, a, mirrored=True)
    assert queue_pending(parent, b, mirrored=False)
    assert [(e["payload"], e["mirrored"]) for e in load_pending(parent)] == \
        [(a, True), (b, False)]
    assert drop_pending(parent, a) == [{"payload": a, "mirrored": True}]
    assert [e["payload"] for e in load_pending(parent)] == [b]
    assert drop_pending(parent, {"payload": "nothing here"}) == []
    lib.close()


def test_pending_queue_tolerates_a_corrupt_file(tmp_path):
    from types import SimpleNamespace

    from darspack.ui.dialogs import load_pending
    lib = Library(tmp_path / "lib").open()
    (tmp_path / "lib" / "feedback_pending.json").write_text("{oops")
    assert load_pending(SimpleNamespace(lib=lib)) == []   # worn file == empty
    lib.close()


def test_draft_roundtrip_and_clear(tmp_path):
    from types import SimpleNamespace

    from darspack.ui.dialogs import clear_draft, load_draft, save_draft
    lib = Library(tmp_path / "lib").open()
    parent = SimpleNamespace(lib=lib)
    state = {"rating": 4, "category": "fb_cat_bug",
             "message": "نیمه‌کاره", "contact": "t@example.com"}
    assert save_draft(parent, state)
    assert load_draft(parent) == state
    clear_draft(parent)
    assert load_draft(parent) == {}
    clear_draft(parent)                       # no error double-clearing
    lib.close()


def test_feedback_dialog_restores_the_draft(tmp_path, qapp):
    """An accidental close must never throw away a half-written
    report: reopening the dialog shows exactly what was typed."""
    from darspack.i18n import tr
    from darspack.ui.dialogs import (
        FeedbackDialog, clear_draft, save_draft,
    )
    parent = _dialog_parent(tmp_path, qapp)
    clear_draft(parent)
    save_draft(parent, {"rating": 3, "category": "fb_cat_idea",
                        "message": "پیش‌نویسِ من", "contact": "@arian"})
    dlg = FeedbackDialog(parent, {})
    assert dlg.rating == 3                    # stars restored
    assert dlg.message.toPlainText() == "پیش‌نویسِ من"
    assert dlg.contact.text() == "@arian"
    assert dlg.category.currentData() == "fb_cat_idea"
    assert dlg.notice.text() == tr("fb_draft_restored")
    draft_path = tmp_path / "lib" / "feedback_draft.json"
    dlg._submitted = True
    dlg._flush_draft()                        # a submitted draft is removed
    assert not draft_path.exists()
    _flush_dialog(dlg)


def test_message_counter_blocks_over_limit(tmp_path, qapp, fake_boxes):
    """The free-form limit is visible while typing: a live counter, red
    past 2000 characters, submit disabled — never a server-side 413."""
    from darspack.ui.dialogs import (
        FeedbackDialog, MAX_MESSAGE_CHARS, load_pending,
    )
    parent = _dialog_parent(tmp_path, qapp)
    pending_before = len(load_pending(parent))
    dlg = FeedbackDialog(parent, {})
    dlg.message.setPlainText("ا" * (MAX_MESSAGE_CHARS + 1))
    assert dlg.submit.isEnabled() is False
    assert "#e5484d" in dlg.counter.styleSheet()          # red warning

    dlg._submit()                             # the click must be a no-op
    assert fake_boxes.popped[-1][0] == "warning"   # an explanatory box, not
    jsonl = tmp_path / "lib" / "feedback.jsonl"    # a silent queue entry
    assert not jsonl.exists() and len(load_pending(parent)) == pending_before
    _flush_dialog(dlg)


def test_submit_is_idempotent_and_failures_keep_the_entry(
        tmp_path, qapp, fake_boxes, stub_poster):
    """The whole happy-plus-failure lifecycle against a stub poster:
    one entry saved locally + queued, a dead network leaves it queued,
    «ارسال دوباره» re-POSTs without duplicating the line, success pops
    the queue and thanks the user."""
    from darspack.i18n import tr
    from darspack.ui.dialogs import FeedbackDialog, load_pending

    from PySide6.QtWidgets import QDialog

    parent = _dialog_parent(tmp_path, qapp)
    fake_boxes.next_answer = fake_boxes.Retry          # «ارسال دوباره»
    dlg = FeedbackDialog(parent, {"feedback_endpoint":
                                  "https://example.test/fb"})
    dlg.message.setPlainText("شبکه قطع شد ولی بازخورد نپاشد")
    assert load_pending(parent) == []          # nothing queued before submit

    dlg._submit()
    assert dlg._posting and not dlg.submit.isEnabled()
    assert dlg.submit.text() == tr("fb_sending")
    jsonl = tmp_path / "lib" / "feedback.jsonl"
    assert len(jsonl.read_text(encoding="utf-8").strip().splitlines()) == 1
    assert len(load_pending(parent)) == 1      # queued for the network
    assert len(stub_poster) == 1               # exactly one post started

    dlg._submit()                              # double click mid-send
    assert len(load_pending(parent)) == 1 and len(stub_poster) == 1

    stub_poster[0].done.emit(False)            # the network failed
    assert len(stub_poster) == 2               # answer=Retry → one re-POST
    assert dlg._posting                        # the re-POST is in flight
    assert len(load_pending(parent)) == 1      # waiting, not duplicated
    assert len(jsonl.read_text(encoding="utf-8").strip().splitlines()) == 1
    assert fake_boxes.popped[-1][0] == "question" and \
        "دوباره تلاش" in fake_boxes.popped[-1][2]

    stub_poster[1].done.emit(True)             # ...which this time works
    assert load_pending(parent) == []          # popped from the queue
    assert len(jsonl.read_text(encoding="utf-8").strip().splitlines()) == 1
    assert dlg._submitted                      # the draft is released
    assert fake_boxes.popped[-1][0] == "info"  # the thanks message
    assert dlg.result() == QDialog.DialogCode.Accepted
    dlg._flush_draft()
    assert not (tmp_path / "lib" / "feedback_draft.json").exists()
    _flush_dialog(dlg)


def test_real_network_failure_then_retry_success(tmp_path, qapp, fake_boxes):
    """Against a REAL flaky HTTP server: the first POST 500s, the form
    offers «ارسال دوباره», the queued entry is re-POSTed without
    duplicating the local line, and success empties the queue."""
    import http.server
    import threading

    from darspack.ui.dialogs import FeedbackDialog, load_pending

    hits = []

    class FlakyHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(length)
            hits.append(1)
            code = 500 if len(hits) == 1 else 200
            self.send_response(code)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), FlakyHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        from PySide6.QtTest import QSignalSpy

        parent = _dialog_parent(tmp_path, qapp)
        fake_boxes.next_answer = fake_boxes.Retry          # send again
        dlg = FeedbackDialog(parent, {
            "feedback_endpoint": f"http://127.0.0.1:{server.server_port}/"})
        dlg.message.setPlainText("راستی‌آزمایی‌های واقعی شبکه هم باید بگذرد")
        dlg._submit()
        # The first POST 500s (done(False) → retry prompt → a second
        # poster is started); the second POST 200s (done(True)).
        spy1 = QSignalSpy(dlg._poster.done)
        _wait_signal(dlg._poster.done, 15)
        assert spy1.count() > 0, "first post never finished"
        assert len(hits) == 1
        spy2 = QSignalSpy(dlg._poster.done)
        _wait_signal(dlg._poster.done, 15)
        assert spy2.count() > 0, "retry post never finished"
        dlg._poster_thread.wait(5000)
        assert len(hits) == 2                    # one failure + the retry
        assert [p for p in fake_boxes.popped if p[0] == "question"], \
            "the network failure must surface as a retry prompt"
        assert fake_boxes.popped[-1][0] == "info"   # the thanks
        assert load_pending(parent) == []           # queue emptied
        jsonl = tmp_path / "lib" / "feedback.jsonl"
        assert len(jsonl.read_text(encoding="utf-8").strip().splitlines()) == 1
        _flush_dialog(dlg)
    finally:
        server.shutdown()


def test_opening_with_pending_entries_offers_to_send(tmp_path, qapp,
                                                     fake_boxes, stub_poster):
    """Entries left queued (failing Wi-Fi yesterday) surface as one
    «اکنون ارسال شود؟» when the dialog opens, then walk the queue in
    order until one fails."""
    from darspack.ui.dialogs import (
        FeedbackDialog, build_feedback_payload, load_pending, queue_pending,
    )
    parent = _dialog_parent(tmp_path, qapp)
    for i in range(2):
        queue_pending(parent, build_feedback_payload(
            4, "fb_cat_question", f"بازخورد قدیمی {i}", ""), mirrored=True)

    fake_boxes.next_answer = fake_boxes.No     # says «بعداً»
    dlg = FeedbackDialog(parent, {"feedback_endpoint":
                                  "https://example.test/fb"})
    dlg._maybe_prompt_pending()                # prompt shown on the dialog
    assert fake_boxes.popped[-1][0] == "question" and "۲" in \
        fake_boxes.popped[-1][2]
    assert load_pending(parent)                # «No» changes nothing
    _flush_dialog(dlg)

    fake_boxes.next_answer = fake_boxes.Yes
    dlg2 = FeedbackDialog(parent, {"feedback_endpoint":
                                   "https://example.test/fb"})
    dlg2._maybe_prompt_pending()
    assert dlg2._posting and len(stub_poster) == 1
    stub_poster[0].done.emit(True)             # first entry sent
    assert dlg2._posting and len(stub_poster) == 2   # the chain moved on
    assert [e["payload"]["message"]
            for e in load_pending(parent)] == ["بازخورد قدیمی 1"]
    stub_poster[1].done.emit(False)            # Wi-Fi died again
    assert dlg2._chain_active is False         # the chain stops, keeps all
    assert len(load_pending(parent)) == 1
    _flush_dialog(dlg2)
