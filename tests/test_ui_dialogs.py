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


def test_save_feedback_writes_jsonl(lib_with_file, qapp):
    """The feedback form's save path: one JSON line per entry."""
    import json
    from darspack.ui.dialogs import save_feedback
    lib, _, tmp_path = lib_with_file

    class Parent:                       # minimal stand-in for MainWindow
        pass
    Parent.lib = lib
    save_feedback(Parent(), "سؤال: می‌شود فصل را حذف کرد؟")

    lines = (tmp_path / "lib" / "feedback.jsonl").read_text(
        encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["text"].startswith("سؤال")
    logged = lib.conn.execute(
        "SELECT action FROM activity_log ORDER BY id DESC LIMIT 1"
    ).fetchone()["action"]
    assert logged == "feedback"


def test_feedback_button_is_lambda_wired():
    """Qt's clicked signal passes `checked` to plain-function slots —
    wiring feedback_dialog directly crashed (QDialog(False)). Guard the
    wiring so it stays a zero-arg lambda."""
    source = (REPO_ROOT / "src" / "darspack" / "ui" / "main_window.py").read_text(
        encoding="utf-8")
    assert '(tr("btn_feedback"), dialogs.feedback_dialog)' not in source
    assert '(tr("btn_feedback"), lambda: dialogs.feedback_dialog(self))' in source


def test_every_dialog_constructs_offscreen(tmp_path, qapp):
    """Construction sweep: every dialog's __init__ runs without crashing.

    exec()/file dialogs can't run in tests, but the metadata-dialog bug
    lived entirely in __init__ — constructing all dialogs catches that
    whole class before a user ever clicks.
    """
    from types import SimpleNamespace

    from PySide6.QtWidgets import QWidget

    from darspack.ui.dialogs import (
        ClassifyDialog, DuplicatesDialog, ExportDialog, MetadataDialog,
        SettingsDialog, ShareDialog, VerifyReportDialog,
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
        ]
        for build in dialogs_to_build:
            dlg = build()          # any crash here = a user-facing bug
            dlg.deleteLater()


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
    dlg2 = MetadataDialog(None, lib, file_id)
    dlg2.subject.setCurrentText("رياضي")      # same subject, other keyboard
    dlg2._save()
    count = lib.conn.execute("SELECT COUNT(*) c FROM subjects").fetchone()["c"]
    assert count == 1


def test_settings_dialog_writes_json(tmp_path, qapp):
    import json

    from darspack.ui.dialogs import SettingsDialog
    path = tmp_path / "settings.json"
    settings = {"language": "fa", "font_size": 10, "library": ""}
    dlg = SettingsDialog(None, settings, path)
    dlg.lang.setCurrentIndex(1)               # English
    dlg.font_size.setValue(14)
    dlg.library.setText(str(tmp_path))
    dlg._save()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved == {"language": "en", "font_size": 14,
                     "library": str(tmp_path)}


def test_duplicates_dialog_jump_searches_first_name(qapp):
    """_jump parses '[label] name1 ، name2' — the first name must land in
    the main window's search box. The text is built exactly as the dialog
    builds its list items."""
    from types import SimpleNamespace

    from PySide6.QtWidgets import QListWidget, QListWidgetItem, QLineEdit, QWidget

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
