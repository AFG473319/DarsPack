"""Tests for the desktop dialogs (offscreen Qt, no display needed).

The metadata dialog crashed on open when the file had no subject
(IndexError: No item with that key — sqlite3.Row's way of saying the
column is missing). These tests would have caught it.
"""
from pathlib import Path

import pytest

from darspack.core.importer import import_file
from darspack.core.library import Library

# anchored to the repo root, so the suite runs from any working directory
REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def lib_with_file(tmp_path):
    with Library(tmp_path / "lib") as lib:
        src = tmp_path / "نمونه سوال ریاضی فصل 3.pdf"
        src.write_bytes(b"demo")
        import_file(lib, src)
        file_id = lib.conn.execute("SELECT id FROM files").fetchone()["id"]
        yield lib, file_id, tmp_path


def test_metadata_dialog_opens_with_suggestion(lib_with_file, qapp):
    from darspack.ui.dialogs import MetadataDialog
    lib, file_id, _ = lib_with_file
    dlg = MetadataDialog(None, lib, file_id)          # used to crash here
    # The importer no longer auto-applies the SUBJECT (the user classifies
    # in the ClassifyDialog); it shows the stored one — empty here.
    assert dlg.subject.currentText() == ""
    assert dlg.chapter.value() == 3                   # chapter hint kept
    assert dlg.kind.currentText() == "نمونه‌سوال"     # kind hint kept


def test_metadata_dialog_save_updates_catalog(lib_with_file, qapp):
    from darspack.ui.dialogs import MetadataDialog
    lib, file_id, _ = lib_with_file
    dlg = MetadataDialog(None, lib, file_id)
    dlg.subject.setCurrentText("فیزیک")
    dlg.chapter.setValue(4)
    dlg.kind.setCurrentText("جزوه")
    dlg.tags.setText("امتحان، فصل اول")
    dlg.note.setText("تست")
    dlg._save()

    row = lib.conn.execute(
        """SELECT f.chapter, f.kind, f.note, s.name AS subject_name
           FROM files f LEFT JOIN subjects s ON s.id = f.subject_id
           WHERE f.id=?""", (file_id,)).fetchone()
    assert row["subject_name"] == "فیزیک"             # new subject created
    assert row["chapter"] == 4 and row["kind"] == "جزوه"
    tags = [t["name"] for t in lib.conn.execute(
        """SELECT t.name FROM tags t JOIN file_tags ft ON ft.tag_id=t.id
           WHERE ft.file_id=? ORDER BY t.id""", (file_id,))]
    assert tags == ["امتحان", "فصل اول"]


def test_metadata_dialog_opens_for_unclassified_file(tmp_path, qapp):
    """A file with no suggestions at all must still open the dialog."""
    from darspack.ui.dialogs import MetadataDialog
    with Library(tmp_path / "lib") as lib:
        src = tmp_path / "IMG_20260101_1234.pdf"
        src.write_bytes(b"camera-dump")
        import_file(lib, src)
        file_id = lib.conn.execute("SELECT id FROM files").fetchone()["id"]
        dlg = MetadataDialog(None, lib, file_id)
        assert dlg.subject.currentText() == ""


def test_metadata_spinboxes_show_persian_digits(lib_with_file, qapp):
    """Chapter/lesson spinboxes showed Latin 3/0 in the Persian
    UI; a Persian QLocale makes the widget render ۰-۹."""
    from darspack.ui.dialogs import MetadataDialog
    lib, file_id, _ = lib_with_file
    dlg = MetadataDialog(None, lib, file_id)
    dlg.chapter.setValue(3)
    dlg.lesson.setValue(12)
    assert dlg.chapter.text() == "۳"
    assert dlg.lesson.text() == "۱۲"
    assert dlg.chapter.value() == 3               # parsing stays numeric


def test_metadata_dialog_shows_the_file_and_offers_cancel(lib_with_file, qapp):
    """The dialog must say which file is being edited, and Cancel must be
    available (it previously had only the save button)."""
    from PySide6.QtWidgets import QLabel, QPushButton

    from darspack.i18n import tr
    from darspack.ui.dialogs import MetadataDialog
    lib, file_id, _ = lib_with_file
    dlg = MetadataDialog(None, lib, file_id)
    assert any(dlg.row["original_name"] in label.text()
               for label in dlg.findChildren(QLabel))
    assert tr("cancel") in {b.text() for b in dlg.findChildren(QPushButton)}


def test_settings_advanced_fields_are_collapsed(tmp_path, qapp):
    """Feedback endpoints are developer-facing; they live under an
    «پیشرفته» toggle instead of the first screen."""
    from darspack.ui.dialogs import SettingsDialog
    path = tmp_path / "settings.json"
    dlg = SettingsDialog(None, {"language": "fa", "font_size": 10,
                                "library": ""}, path)
    assert dlg.advanced_fields.isHidden()
    dlg.advanced.setChecked(True)
    assert not dlg.advanced_fields.isHidden()


def test_feedback_dialog_offers_cancel(qapp):
    from PySide6.QtWidgets import QPushButton

    from darspack.i18n import tr
    from darspack.ui.dialogs import FeedbackDialog
    dlg = FeedbackDialog(None, {})
    assert tr("cancel") in {b.text() for b in dlg.findChildren(QPushButton)}


def test_metadata_dialog_saves_year_and_lesson_without_a_teacher_field(
        lib_with_file, qapp):
    """A3/A3b: year and lesson persist; the teacher input was removed
    (it confused the flow), and saving must preserve an existing teacher
    rather than wiping it."""
    from darspack.core import db
    from darspack.ui.dialogs import MetadataDialog
    lib, file_id, _ = lib_with_file
    with lib.conn:
        teacher_id = db.get_or_create(lib.conn, "teachers", "آقای رضایی")
        lib.conn.execute("UPDATE files SET teacher_id=? WHERE id=?",
                         (teacher_id, file_id))
    dlg = MetadataDialog(None, lib, file_id)
    assert not hasattr(dlg, "teacher")            # the confusing field is gone
    dlg.subject.setCurrentText("ریاضی")
    dlg.lesson.setValue(7)
    dlg.year.setCurrentText("1403-1404")
    dlg._save()
    row = lib.conn.execute(
        """SELECT f.lesson, f.school_year, f.chapter,
                  t.name AS teacher_name
           FROM files f LEFT JOIN teachers t ON t.id=f.teacher_id
           WHERE f.id=?""", (file_id,)).fetchone()
    assert row["lesson"] == 7
    assert row["school_year"] == "1403-1404"
    assert row["teacher_name"] == "آقای رضایی"   # stored data preserved
    # reopening shows the stored values back
    dlg2 = MetadataDialog(None, lib, file_id)
    assert dlg2.year.currentText() == "1403-1404"
    assert dlg2.lesson.value() == 7


def test_save_feedback_writes_jsonl(lib_with_file, qapp):
    """The feedback form's save path: one JSON line per entry (the full
    payload from build_feedback_payload — same shape as the POST)."""
    import json

    from darspack.ui.dialogs import build_feedback_payload, save_feedback
    lib, _, tmp_path = lib_with_file

    class Parent:                       # minimal stand-in for MainWindow
        pass
    Parent.lib = lib
    payload = build_feedback_payload(5, "fb_cat_praise",
                                     "سؤال: می‌شود فصل را حذف کرد؟", "")
    save_feedback(Parent(), payload)

    lines = (tmp_path / "lib" / "feedback.jsonl").read_text(
        encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["message"].startswith("سؤال")


def test_feedback_button_is_lambda_wired():
    """Qt's clicked signal passes `checked` to plain-function slots —
    wiring feedback_dialog directly crashed (QDialog(False)). Guard the
    wiring so it stays a zero-arg lambda."""
    source = (REPO_ROOT / "src" / "darspack" / "ui" / "main_window.py").read_text(
        encoding="utf-8")
    assert '(tr("btn_feedback"), dialogs.feedback_dialog)' not in source
    assert 'lambda: dialogs.FeedbackDialog(self, self.settings).exec()' in source


def test_every_dialog_constructs_offscreen(tmp_path, qapp):
    """Construction sweep: every dialog's __init__ runs without crashing.

    exec()/file dialogs can't run in tests, but the metadata-dialog bug
    lived entirely in __init__ — constructing all dialogs catches that
    whole class before a user ever clicks.
    """
    from types import SimpleNamespace

    from PySide6.QtWidgets import QWidget

    from darspack.ui.dialogs import (
        ActivityDialog, ClassifyDialog, DuplicatesDialog, ExportDialog,
        FeedbackDialog, MetadataDialog, SettingsDialog, ShareDialog,
        StatsDialog, StatsProgressDialog, VerifyReportDialog,
    )

    with Library(tmp_path / "lib") as lib:
        src = tmp_path / "نمونه سوال ریاضی فصل 3.pdf"
        src.write_bytes(b"demo")
        import_file(lib, src)
        file_id = lib.conn.execute("SELECT id FROM files").fetchone()["id"]

        # a real widget parent (dialogs require QWidget | None) carrying
        # the attributes the dialogs read from the MainWindow
        parent = QWidget()
        parent.lib = lib
        parent.last_rows = []
        group = SimpleNamespace(label_fa="تکراری کامل", rows=[],
                                detail_fa="test")

        dialogs_to_build = [
            lambda: MetadataDialog(parent, lib, file_id),
            lambda: ClassifyDialog(parent, lib, [file_id]),
            lambda: DuplicatesDialog(parent, {"tab": [group]}),
            lambda: ExportDialog(parent, [file_id]),
            lambda: SettingsDialog(parent, {"language": "fa", "font_size": 10,
                                            "library": str(tmp_path)},
                                   tmp_path / "settings.json"),
            lambda: ShareDialog(parent, SimpleNamespace(pin="۱۲۳۴۵۶"),
                                ["http://192.168.1.5:8000/"], on_close=None),
            lambda: VerifyReportDialog(parent, "x.zip",
                                       SimpleNamespace(ok=True, problems=[]),
                                       library=lib, offer_import=False),
            lambda: ActivityDialog(parent, lib),
            lambda: StatsDialog(parent, {"file_count": 0,
                                         "dedup_bytes": 0}),
            lambda: StatsProgressDialog(parent),
            lambda: FeedbackDialog(parent, {"feedback_endpoint": "",
                                            "feedback_form_url": ""}),
        ]
        built = []
        for build in dialogs_to_build:
            dlg = build()          # any crash here = a user-facing bug
            built.append(dlg)
            dlg.deleteLater()
        # Flush the queued deletions INSIDE this test. If they stay pending,
        # a later test's event-loop wait (QTest.qWait) processes them after
        # the parent widget's Python wrapper is gone — an access-violation
        # crash class hit when the debounce tests added qWait to the suite.
        from PySide6.QtCore import QCoreApplication, QEvent
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


# --- interaction edges of the save paths ---------------------------------

def test_metadata_tag_parsing_tolerates_messy_input(lib_with_file, qapp):
    """Mixed commas, doubles, blanks and a repeated tag → exactly a, b, c."""
    from darspack.ui.dialogs import MetadataDialog
    lib, file_id, _ = lib_with_file
    dlg = MetadataDialog(None, lib, file_id)
    dlg.tags.setText("a, b ، ، c ، b")        # Latin + Persian commas, dup
    dlg._save()
    tags = [t["name"] for t in lib.conn.execute(
        """SELECT t.name FROM tags t JOIN file_tags ft ON ft.tag_id=t.id
           WHERE ft.file_id=? ORDER BY t.name""", (file_id,))]
    assert tags == ["a", "b", "c"]            # INSERT OR IGNORE: no dup row


def test_metadata_clearing_tags_removes_links(lib_with_file, qapp):
    from darspack.ui.dialogs import MetadataDialog
    lib, file_id, _ = lib_with_file
    dlg = MetadataDialog(None, lib, file_id)
    dlg.tags.setText("قدیمی")
    dlg._save()
    dlg2 = MetadataDialog(None, lib, file_id)
    dlg2.tags.setText("   ")                  # user wiped the field
    dlg2._save()
    count = lib.conn.execute(
        "SELECT COUNT(*) c FROM file_tags WHERE file_id=?",
        (file_id,)).fetchone()["c"]
    assert count == 0


def test_metadata_subject_reuse_across_spellings(lib_with_file, qapp):
    """«رياضي» (Arabic ي) after «ریاضی» must reuse the same subjects row."""
    from darspack.ui.dialogs import MetadataDialog
    lib, file_id, _ = lib_with_file
    dlg = MetadataDialog(None, lib, file_id)
    dlg.subject.setCurrentText("ریاضی")
    dlg._save()
    first = lib.conn.execute(
        "SELECT subject_id FROM files WHERE id=?", (file_id,)).fetchone()["subject_id"]
    dlg2 = MetadataDialog(None, lib, file_id)
    dlg2.subject.setCurrentText("رياضي")      # same subject, other keyboard
    dlg2._save()
    second = lib.conn.execute(
        "SELECT subject_id FROM files WHERE id=?", (file_id,)).fetchone()["subject_id"]
    # both spellings land on ONE subjects row («ریاضی» is among the A1
    # seeded defaults, so nothing new is created at all)
    count = lib.conn.execute("SELECT COUNT(*) c FROM subjects").fetchone()["c"]
    assert second == first
    assert count == 1      # presets are not seeded: only the saved subject exists


def test_settings_dialog_writes_json(tmp_path, qapp):
    import json

    from darspack.ui.dialogs import SettingsDialog
    path = tmp_path / "settings.json"
    settings = {"language": "fa", "font_size": 10, "library": ""}
    dlg = SettingsDialog(None, settings, path)
    dlg.lang.setCurrentIndex(1)               # English
    dlg.font_size.setValue(14)
    dlg.library.setText(str(tmp_path))
    dlg.fb_endpoint.setText("https://example.test/fb")
    dlg._save()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved == {"language": "en", "font_size": 14,
                     "library": str(tmp_path),
                     "feedback_endpoint": "https://example.test/fb",
                     "feedback_form_url": ""}


def test_duplicates_dialog_jump_searches_first_name(qapp):
    """_jump parses '[label] name1 ، name2' — the first name must land in
    the main window's search box. The text is built exactly as the dialog
    builds its list items."""
    from types import SimpleNamespace

    from PySide6.QtWidgets import QListWidgetItem, QLineEdit, QWidget

    from darspack.ui.dialogs import DuplicatesDialog
    parent = QWidget()
    parent.search_box = QLineEdit()
    group = SimpleNamespace(
        label_fa="تکراری کامل",
        rows=[{"original_name": "نخست.pdf"}, {"original_name": "دوم.pdf"}],
        detail_fa="۲ نسخه‌ی یکسان")
    dlg = DuplicatesDialog(parent, {"tab": [group]})
    text = (f"[{group.label_fa}] "
            f"{' ، '.join(r['original_name'] for r in group.rows)}\n"
            f"    {group.detail_fa}")
    dlg._jump(QListWidgetItem(text))
    assert parent.search_box.text() == "نخست.pdf"


def test_verify_report_dialog_button_only_when_ok(lib_with_file, qapp):
    """ok=True + offer_import → the import button exists; a broken package
    gets no import button. Both variants log to the activity log."""
    from types import SimpleNamespace

    from PySide6.QtWidgets import QPushButton

    from darspack.ui.dialogs import VerifyReportDialog
    lib, _, _ = lib_with_file
    ok_dlg = VerifyReportDialog(None, "x.zip",
                                SimpleNamespace(ok=True, problems=[]),
                                library=lib, offer_import=True)
    assert ok_dlg.findChildren(QPushButton)   # the import button
    bad_dlg = VerifyReportDialog(None, "x.zip",
                                 SimpleNamespace(ok=False,
                                                 problems=["گم‌شده: a.pdf"]),
                                 library=lib, offer_import=True)
    assert not bad_dlg.findChildren(QPushButton)
    actions = [r["action"] for r in lib.conn.execute(
        "SELECT action FROM activity_log ORDER BY id")]
    assert actions.count("verify") == 2       # both dialogs logged


# --- D3: QR code in the share dialog ---------------------------------------

def test_qr_svg_contains_the_url():
    """The QR's SVG embeds the URL as its <title> — the QR modules are
    pure path data, so this is how the content stays pinnable."""
    from darspack.ui.dialogs import qr_svg_bytes
    svg = qr_svg_bytes("http://192.168.1.5:8000/")
    assert svg.startswith(b"<?xml")
    assert b"http://192.168.1.5:8000/" in svg
    assert b"<path" in svg                    # actual QR modules present


def test_pick_lan_url_skips_loopback():
    """N urls → the QR uses the first LAN one; loopback-only → None."""
    from darspack.ui.dialogs import pick_lan_url
    assert pick_lan_url(["http://127.0.0.1:8000/",
                         "http://192.168.1.5:8000/",
                         "http://192.168.1.6:8000/"]) == \
        "http://192.168.1.5:8000/"
    assert pick_lan_url(["http://localhost:8000/"]) is None


def test_share_dialog_renders_qr_for_lan_url(qapp):
    """The share dialog renders an SVG QR widget when a LAN URL exists —
    the construction sweep covers the loopback-only case implicitly."""
    from types import SimpleNamespace

    from PySide6.QtSvgWidgets import QSvgWidget

    from darspack.ui.dialogs import ShareDialog
    dlg = ShareDialog(None, SimpleNamespace(pin="۱۲۳۴۵۶"),
                      ["http://127.0.0.1:8000/", "http://192.168.1.5:8000/"],
                      on_close=None)
    qrs = dlg.findChildren(QSvgWidget)
    assert len(qrs) == 1
    assert qrs[0].size().width() == 180
    dlg.deleteLater()


def test_share_dialog_puts_the_qr_on_a_white_card(qapp):
    """A bare white square on the dark dialog looked unfinished;
    the QR gets a padded white card, the PIN gets a caption line, and
    both PIN and URL are copyable."""
    from types import SimpleNamespace

    from PySide6.QtWidgets import QFrame, QLabel, QPushButton

    from darspack.i18n import tr
    from darspack.ui.dialogs import ShareDialog

    dlg = ShareDialog(None, SimpleNamespace(pin="123456"),
                      ["http://192.168.1.5:8000/"], on_close=None)
    card = dlg.findChild(QFrame, "QrCard")
    assert card is not None
    assert "ffffff" in card.styleSheet().lower()
    assert any(label.text() == tr("share_pin")
               for label in dlg.findChildren(QLabel))
    texts = {button.text() for button in dlg.findChildren(QPushButton)}
    assert tr("copy_pin") in texts and tr("copy_url") in texts
    dlg.deleteLater()


# --- feedback: a real star rating -----------------------------------------

def test_feedback_stars_are_flat_toggles(qapp):
    """The rating rendered as five blue buttons. Stars must be
    flat toggles, and the first N must be checked (gold) after a click."""
    from darspack.ui.dialogs import FeedbackDialog

    dlg = FeedbackDialog(None, {})
    assert len(dlg.star_buttons) == 5
    assert all(button.objectName() == "Star" for button in dlg.star_buttons)
    dlg.star_buttons[3].click()              # 4th star
    assert dlg.rating == 4
    assert [b.isChecked() for b in dlg.star_buttons] == \
        [True, True, True, True, False]
    assert [b.text() for b in dlg.star_buttons] == ["★"] * 4 + ["☆"]
    dlg.deleteLater()


# --- E1/E5/D4: history, stats, live share refresh ---------------------------

def test_activity_dialog_renders_events(lib_with_file, qapp):
    """E1: log rows render with a Jalali date and a Persian action name."""
    from darspack.core import db

    from darspack.ui.dialogs import ActivityDialog
    lib, _, _ = lib_with_file
    db.log(lib.conn, "import", "جزوه فیزیک.pdf → 000001.pdf")
    dlg = ActivityDialog(None, lib)
    table = dlg.event_table
    assert table.rowCount() >= 1
    headers = []
    for col in range(table.columnCount()):
        item = table.item(0, col)
        headers.append(item.text() if item else "")
    assert headers[1] == "وارد کردن"          # action translated
    assert "جزوه فیزیک" in headers[2]         # detail shown
    dlg.deleteLater()


def test_activity_dialog_empty_log_message(tmp_path, qapp):
    """E1: an empty log gets a friendly sentence, not a blank table."""
    from darspack.core.library import Library
    from PySide6.QtWidgets import QLabel, QTableWidget

    from darspack.ui.dialogs import ActivityDialog
    with Library(tmp_path / "lib") as lib:
        lib.conn.execute("DELETE FROM activity_log")   # drop seed_subjects row
        lib.conn.commit()
        dlg = ActivityDialog(None, lib)
        texts = [lbl.text() for lbl in dlg.findChildren(QLabel)]
        assert any("هنوز فعالیتی ثبت نشده" in t for t in texts)
        assert not dlg.findChildren(QTableWidget) or \
            dlg.findChildren(QTableWidget)[0].rowCount() == 0


def test_activity_dialog_forgets_selected_rule(tmp_path, qapp):
    """E1/A4 transparency: the «فراموش کن» button deletes the selected
    hint rule — the app's memory is user-controllable."""
    from darspack.core.suggest import learn_hint, load_hints

    from darspack.ui.dialogs import ActivityDialog
    with Library(tmp_path / "lib") as lib:
        learn_hint(lib.conn, "رضایی", "ریاضی")
        learn_hint(lib.conn, "احمدی", "فیزیک")
        lib.conn.commit()
        dlg = ActivityDialog(None, lib)
        dlg.rule_table.selectRow(0)
        token = dlg.rule_table.item(0, 0).text()
        dlg._forget_selected_rule()
        remaining = load_hints(lib.conn)
        assert token not in remaining
        assert len(remaining) == 1
        assert dlg.rule_table.rowCount() == 1


def test_library_stats_matches_a_planted_fixture(lib_with_file, qapp):
    """E5: the stats match a planted fixture."""
    from darspack.ui.dialogs import library_stats

    lib, fid, _ = lib_with_file
    from darspack.core import db
    with lib.conn:
        sid = db.get_or_create(lib.conn, "subjects", "ریاضی")
        lib.conn.execute("UPDATE files SET subject_id=? WHERE id=?", (sid, fid))
    stats = library_stats(lib.conn)
    assert stats["file_count"] == 1
    assert stats["per_subject"] == [("ریاضی", 1)]
    assert stats["dedup_bytes"] == 0
    assert stats["unclassified"] == 0


def test_stats_dialog_draws_real_progress_bars(lib_with_file, qapp):
    """The Unicode ▓/░ bars rendered as gray tiles in Segoe UI —
    the dialog must use QProgressBar and Persian units instead."""
    from PySide6.QtWidgets import QLabel, QProgressBar

    from darspack.core import db
    from darspack.ui.dialogs import StatsDialog, library_stats

    lib, fid, _ = lib_with_file
    with lib.conn:
        sid = db.get_or_create(lib.conn, "subjects", "ریاضی")
        lib.conn.execute("UPDATE files SET subject_id=? WHERE id=?", (sid, fid))
    dlg = StatsDialog(None, library_stats(lib.conn))
    bars = dlg.findChildren(QProgressBar)
    assert bars and max(b.value() for b in bars) == 1
    texts = " ".join(label.text() for label in dlg.findChildren(QLabel))
    assert "بایت" in texts                    # Persian size unit, no «B»
    dlg.deleteLater()


def test_stats_dialog_dedup_bytes(tmp_path, qapp):
    """E5: a skipped duplicate is space the library never stored; a
    duplicate the user explicitly kept is NOT counted as saved."""
    from darspack.ui.dialogs import StatsDialog, library_stats
    with Library(tmp_path / "lib") as lib:
        src = tmp_path / "a.pdf"
        src.write_bytes(b"same content")
        import_file(lib, src)
        skipped = import_file(lib, src)          # rejected at import
        assert skipped.status == "duplicate"
        stats = library_stats(lib.conn)
        assert stats["file_count"] == 1
        assert stats["dedup_bytes"] == len(b"same content")

        import_file(lib, src, keep_duplicate=True)   # user chose to keep it
        stats = library_stats(lib.conn)
        assert stats["file_count"] == 2
        assert stats["dedup_bytes"] == len(b"same content")   # unchanged
        dlg = StatsDialog(None, stats)      # results-only view since the
        assert dlg is not None              # compute moved to StatsWorker
        dlg.deleteLater()


def test_bulk_edit_dialog_writes_only_chosen_fields(tmp_path, qapp):
    """Bulk reclassify: only the fields the user set are written; fields
    left at «بدون تغییر» keep every row's existing value."""
    from darspack.ui.dialogs import BulkEditDialog
    with Library(tmp_path / "lib") as lib:
        ids = []
        for name in ("a.pdf", "b.pdf"):
            src = tmp_path / name
            src.write_bytes(name.encode())
            ids.append(import_file(lib, src).file_id)
        with lib.conn:
            lib.conn.execute(
                "UPDATE files SET chapter=3, school_year='1404-1405'")

        untouched = BulkEditDialog(None, lib, ids)
        untouched._apply()          # nothing chosen → no write, dialog rejects
        rows = lib.conn.execute("SELECT * FROM files ORDER BY id").fetchall()
        assert [r["kind"] for r in rows] == [None, None]

        dlg = BulkEditDialog(None, lib, ids)
        dlg.kind.setCurrentText("کاربرگ")
        dlg._apply()
        rows = lib.conn.execute("SELECT * FROM files ORDER BY id").fetchall()
        assert [r["kind"] for r in rows] == ["کاربرگ", "کاربرگ"]
        assert all(r["chapter"] == 3 for r in rows)          # untouched
        assert all(r["school_year"] == "1404-1405" for r in rows)
        assert all(r["subject_id"] is None for r in rows)    # untouched
        dlg.deleteLater()
        untouched.deleteLater()


def test_share_dialog_live_refresh(tmp_path, qapp):
    """D4: a phone upload (a new file row) while the share dialog is open
    triggers the owner window's refresh and the new-files label."""
    from types import SimpleNamespace

    from PySide6.QtWidgets import QLabel, QWidget

    from darspack.core.importer import import_file
    from darspack.core.library import Library

    from darspack.ui.dialogs import ShareDialog
    with Library(tmp_path / "lib") as lib:
        parent = QWidget()
        parent.lib = lib
        refreshes = []
        parent.refresh = lambda: refreshes.append(1)
        dlg = ShareDialog(parent, SimpleNamespace(pin="۱۲۳۴۵۶",
                                                  is_running=lambda: True),
                          ["http://192.168.1.5:8000/"], on_close=None)
        assert dlg._upload_label.isHidden()     # no uploads yet → no label
        src = tmp_path / "از گوشی.pdf"
        src.write_bytes(b"phone upload")
        import_file(lib, src)
        dlg._check_files()
        assert refreshes == [1]
        label = [lbl for lbl in dlg.findChildren(QLabel)
                 if "فایل جدید" in lbl.text()]
        assert label                                # «۱ فایل جدید…» shown
        dlg._poll_timer.stop()
        dlg.deleteLater()


def test_metadata_dialog_missing_file_raises(lib_with_file, qapp):
    """M22: a vanished row fails fast with a clear error instead of
    crashing on self.row[...] — callers check first and show a
    status message."""
    from darspack.ui.dialogs import MetadataDialog
    lib, _, _ = lib_with_file
    with pytest.raises(ValueError, match="not found in catalog"):
        MetadataDialog(None, lib, 999999)


def test_share_dialog_shows_latin_pin(lib_with_file, qapp):
    """M23: the PIN on screen must be exactly what the phone accepts —
    Latin digits. Persian digits read off the screen used to fail the
    phone login with a bare 'wrong PIN'."""
    import types

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLabel

    from darspack.ui.dialogs import ShareDialog

    lib, _, _ = lib_with_file
    server = types.SimpleNamespace(pin="123456", port=8765)
    dlg = ShareDialog(None, server,
                      ["http://192.168.1.5:8765/?pin=123456"],
                      on_close=lambda: None)
    pin_label = dlg.findChild(QLabel, "PinDigits")
    assert pin_label is not None
    assert pin_label.text() == "123456"
    assert "۱۲۳۴۵۶" not in pin_label.text()
    assert pin_label.layoutDirection() == Qt.LeftToRight


def test_text_dialog_shows_message_and_confirm_button(qapp, monkeypatch):
    from darspack.ui import dialogs
    created = []
    monkeypatch.setattr(
        dialogs.QMessageBox, "exec",
        lambda self: (created.append(self), 0)[1])
    dialogs.text_dialog(None, "about-title", "about-body")
    assert created[0].windowTitle() == "about-title"
    assert created[0].text() == "about-body"


def test_share_dialog_rotate_pin_keeps_latin_digits(lib_with_file, qapp):
    from PySide6.QtWidgets import QLabel, QPushButton
    from darspack.i18n import tr
    from darspack.ui.dialogs import ShareDialog

    class _Server:
        def __init__(self):
            self.pin = "123456"
            self.port = 8765

        def rotate_pin(self):
            self.pin = "654321"

    server = _Server()
    dlg = ShareDialog(None, server, ["http://192.168.1.5:8765/?pin=123456"],
                      on_close=lambda: None)
    btn = next(b for b in dlg.findChildren(QPushButton) if b.text() == tr("new_pin"))
    btn.click()
    pin_label = dlg.findChild(QLabel, "PinDigits")
    assert pin_label.text() == "654321"
    assert "۶۵۴۳۲۱" not in pin_label.text()


def test_bulk_edit_subject_db_locked_shows_warning_not_crash(lib_with_file, qapp, monkeypatch):
    import sqlite3
    from darspack.core import db
    from darspack.ui import dialogs

    lib, file_id, _ = lib_with_file
    dlg = dialogs.BulkEditDialog(None, lib, [file_id])
    dlg.subject.setEditText("فیزیک")
    monkeypatch.setattr(
        db, "get_or_create",
        lambda *a, **k: (_ for _ in ()).throw(sqlite3.OperationalError("database is locked")),
    )
    warnings = []
    monkeypatch.setattr(dialogs.QMessageBox, "warning", lambda *a, **k: warnings.append(a))
    dlg._apply()
    assert len(warnings) == 1


def test_settings_save_write_error_shows_warning(tmp_path, qapp, monkeypatch):
    from darspack.ui import dialogs

    lib_dir = tmp_path / "lib"
    lib_dir.mkdir()
    settings_path = tmp_path / "settings.json"
    settings = {"language": "fa", "font_size": 10, "library": str(lib_dir)}
    dlg = dialogs.SettingsDialog(None, settings, settings_path)
    monkeypatch.setattr(Path, "write_text",
                        lambda *a, **k: (_ for _ in ()).throw(PermissionError("denied")))
    warnings = []
    monkeypatch.setattr(dialogs.QMessageBox, "warning", lambda *a, **k: warnings.append(a))
    dlg._save()
    assert len(warnings) == 1


def test_verify_report_import_handles_empty_package_without_crashing(lib_with_file, qapp, monkeypatch):
    from darspack.core.manifest import export_package, verify_package
    from darspack.ui import dialogs
    from darspack.ui.main_window import MainWindow

    lib, _, tmp_path = lib_with_file
    empty_pkg = tmp_path / "empty.darspack.zip"
    export_package(lib.conn, lib.files_dir, [], empty_pkg)
    report = verify_package(empty_pkg)

    win = MainWindow(lib.root, {"language": "fa", "font_size": 10, "library": str(lib.root)},
                     tmp_path / "settings.json")
    try:
        dlg = dialogs.VerifyReportDialog(win, empty_pkg, report, library=win.lib, offer_import=True)
        infos = []
        monkeypatch.setattr(dialogs.QMessageBox, "information", lambda *a, **k: infos.append(a))
        dlg._import_contents()
        assert len(infos) == 1
        assert not getattr(win, "_import_busy", False)
    finally:
        win.lib.close()

def test_subject_combo_is_tidy_when_empty(qapp):
    from darspack.ui.dialogs import make_subject_combo
    empty = make_subject_combo([], blank=True)
    assert empty.count() == 0                  # no stray blank entry on first run
    assert empty.property("emptyList") is True
    assert empty.lineEdit().placeholderText() != ""
    empty.showPopup()                          # suppressed: no empty sliver
    assert not empty.view().isVisible()

    one = make_subject_combo(["math"], blank=True)
    assert [one.itemText(i) for i in range(one.count())] == ["", "math"]
    assert one.property("emptyList") is False
